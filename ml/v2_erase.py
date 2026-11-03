"""발행 뒤 입력 지우기(실험 consecutive-01). 재학습 없이 저장 모델로, 발행 뒤 자이로 이력을 영점 값으로 바꾸면 연속 동작이 살아나는지 본다.

지우기 시점: none(안 지움), issue(발행 순간), issue150(발행 150 ms 뒤), rearm(잠금이 풀리는 순간). 지운 뒤 창은 회전각도 그만큼 다시 계산된다.
quiet_ms를 주면 발행 없이 끝난 큰 움직임도 지운다(실험 field-01, 놓친 동작이 창에 남아 다음 동작까지 놓치는 문제).
평가: ① 단일 클립 정검출(끝점~r+300 ms) ② 배경 클립 발행 ③ 합성 쌍(간격별) ④ 33초 연속 기록(온라인 영점).
사용: ml/.venv/Scripts/python.exe ml/v2_erase.py --tag seq-20261031 --out erase.json
"""
import argparse
import json
from pathlib import Path

import numpy as np

import v2
import v2_return as vr
import v2_seq_eval as se
import v2_stream as vs

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/experiments/ble-v2/consecutive-01"
MODES = {"none": None, "issue": 0, "issue150": 3, "rearm": "rearm"}   # 숫자는 발행 뒤 판정 수(50 ms 단위)
LABEL = vr.LABEL
QUIET_MS = 150          # 보드 규칙: 큰 움직임 뒤 이만큼 정지하면 발행 없이도 지운다
QUIET_BIG_DPS = 300     # 큰 움직임: 판정 사이 샘플 중 영점 뺀 |자이로|가 이 값을 넘음
QUIET_STILL_DPS = 30    # 정지: 최근 quiet_ms 동안 영점 뺀 |자이로|가 모두 이 값 미만
PAIR_GAPS = (0, 100, 200, 300, 500, 800)


def replay(predict, raw, ts, prep, bias, static, mode, with_scores=False, quiet_ms=None):
    """발행 규칙(v2.issue_events와 같음)을 판정마다 따라가며, mode 시점에 그때까지의 자이로를 영점으로 바꾼다. 발행 목록을 돌려준다.
    quiet_ms를 주면 잠기지 않고 지우기 예약도 없는 동안 큰 움직임 뒤 quiet_ms 정지가 오면 지운다(보드 gesture_runtime.c와 같은 순서).
    with_scores면 (발행 목록, 판정 시각, 판정 점수)를 돌려준다."""
    raw = raw.copy()
    window, stride = prep["window"], prep["stride"]
    x, times = vs.stream_inputs(raw, ts, prep, bias, static)
    p = predict(x)
    ends = np.arange(window - 1, len(raw), stride)
    events, pending = [], None
    locked, candidate, count, none_count = False, None, 0, 0
    moved = False
    d = 0
    while d < len(times):
        s = p[d]
        top = int(np.argmax(s))
        erase = False
        if locked:
            none_count = none_count + 1 if top == 0 and s[0] >= .8 else 0
            if none_count >= 2:
                locked, candidate, count, none_count = False, None, 0, 0
                erase = mode == "rearm"
        else:
            margin = np.sort(s)[-1] - np.sort(s)[-2]
            if top != 0 and s[top] >= .8 and margin >= .2:
                count = count + 1 if top == candidate else 1
                candidate = top
                if count >= 2:
                    events.append({"timestamp_ms": int(times[d]), "class_index": top, "score": float(s[top])})
                    locked, candidate, count, none_count = True, None, 0, 0
                    moved = False
                    if isinstance(mode, int):
                        pending = d + mode
            else:
                candidate, count = None, 0
        if quiet_ms and not locked and pending is None:
            end = ends[d]
            moved = moved or np.abs(raw[end - stride + 1:end + 1, 3:6] - bias[end]).max() > QUIET_BIG_DPS
            q = int(quiet_ms / prep["sample_ms"])
            if moved and np.abs(raw[end - q + 1:end + 1, 3:6] - bias[end]).max() < QUIET_STILL_DPS:
                erase, moved = True, False
        if pending is not None and d >= pending:
            erase, pending = True, None
        if erase:
            end = ends[d]
            raw[:end + 1, 3:6] = bias[end]       # 보드와 같이 지우는 순간의 영점 하나로 바꾼다
            last = int(np.searchsorted(ends, end + window - 1, side="right"))    # 지운 행이 든 뒤쪽 창만 다시 계산한다
            if d + 1 < last:
                lo = ends[d + 1] - (window - 1)
                hi = ends[last - 1] + 1
                redo, _ = vs.stream_inputs(raw[lo:hi], ts[lo:hi], prep, bias[lo:hi], static[lo:hi])
                p[d + 1:last] = predict(redo)
        d += 1
    return (events, times, p) if with_scores else events


def eval_clips(predict, prep, paths, by_path, nb, mode):
    clean = total = bg_events = bg_clips = other_dir = 0
    for path in paths:
        ts, raw = v2.read_sensor(ROOT / path)
        bias, static = vs.precue_estimates(raw)
        events = replay(predict, raw, ts, prep, bias, static, mode)
        if by_path[path]["completion_ms"] is None:
            bg_clips += 1
            bg_events += len(events)
            continue
        counts, _, _ = vr.classify(by_path[path], events, vr.success_window(path, by_path, nb, "extreme_window"))
        total += 1
        clean += int(counts.get("correct", 0) > 0 and len({e["class_index"] for e in events}) == 1)
        true = vr.CLASSES.index(nb[path]["direction"])
        other_dir += int(any(e["class_index"] != true for e in events))
    return {"clean": clean, "total": total, "other_dir": other_dir, "bg_events": bg_events, "bg_clips": bg_clips}


def eval_pairs(predict, prep, paths, nb, starts, gap, mode):
    hit = wrong = total = 0
    for path, prior in se.pairs_for(paths, starts):
        if prior == path:
            continue
        ts, raw = v2.read_sensor(ROOT / path)
        _, prior_raw = v2.read_sensor(ROOT / prior)
        n = nb[path]
        joined, valid, r2, prior_r2 = vr.compose_sequence(raw, starts[path], n["event_ms"], prior_raw, starts[prior], nb[prior]["event_ms"], gap, 100)
        if vr.positive_windows(r2, len(raw), valid) != vr.positive_windows(n["event_ms"], len(raw), len(raw)):
            continue
        shift = r2 - n["event_ms"]
        bias, static = vs.precue_estimates(joined)
        events = replay(predict, joined[:valid], ts[:valid], prep, bias[:valid], static[:valid], mode)
        later = [e for e in events if e["timestamp_ms"] >= prior_r2 + v2.POSITIVE_MS]
        true = vr.CLASSES.index(n["direction"])
        ok = any(e["class_index"] == true and n["extreme_ms"] + shift <= e["timestamp_ms"] <= r2 + 300 for e in later)
        bad = any(e["class_index"] != true for e in later)
        total += 1
        hit += int(ok and not bad)
        wrong += int(bad)
    return {"hit": hit, "wrong": wrong, "total": total}


def eval_record(predict, prep, raw, ts, gestures, mode):
    """33초 기록. 동작마다 다음 동작 시작 전까지의 발행을 본다. 구간은 앞 5개(빠른 위), 가운데, 뒤 5개(편한 간격)다."""
    bias, static = vs.still_estimates(raw)
    events = replay(predict, raw, ts, prep, bias, static, mode)
    rows = []
    for i, g in enumerate(gestures):
        end = gestures[i + 1]["start_ms"] if i + 1 < len(gestures) else ts[-1]
        inside = [e for e in events if g["start_ms"] <= e["timestamp_ms"] < end]
        true = vr.CLASSES.index(g["dir"])
        rows.append({"right": int(any(e["class_index"] == true for e in inside)), "wrong": int(any(e["class_index"] != true for e in inside))})
    part = lambda a, b: {"right": sum(r["right"] for r in rows[a:b]), "wrong": sum(r["wrong"] for r in rows[a:b]), "n": len(rows[a:b])}
    return {"fast": part(0, 5), "middle": part(5, len(rows) - 5), "easy": part(len(rows) - 5, len(rows)), "events": len(events)}


def selected_epoch(tag, split, by_path, nb):
    res = [vr.rescored(json.loads(vr.result_path(LABEL, split, s, tag).read_text(encoding="utf-8")), "extreme_window", by_path, nb) for s in v2.SEEDS]
    by_e = {e: vr.epoch_stats(res, e, "extreme_window") for e in v2.EPOCH_CANDIDATES}
    return max(v2.EPOCH_CANDIDATES, key=lambda e: (round(by_e[e]["selection_score"], 12), -e))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tag", required=True)
    p.add_argument("--splits", nargs="+", default=["S-P3", "S-P5"])
    p.add_argument("--seeds", type=int, nargs="+", default=list(v2.SEEDS))
    p.add_argument("--out", required=True)
    args = p.parse_args()
    tf = v2.configure_tf()
    _, by_path, nb = vr.load()
    starts = vr.motion_starts()
    rec = np.loadtxt(OUT / "continuous.1.csv", delimiter=",", skiprows=1)
    rec_ts, rec_raw = rec[:, 0], rec[:, 1:]
    gestures = json.loads((OUT / "consec_ablation.json").read_text(encoding="utf-8"))
    result = {"label": LABEL, "tag": args.tag, "created_kst": v2.now(), "splits": {}}
    for sp in args.splits:
        split = v2.load_split(sp)
        epoch = selected_epoch(args.tag, sp, by_path, nb)
        table = {m: {"clips": [], "record": [], "pairs": {str(g): [] for g in PAIR_GAPS}} for m in MODES}
        for seed in args.seeds:
            totals = {m: {"clean": 0, "total": 0, "other_dir": 0, "bg_events": 0, "bg_clips": 0} for m in MODES}
            rec_tot = {m: {} for m in MODES}
            pair_tot = {m: {g: [0, 0, 0] for g in PAIR_GAPS} for m in MODES}
            for k, fold in enumerate(split["cv"]["folds"]):
                path = vr.model_dir(LABEL, sp, seed, k, args.tag)
                model = tf.keras.models.load_model(path / f"e{epoch}.keras")
                prep = json.loads((path / "prep.json").read_text(encoding="utf-8"))
                predict = lambda x: model.predict_on_batch(x)
                val = fold["validation_sources"]
                gest = [q for q in val if by_path[q]["completion_ms"] is not None]
                for name, mode in MODES.items():
                    c = eval_clips(predict, prep, val, by_path, nb, mode)
                    for key in totals[name]:
                        totals[name][key] += c[key]
                    r = eval_record(predict, prep, rec_raw, rec_ts, gestures, mode)
                    for part in ("fast", "middle", "easy"):
                        slot = rec_tot[name].setdefault(part, {"right": 0, "wrong": 0, "n": 0})
                        for key in slot:
                            slot[key] += r[part][key]
                    for g in PAIR_GAPS:
                        q = eval_pairs(predict, prep, gest, nb, starts, g, mode)
                        pair_tot[name][g][0] += q["hit"]
                        pair_tot[name][g][1] += q["wrong"]
                        pair_tot[name][g][2] += q["total"]
                print(f"{sp} seed {seed} fold {k} done", flush=True)
            for name in MODES:
                table[name]["clips"].append({"seed": seed, **totals[name]})
                table[name]["record"].append({"seed": seed, **rec_tot[name]})
                for g in PAIR_GAPS:
                    table[name]["pairs"][str(g)].append({"seed": seed, "hit": pair_tot[name][g][0], "wrong": pair_tot[name][g][1], "total": pair_tot[name][g][2]})
        result["splits"][sp] = {"epoch": epoch, "modes": table}
        for name in MODES:
            cl = table[name]["clips"]
            clean = np.mean([c["clean"] / c["total"] for c in cl]) * 100
            other = sum(c["other_dir"] for c in cl)
            bg = sum(c["bg_events"] for c in cl)
            rc = table[name]["record"]
            parts = {part: (sum(r[part]["right"] for r in rc), sum(r[part]["wrong"] for r in rc), sum(r[part]["n"] for r in rc)) for part in ("fast", "middle", "easy")}
            pairs = " ".join(f"{g}:{np.mean([q['hit'] / q['total'] for q in table[name]['pairs'][str(g)]]) * 100:.0f}" for g in PAIR_GAPS)
            print(f"{sp} E{epoch} {name:9} clean {clean:5.2f}% 다른방향 {other:3} 배경 {bg:3}/{cl[0]['bg_clips'] * len(cl)} | 기록 {parts} | 쌍% {pairs}", flush=True)
    (OUT / args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
