"""발행 규칙 변형과 저장된 점수로 다시 채점(학습하지 않는다).

점수는 학습한 PC의 ml/runs/return-label-01/<tag>/<label>-<split>/seed-<seed>-fold-<k>-scores.npz(깃 제외)에 있다.
분할마다 같은 tag 요약의 선택 E(지금 규칙 기준)에서 규칙만 바꿔 채점한다.

사용: ml/.venv/Scripts/python.exe ml/v2_rules.py --tag noacc-zoon-pc-20261029 --label newtcnrotwarpnoacc --summary summary-noacc-zoon_computer.json
"""
import argparse
import json

import numpy as np

import v2
import v2_return as vr

RULES = {"R0": {"refractory_ms": 0, "rearm": 2},       # 지금 규칙(v2.issue_events와 같다)
         "R1": {"refractory_ms": 500, "rearm": 2},
         "R2": {"refractory_ms": 800, "rearm": 2},
         "R3": {"refractory_ms": 0, "rearm": 4},
         # 복귀 중 반대 방향 발행 24건 중 20건이 연속 2회 판정만 조건을 채웠다
         "R4": {"refractory_ms": 0, "rearm": 2, "consecutive": 3},
         "R5": {"refractory_ms": 500, "rearm": 2, "consecutive": 3}}
SPLITS = ("C", "S-P1", "S-P2", "S-P3", "S-P4", "S-P5")
SCORING = "extreme_window"


def issue_events_rule(times, scores, refractory_ms=0, rearm=2, consecutive=2):
    """v2.issue_events와 같되, 직전 발행 뒤 refractory_ms 안에는 발행하지 않고, 재무장에 확실한 NONE이 rearm번,
    발행에 같은 방향 조건 충족이 consecutive번 연속 필요하다."""
    events, last = [], None
    locked, candidate, count, none_count = False, None, 0, 0
    for t, p in zip(times, scores):
        top = int(np.argmax(p))
        if locked:
            none_count = none_count + 1 if top == 0 and p[0] >= .8 else 0
            if none_count >= rearm:
                locked, candidate, count, none_count = False, None, 0, 0
            continue
        margin = np.sort(p)[-1] - np.sort(p)[-2]
        if top != 0 and p[top] >= .8 and margin >= .2:
            count = count + 1 if top == candidate else 1
            candidate = top
            if count >= consecutive and (last is None or t - last >= refractory_ms):
                events.append({"timestamp_ms": int(t), "class_index": top, "score": float(p[top])})
                locked, candidate, count, none_count, last = True, None, 0, 0, t
        else:
            candidate, count = None, 0
    return events


def val_chunks(split, k, by_path):
    """fold k 검증 원본을 학습 때와 같은 순서(v2.fold_sets)로, 판정 시각만 채운 (record, None, ends, meta)로 돌려준다."""
    val = set(split["cv"]["folds"][k]["validation_sources"])
    chunks = []
    for p in split["train_sources"]:
        if p in val:
            ts, _ = v2.read_sensor(vr.ROOT / p)
            ends = np.arange(v2.WINDOW - 1, len(ts), v2.STRIDE)
            chunks.append((by_path[p], None, ends, [{"timestamp_ms": int(ts[i])} for i in ends]))
    return chunks


def score_with(val, scores, by_path, nb, issue_fn):
    """v2_return.score와 같은 클립별 채점을 발행 함수 issue_fn(times, scores)로 한다."""
    offset, per_source = 0, []
    for record, _, labels, meta in val:
        n = len(labels)
        events = issue_fn([m["timestamp_ms"] for m in meta], scores[offset:offset + n])
        counts, delays, kinds = vr.classify(record, events, vr.success_window(record["source_path"], by_path, nb, SCORING))
        per_source.append({"source_path": record["source_path"], "counts": counts, "delays_ms": delays, "events": kinds})
        offset += n
    assert offset == len(scores)
    return per_source


def rescore(tag, label, split_name, epoch, rule, by_path, nb):
    """seed별로 fold 점수를 규칙 rule로 다시 채점해 v2_return.epoch_stats가 읽는 결과 모양으로 돌려준다."""
    split = v2.load_split(split_name)
    fn = lambda times, scores: issue_events_rule(times, scores, **RULES[rule])
    seeds = []
    for s in v2.SEEDS:
        folds = []
        for k in range(split["cv"]["n_folds"]):
            npz = vr.run_dir(tag) / f"{label}-{split_name}" / f"seed-{s}-fold-{k}-scores.npz"
            scores = np.load(npz)[f"e{epoch}"]
            per_source = score_with(val_chunks(split, k, by_path), scores, by_path, nb, fn)
            folds.append({"per_epoch": {str(epoch): {SCORING: {"per_source": per_source}}}})
        seeds.append({"folds": folds})
    return seeds


def off_direction_count(seeds, epoch, nb):
    """방향 클립에서 정답과 다른 방향으로 나간 발행 수(seed 합)."""
    return sum(1 for res in seeds for f in res["folds"] for p in f["per_epoch"][str(epoch)][SCORING]["per_source"]
               if p["source_path"] in nb
               for _, c, _ in p["events"] if c != v2.CLASSES.index(nb[p["source_path"]]["direction"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--summary", required=True, help="같은 tag의 summarize 결과 파일 이름(분할별 선택 E를 읽는다)")
    ap.add_argument("--rules", nargs="+", choices=list(RULES), default=list(RULES), help="R0는 항상 포함해 요약과 맞는지 확인한다")
    ap.add_argument("--out", help="결과 파일 이름(기본 rules-<tag>-<label>.json)")
    a = ap.parse_args()
    names = ["R0"] + [r for r in a.rules if r != "R0"]
    target = vr.OUT / (a.out or f"rules-{a.tag}-{a.label}.json")
    if target.exists():
        raise FileExistsError(f"{target}가 이미 있다")
    summary = json.loads((vr.OUT / a.summary).read_text(encoding="utf-8"))
    _, by_path, nb = vr.load()
    out = {"tag": a.tag, "label": a.label, "summary": a.summary, "rules": {n: RULES[n] for n in names}, "scoring": SCORING,
           "created_kst": v2.now(), "panels": {}}
    for sp in SPLITS:
        panel = summary["panels"][f"{a.label}-{sp}"][SCORING]
        e = panel["selected_E"]
        out["panels"][sp] = {"epoch": e}
        for name in names:
            seeds = rescore(a.tag, a.label, sp, e, name, by_path, nb)
            st = vr.epoch_stats(seeds, e, SCORING)
            if name == "R0":       # 지금 규칙으로 다시 채점하면 요약과 같아야 한다(점수와 판정 시각 정렬 확인)
                assert abs(st["clean_success_rate"] - panel["by_epoch"][str(e)]["clean_success_rate"]) < 1e-12
            row = {k: st[k] for k in ("clean_success_rate", "no_issue_rate", "background_false_per_clip", "delay_median_ms")}
            row["off_direction"] = off_direction_count(seeds, e, nb)
            out["panels"][sp][name] = row
            print(f"{sp} E{e} {name}: 정검출 {row['clean_success_rate'] * 100:.2f}% 무발행 {row['no_issue_rate'] * 100:.2f}% "
                  f"다른 방향 {row['off_direction']} 배경 {row['background_false_per_clip']:.3f} 지연 {row['delay_median_ms']}")
    out["aggregate"] = {name: {"s_mean_clean_success_rate": float(np.mean([out["panels"][sp][name]["clean_success_rate"] for sp in SPLITS[1:]])),
                               "c_clean_success_rate": out["panels"]["C"][name]["clean_success_rate"],
                               "off_direction_total": sum(out["panels"][sp][name]["off_direction"] for sp in SPLITS),
                               "background_false_mean": float(np.mean([out["panels"][sp][name]["background_false_per_clip"] for sp in SPLITS])),
                               "s_mean_no_issue_rate": float(np.mean([out["panels"][sp][name]["no_issue_rate"] for sp in SPLITS[1:]])),
                               "delay_median_mean_ms": float(np.mean([out["panels"][sp][name]["delay_median_ms"] for sp in SPLITS]))}
                        for name in names}
    v2.dump(target, out)
    for name, agg in out["aggregate"].items():
        print(f"{name}: S 평균 {agg['s_mean_clean_success_rate'] * 100:.2f}% C {agg['c_clean_success_rate'] * 100:.2f}% "
              f"다른 방향 합 {agg['off_direction_total']} 배경 평균 {agg['background_false_mean']:.3f}")


if __name__ == "__main__":
    main()
