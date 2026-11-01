"""모델이 본 입력 창을 학습 양성 창과 같은 전처리로 비교(진행기록 2026-11-01, 복귀 초반 방향 읽기 확인).

사용(저장소 루트에서): ml/.venv/Scripts/python.exe docs/experiments/ble-v2/consecutive-01/waveform_check.py --label newtcnrotwarpnoacc --split S-P3
대상: align_reverse.json의 해당 라벨·분할 건(정답보다 앞선 반대 방향 발행).
입력: 발행 시각의 판정 창을 stream_inputs로 만든 것(재생과 같은 온라인 영점·정지 추정). 학습 양성 창은 prepare_fold의 x_train 중 양성 라벨.
비교: 오방향 발행 창과 정답 발행 창 각각에 대해, 같은 fold의 학습 양성 창 가운데 가장 가까운 것(유클리드 거리)의 라벨을 센다.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "ml"))
import v2  # noqa: E402
import v2_return as vr  # noqa: E402
import v2_stream as vs  # noqa: E402

HERE = Path(__file__).resolve().parent
CL = list(vr.CLASSES)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--tag", default="seq-local-20261101")
    ap.add_argument("--seed", type=int, default=20261021)
    a = ap.parse_args()
    cases = [c for c in json.loads((HERE / f"comparison-{a.tag}" / "align_reverse.json").read_text(encoding="utf-8"))
             if c["label"] == a.label and c["split"] == a.split]
    ts, raw = vs.read_stream(HERE / "continuous.1.csv")
    bias, static = vs.still_estimates(raw)
    _, by_path, nb = vr.load()
    split = v2.load_split(a.split)
    summary = {"wrong_nearest": {}, "correct_nearest": {}}
    rows = []
    for k in sorted({c["fold"] for c in cases}):
        folder = vr.model_dir(a.label, a.split, a.seed, k, a.tag)
        prep = json.loads((folder / "prep.json").read_text(encoding="utf-8"))
        x_all, times = vs.stream_inputs(raw, ts, prep, bias, static)
        tindex = {t: i for i, t in enumerate(times)}
        d, _ = vr.prepare_fold(a.label, by_path, nb, split, k)
        xtr, ytr = d["x_train"], d["y_train"]
        pos = ytr > 0
        xp = xtr[pos].reshape(pos.sum(), -1).astype(np.float64)
        yp = ytr[pos]
        for c in [c for c in cases if c["fold"] == k]:
            for key, t, bucket in (("wrong", c["wrong_ms"], "wrong_nearest"), ("correct", c["correct_ms"], "correct_nearest")):
                if t not in tindex:
                    continue
                q = x_all[tindex[t]].reshape(-1).astype(np.float64)
                dist = np.sqrt(((xp - q) ** 2).sum(axis=1))
                near = int(np.argmin(dist))
                lab = CL[int(yp[near])]
                summary[bucket][lab] = summary[bucket].get(lab, 0) + 1
                rows.append({"fold": k, "kind": key, "wrong_dir": c["wrong_dir"], "target_dir": c["target_dir"],
                             "nearest_label": lab, "nearest_dist": float(dist[near])})
    out = HERE / f"waveform_check-{a.label}-{a.split}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    print(out)


if __name__ == "__main__":
    main()
