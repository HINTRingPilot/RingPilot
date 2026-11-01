"""복귀 피크를 학습 라벨 기준으로 맞춰 재생 점수와 발행 시각을 다시 본다(진행기록 2026-11-01, 1번).

기준: 학습 클립에서 재 동작 피크→복귀 피크 간격의 중앙값(방향 있는 라벨 294개, 320 ms)을 33초 기록의 동작 피크에 더한다.
33초 기록에는 라벨이 없으므로 이 간격을 고정으로 쓴다(추정치의 자이로 최대 방식은 쓰지 않는다).
사용(저장소 루트에서): ml/.venv/Scripts/python.exe docs/experiments/ble-v2/consecutive-01/return_align.py --tag seq-local-20261101
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "ml"))
import v2_return as vr  # noqa: E402

HERE = Path(__file__).resolve().parent
CL = list(vr.CLASSES)
GAP_MS = 320  # 학습 라벨 기준 중앙값(동작 피크 → 복귀 피크)
OFFS = np.arange(-300, 301, 50)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()
    folder = HERE / f"comparison-{a.tag}"
    targets = json.loads((HERE / "consec_ablation.json").read_text(encoding="utf-8"))
    comfy = [t for t in targets if 23000 <= t["peak_ms"] < 31000]
    cases = json.loads((folder / "align_reverse.json").read_text(encoding="utf-8"))
    trace = {}
    for lab in ("newtcnrotwarpnoacc", "newtcnrotwarpnoaccseq"):
        acc = {int(o): {"fwd": [], "rev": []} for o in OFFS}
        for f in sorted(folder.glob(f"{lab}-*-fold*-e*.json")):
            r = json.loads(f.read_text(encoding="utf-8"))
            if r["epoch"] != r["selected_E"]:
                continue
            z = np.load(f.with_suffix(".npz"))
            times, scores = z["times"], z["scores"]
            for g in comfy:
                rp = g["peak_ms"] + GAP_MS
                fwd, rev = CL.index(g["dir"]), CL.index("DOWN" if g["dir"] == "UP" else "UP")
                for o in OFFS:
                    j = int(np.argmin(np.abs(times - (rp + o))))
                    acc[int(o)]["fwd"].append(float(scores[j, fwd]))
                    acc[int(o)]["rev"].append(float(scores[j, rev]))
        trace[lab] = {str(o): {"fwd_median": float(np.median(v["fwd"])), "rev_median": float(np.median(v["rev"]))}
                      for o, v in acc.items()}
        print(f"\n{lab}: 창 끝 (라벨 복귀 피크 대비 ms) | 정답 방향 점수 | 반대 방향 점수 (중앙값)")
        for o in OFFS:
            t = trace[lab][str(int(o))]
            print(f"  {int(o):5d} | {t['fwd_median']:.3f} | {t['rev_median']:.3f}")
    # 100건의 발행 시각을 같은 기준으로 옮긴다
    offs_w, offs_c = [], []
    for c in cases:
        rp = c["target_peak_ms"] + GAP_MS
        offs_w.append(c["wrong_ms"] - rp)
        offs_c.append(c["correct_ms"] - rp)
    print(f"\n오방향 발행 − 라벨 복귀 피크 (ms): 중앙값 {np.median(offs_w):.0f}, 범위 {min(offs_w)}~{max(offs_w)} ({len(offs_w)}건)")
    print(f"정답 발행 − 라벨 복귀 피크 (ms): 중앙값 {np.median(offs_c):.0f}, 범위 {min(offs_c)}~{max(offs_c)}")
    (folder / "return_align.json").write_text(json.dumps({"gap_ms": GAP_MS, "trace": trace,
                                                          "wrong_minus_rp": offs_w, "correct_minus_rp": offs_c},
                                                         ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
