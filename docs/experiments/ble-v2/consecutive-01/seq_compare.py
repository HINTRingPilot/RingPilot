"""noacc와 seq(앞 동작 합성) 비교 집계(계획 docs/superpowers/plans/2026-11-01-v2-continuous-offline.md Task 2·4).

사용(저장소 루트에서):
  ml/.venv/Scripts/python.exe docs/experiments/ble-v2/consecutive-01/seq_compare.py background --tag T --summary S
  ml/.venv/Scripts/python.exe docs/experiments/ble-v2/consecutive-01/seq_compare.py replay --tag T --summary S
  ml/.venv/Scripts/python.exe docs/experiments/ble-v2/consecutive-01/seq_compare.py score --tag T
background  배경 클립을 idle과 other로 나눠 발행 수/클립 수를 seed별로 센다(선택 E와 E60).
replay      33초 기록 전체를 fold 모델마다 온라인 영점·R0 상태 유지로 재생해 comparison-<T>/에 점수·발행을 저장한다.
score       재생 발행을 consec_ablation.json의 동작 경계에 시간순 일대일로 맞춰 구간별로 센다.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "ml"))
import v2  # noqa: E402
import v2_return as vr  # noqa: E402
import v2_stream as vs  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = ROOT / "docs/experiments/ble-v2/return-label-01"
LABELS = ("newtcnrotwarpnoacc", "newtcnrotwarpnoaccseq")
SPLITS = ("S-P3", "S-P5")
ALL_MODEL = ROOT / "ml/models/newtcnrotwarpnoacc-ALL-seed-20261021-E60"
SPAN_AFTER_MS = 400        # consec_ablation.py와 같은 대상 구간 [시작, 끝 + 400 ms]
GROUPS = {                 # 가는 피크(ms)로 나눈 구간. 번갈아 구간 방향은 볼록 부호로 붙인 추정이다
    "fast_up": (10000, 13000),
    "single_16530": (16000, 17000),
    "alternating_est": (17000, 20000),
    "comfortable": (23000, 31000),
}


def selected_epochs(summary_name):
    s = json.loads((RESULTS / summary_name).read_text(encoding="utf-8"))
    return {(lab, sp): s["panels"][f"{lab}-{sp}"]["extreme_window"]["selected_E"] for lab in LABELS for sp in SPLITS}


def cmd_background(tag, summary_name):
    _, by_path, nb = vr.load()
    sel = selected_epochs(summary_name)
    out = {}
    for lab in LABELS:
        for sp in SPLITS:
            for epoch in sorted({sel[(lab, sp)], 60}):
                rows = []
                for seed in v2.SEEDS:
                    path = vr.result_path(lab, sp, seed, tag)
                    res = vr.rescored(json.loads(path.read_text(encoding="utf-8")), "extreme_window", by_path, nb)
                    c = Counter()
                    for fold in res["folds"]:
                        for p in fold["per_epoch"][str(epoch)]["extreme_window"]["per_source"]:
                            kind = Path(p["source_path"]).name.split(".")[0]
                            if kind in ("idle", "other"):
                                c[f"{kind}_clips"] += 1
                                c[f"{kind}_false"] += p["counts"]["background_false"]
                    rows.append({"seed": seed, **c})
                key = f"{lab}-{sp}-e{epoch}"
                out[key] = {"label": lab, "split": sp, "epoch": epoch, "selected": epoch == sel[(lab, sp)], "per_seed": rows,
                            **{k: sum(r.get(k, 0) for r in rows) for k in ("idle_false", "idle_clips", "other_false", "other_clips")}}
                o = out[key]
                print(f"{key:40s} idle {o['idle_false']:3d}/{o['idle_clips']:3d}  other {o['other_false']:3d}/{o['other_clips']:3d}  "
                      f"other seed별 {[r.get('other_false', 0) for r in rows]}")
    target = RESULTS / f"background-{tag}.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(target)


def replay_one(tf, folder, model_file, prep, raw, ts, out, stem, meta):
    model = tf.keras.models.load_model(folder / model_file)
    times, scores, events = vs.replay(model, raw, ts, prep, estimates="still")
    np.savez_compressed(out / f"{stem}.npz", times=np.array(times), scores=scores)
    (out / f"{stem}.json").write_text(json.dumps({**meta, "estimates": "still", "events": events}, ensure_ascii=False, indent=1) + "\n",
                                      encoding="utf-8")
    tf.keras.backend.clear_session()


def cmd_replay(tag, summary_name):
    tf = v2.configure_tf()
    sel = selected_epochs(summary_name)
    out = HERE / f"comparison-{tag}"
    out.mkdir(exist_ok=False)
    ts, raw = vs.read_stream(HERE / "continuous.1.csv")
    prep = json.loads((ALL_MODEL / "export.json").read_text(encoding="utf-8"))
    replay_one(tf, ALL_MODEL, "e60.keras", prep, raw, ts, out, "reference-ALL-e60", {"label": "reference-ALL", "epoch": 60})
    for lab in LABELS:
        for sp in SPLITS:
            for seed in v2.SEEDS:
                for fold in range(v2.load_split(sp)["cv"]["n_folds"]):
                    folder = vr.model_dir(lab, sp, seed, fold, tag)
                    prep = json.loads((folder / "prep.json").read_text(encoding="utf-8"))
                    for epoch in sorted({sel[(lab, sp)], 60}):
                        meta = {"label": lab, "split": sp, "seed": seed, "fold": fold, "epoch": epoch, "selected_E": sel[(lab, sp)]}
                        replay_one(tf, folder, f"e{epoch}.keras", prep, raw, ts, out, f"{lab}-{sp}-{seed}-fold{fold}-e{epoch}", meta)
            print(lab, sp, "done", flush=True)
    print(out)


def match(events, targets):
    """발행을 시간순으로 대상 구간에 일대일로 맞춘다. 열린(아직 안 맞춘) 대상 중 시작이 가장 이른 것에 붙인다."""
    done = [None] * len(targets)
    extra = Counter()
    for ev in sorted(events, key=lambda e: e["timestamp_ms"]):
        t, d = ev["timestamp_ms"], vr.CLASSES[ev["class_index"]]
        inside = [i for i, g in enumerate(targets) if g["start_ms"] <= t <= g["end_ms"] + SPAN_AFTER_MS]
        open_ = [i for i in inside if done[i] is None]
        if not inside:
            extra["outside"] += 1
        elif not open_:
            extra["duplicate"] += 1
        else:
            i = open_[0]
            if len(open_) > 1:
                extra["ambiguous"] += 1
            if d == targets[i]["dir"]:
                done[i] = "correct"
            else:
                extra["wrong_direction"] += 1
    return done, extra


def group_of(peak):
    return next(k for k, (a, b) in GROUPS.items() if a <= peak < b)


def cmd_score(tag):
    targets = json.loads((HERE / "consec_ablation.json").read_text(encoding="utf-8"))
    folder = HERE / f"comparison-{tag}"
    rows = []
    for f in sorted(folder.glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        done, extra = match(r["events"], targets)
        g = Counter()
        for t, d in zip(targets, done):
            g[f"{group_of(t['peak_ms'])}_correct"] += d == "correct"
            g[f"{group_of(t['peak_ms'])}_total"] += 1
        rows.append({k: r.get(k) for k in ("label", "split", "seed", "fold", "epoch", "selected_E")} | dict(g) | dict(extra))
    (folder / "score.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    # seed별 fold 평균
    keys = [f"{k}_correct" for k in GROUPS] + ["duplicate", "wrong_direction", "outside", "ambiguous"]
    print("reference-ALL-e60:", {k: v for k, v in rows[[r["label"] for r in rows].index("reference-ALL")].items() if k in keys})
    for lab in LABELS:
        for sp in SPLITS:
            for sel_only in (True, False):
                sub = [r for r in rows if r["label"] == lab and r["split"] == sp and (r["epoch"] == r["selected_E"]) == sel_only]
                if not sub:
                    continue
                ep = sub[0]["epoch"]
                per_seed = {s: {k: float(np.mean([r.get(k, 0) for r in sub if r["seed"] == s])) for k in keys} for s in v2.SEEDS}
                tot = {k: sum(r.get(k, 0) for r in sub) for k in keys[-4:]}
                print(f"{lab}-{sp} E{ep}: 빠른 위 seed별 fold 평균 {[round(per_seed[s]['fast_up_correct'], 2) for s in v2.SEEDS]} / 5, "
                      f"편한 {np.mean([per_seed[s]['comfortable_correct'] for s in v2.SEEDS]):.2f} / 5, "
                      f"번갈아(추정) {np.mean([per_seed[s]['alternating_est_correct'] for s in v2.SEEDS]):.2f} / 4, "
                      f"16.53 {np.mean([per_seed[s]['single_16530_correct'] for s in v2.SEEDS]):.2f} / 1, 합계 {tot}")


RULES = ("time", "direction")


def diagnose(events, targets, rule="time"):
    """동작마다 정답·오방향·중복을 센다. rule="time"(기본): 아직 정답이 없는 대상 중 시작이 가장 이른 것에 붙인다(match와 같다).
    rule="direction"(민감도): 구간 안에서 발행 방향과 같은 대상을 먼저 찾고, 없을 때만 미대응 대상에 붙인다.
    오방향 발행은 구간 안의 모든 대상에 붙인다. 중복은 같은 방향 발행이 이미 대응된 대상에 또 나온 경우이고, 모호는 미대응 후보가 둘 이상인 발행 수다."""
    assert rule in RULES
    per = [{"correct": False, "wrong": 0, "dup": 0} for _ in targets]
    outside = ambiguous = 0
    for ev in sorted(events, key=lambda e: e["timestamp_ms"]):
        t, d = ev["timestamp_ms"], vr.CLASSES[ev["class_index"]]
        inside = [i for i, g in enumerate(targets) if g["start_ms"] <= t <= g["end_ms"] + SPAN_AFTER_MS]
        if not inside:
            outside += 1
            continue
        same = [i for i in inside if targets[i]["dir"] == d]
        open_ = [i for i in inside if not per[i]["correct"]]
        if rule == "time":
            if not open_:
                per[inside[0]]["dup"] += 1
            elif targets[open_[0]]["dir"] == d:
                per[open_[0]]["correct"] = True
                ambiguous += len(open_) > 1 and any(targets[i]["dir"] == d for i in open_[1:])
            else:
                for i in inside:
                    per[i]["wrong"] += 1
                ambiguous += len(open_) > 1 and any(targets[i]["dir"] == d for i in open_[1:])
        else:
            if not same:
                for i in inside:
                    per[i]["wrong"] += 1
            else:
                cand = [i for i in same if not per[i]["correct"]]
                if cand:
                    per[cand[0]]["correct"] = True
                    ambiguous += len(cand) > 1
                else:
                    per[same[0]]["dup"] += 1
    cats = []
    for g, p in zip(targets, per):
        if p["correct"]:
            c = "정답+오방향" if p["wrong"] else "정답만"
        else:
            c = "오방향만" if p["wrong"] else "누락"
        cats.append({"group": group_of(g["peak_ms"]), "category": c, "dup": p["dup"]})
    return cats, {"outside": outside, "ambiguous": ambiguous}


def cmd_diagnose(tag):
    targets = json.loads((HERE / "consec_ablation.json").read_text(encoding="utf-8"))
    folder = HERE / f"comparison-{tag}"
    out = {rule: [] for rule in RULES}
    for f in sorted(folder.glob("*-fold*-e*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        if r["epoch"] != r["selected_E"]:
            continue
        for rule in RULES:
            cats, extra = diagnose(r["events"], targets, rule)
            out[rule].append({"label": r["label"], "split": r["split"], "seed": r["seed"], "fold": r["fold"], "epoch": r["epoch"],
                              "targets": cats, **extra})
    (folder / "diagnose.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    cols = ("정답만", "정답+오방향", "오방향만", "누락")
    for rule in RULES:
        print(f"\n== 규칙: {rule}")
        for lab in LABELS:
            for sp in SPLITS:
                sub = [r for r in out[rule] if r["label"] == lab and r["split"] == sp]
                for grp in GROUPS:
                    n = len([t for t in sub[0]["targets"] if t["group"] == grp])
                    avg = {c: float(np.mean([sum(t["category"] == c for t in r["targets"] if t["group"] == grp) for r in sub])) for c in cols}
                    dup = float(np.mean([sum(t["dup"] for t in r["targets"] if t["group"] == grp) for r in sub]))
                    print(f"{lab:24s} {sp} {grp:16s} /{n} " + " ".join(f"{c} {avg[c]:.2f}" for c in cols) + f" 중복 {dup:.2f}")
                ex = float(np.mean([r["outside"] for r in sub])), float(np.mean([r["ambiguous"] for r in sub]))
                print(f"{lab:24s} {sp} 구간 밖 {ex[0]:.2f} 모호 {ex[1]:.2f}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=("background", "replay", "score", "diagnose"))
    p.add_argument("--tag", required=True)
    p.add_argument("--summary")
    a = p.parse_args()
    if a.cmd == "background":
        cmd_background(a.tag, a.summary)
    elif a.cmd == "replay":
        cmd_replay(a.tag, a.summary)
    elif a.cmd == "score":
        cmd_score(a.tag)
    else:
        cmd_diagnose(a.tag)


if __name__ == "__main__":
    main()
