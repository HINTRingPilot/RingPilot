"""편한 간격 동작에서 정답보다 먼저 나온 반대 방향 발행을 원본 신호와 같은 시간축에 놓는다(진행기록 2026-11-01, 100건 대조).

사용(저장소 루트에서): ml/.venv/Scripts/python.exe docs/experiments/ble-v2/consecutive-01/align_reverse.py --tag seq-local-20261101
선택 E fold 모델의 재생 발행을 쓴다. 대상: 편한 간격 대상(23~31 s) 구간 안에서 정답 발행보다 앞선 반대 방향 발행 전부.
출력: comparison-<tag>/align_reverse.json(건별), 요약은 표준출력.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "ml"))
import v2_return as vr  # noqa: E402
import v2_stream as vs  # noqa: E402

HERE = Path(__file__).resolve().parent
SPAN_AFTER_MS = 400
LOBE_DPS = 60.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tag", required=True)
    a = p.parse_args()
    targets = json.loads((HERE / "consec_ablation.json").read_text(encoding="utf-8"))
    comfy = [t for t in targets if 23000 <= t["peak_ms"] < 31000]
    ts, raw = vs.read_stream(HERE / "continuous.1.csv")
    bias = np.median(raw[100:900, 3:6], axis=0)
    gy = raw[:, 3:6] - bias
    folder = HERE / f"comparison-{a.tag}"
    cases = []
    for f in sorted(folder.glob("*-fold*-e*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        if r["epoch"] != r["selected_E"]:
            continue
        ev = r["events"]
        for g in comfy:
            inside = [e for e in ev if g["start_ms"] <= e["timestamp_ms"] <= g["end_ms"] + SPAN_AFTER_MS]
            cor = [e for e in inside if vr.CLASSES[e["class_index"]] == g["dir"]]
            if not cor:
                continue
            c0 = min(e["timestamp_ms"] for e in cor)
            for w in inside:
                if vr.CLASSES[w["class_index"]] == g["dir"] or w["timestamp_ms"] >= c0:
                    continue
                tw = w["timestamp_ms"]
                i0 = int(np.searchsorted(ts, tw - 300))
                i1 = int(np.searchsorted(ts, tw + 100))
                seg = gy[i0:i1, 1]
                prev = [e["timestamp_ms"] for e in ev if e["timestamp_ms"] < tw]
                cases.append({
                    "label": r["label"], "split": r["split"], "seed": r["seed"], "fold": r["fold"], "epoch": r["epoch"],
                    "target_peak_ms": g["peak_ms"], "target_dir": g["dir"],
                    "start_ms": g["start_ms"], "end_ms": g["end_ms"],
                    "wrong_dir": vr.CLASSES[w["class_index"]], "wrong_ms": tw, "correct_ms": c0,
                    "wrong_minus_start": tw - g["start_ms"], "wrong_minus_peak": tw - g["peak_ms"],
                    "gyroY_max_abs_300ms_before": float(np.max(np.abs(seg))) if len(seg) else None,
                    "gyroY_at_wrong_sign": int(np.sign(gy[int(np.searchsorted(ts, tw)), 1])),
                    "prev_event_gap_ms": (tw - max(prev)) if prev else None,
                    "wrong_score": w.get("score"),
                })
    (folder / "align_reverse.json").write_text(json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"건수: {len(cases)} (라벨별 {Counter(c['label'] for c in cases)})")
    for lab in sorted({c["label"] for c in cases}):
        cs = [c for c in cases if c["label"] == lab]
        wm = [c["wrong_minus_start"] for c in cs]
        wp = [c["wrong_minus_peak"] for c in cs]
        print(f"\n{lab}: 정답 발행보다 앞선 오방향 {len(cs)}건")
        print("  정답 대비 (ms):", Counter(c["correct_ms"] - c["wrong_ms"] for c in cs).most_common())
        print("  동작 시작 대비 (ms) 중앙값 {:.0f}, 범위 {}~{}".format(np.median(wm), min(wm), max(wm)))
        print("  동작 피크 대비 (ms) 중앙값 {:.0f}, 범위 {}~{}".format(np.median(wp), min(wp), max(wp)))
        print("  시작 전 발행 {}건 / 시작~피크 {}건 / 피크 후 {}건".format(
            sum(x < 0 for x in wm), sum(0 <= x and y < 0 for x, y in zip(wm, wp)), sum(y >= 0 for y in wp)))
        lobes = [c["gyroY_max_abs_300ms_before"] for c in cs if c["gyroY_max_abs_300ms_before"] is not None]
        print("  직전 300 ms 자이로 Y 최대 |값| 중앙값 {:.0f} dps, 60 dps 이상 {}건".format(np.median(lobes), sum(x >= LOBE_DPS for x in lobes)))
        print("  직전 발행과의 간격(ms) 중앙값 {}".format(np.median([c["prev_event_gap_ms"] for c in cs if c["prev_event_gap_ms"] is not None])))
        print("  발행 점수 중앙값 {}".format(np.median([c["wrong_score"] for c in cs if c["wrong_score"] is not None])))


if __name__ == "__main__":
    main()
