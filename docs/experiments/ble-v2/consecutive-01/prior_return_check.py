"""합성 사본의 앞 동작 복귀 창 제외 집계와, 선택된 NONE·방향 창과 오방향 창의 최근접 비교(진행기록 2026-11-01, 1~3번). 재학습 없음.

사용(저장소 루트에서): ml/.venv/Scripts/python.exe docs/experiments/ble-v2/consecutive-01/prior_return_check.py --label newtcnrotwarpnoaccseq --split S-P3
1) 시각 정의: 학습 라벨은 records의 return_peak_ms(라벨 기준). 33초 기록은 동작 피크 + 320 ms(추정)로 맞춘다.
2) 합성 사본: 앞 동작 복귀 창 = 사본 시간축에서 앞 동작 복귀 피크 −200~−100 ms(first_valid_ms 이전이라 학습에서 제외됨).
   fold별 사본 수와 제외 대상 창 수를 센다(창은 5 샘플 간격으로 생긴다).
3) 최근접 비교: 같은 fold의 실제 선택된 학습 창(NONE·UP·DOWN·LEFT·RIGHT)을 후보로 삼고, 33초 기록의 오방향·정답 창 각각의 가장 가까운 후보 라벨과 출처(원본/합성/속도 복사본)를 센다.
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
CL = list(vr.CLASSES)
EARLY = (-200, -100)


def seq_plan(path, c, usable, starts, nb, cond):
    """seq_augmenter와 같은 난수 순서로 사본 (앞 동작, 이동량)을 다시 뽑는다."""
    seq, aug = cond["seq"], cond["aug"]
    rng = vr.clip_rng(path, 100 + c)
    others = [q for q in usable if q != path]
    prior = others[int(rng.integers(len(others)))]
    gap = float(rng.uniform(0, seq["gap_max_ms"]))
    vr.random_rotation(rng, aug["rot_y_deg"], aug["tilt_deg"])
    start = int(starts[path] / vr.SAMPLE_MS)
    prior_rows = int((nb[prior]["event_ms"] + seq["prior_tail_ms"]) / vr.SAMPLE_MS) - int(starts[prior] / vr.SAMPLE_MS)
    gap_rows = int(gap / vr.SAMPLE_MS)
    shift = (vr.PRECUE_SAMPLES + prior_rows + gap_rows - start) * vr.SAMPLE_MS
    # 사본 시간축: 앞 동작 시작이 PRECUE 행(900 ms)에 놓인다
    prior_rp_copy = nb[prior]["return_peak_ms"] - starts[prior] + vr.PRECUE_SAMPLES * vr.SAMPLE_MS
    return prior, shift, prior_rp_copy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--tag", default="seq-local-20261101")
    a = ap.parse_args()
    _, by_path, nb = vr.load()
    split = v2.load_split(a.split)
    starts = vr.motion_starts()
    cond = vr.CONDITIONS[a.label]
    captured = {}
    original = v2.choose_training

    def capture(y, meta, seed):
        idx = original(y, meta, seed)
        captured.update(y=y, meta=meta, idx=idx)
        return idx

    v2.choose_training = capture
    cases = [c for c in json.loads((HERE / f"comparison-{a.tag}" / "align_reverse.json").read_text(encoding="utf-8"))
             if c["label"] == a.label and c["split"] == a.split]
    ts, raw = vs.read_stream(HERE / "continuous.1.csv")
    bias, static = vs.still_estimates(raw)
    report = {"folds": [], "nearest_wrong": Counter(), "nearest_correct": Counter(), "nearest_wrong_source": Counter()}
    try:
        for k in range(split["cv"]["n_folds"]):
            d, _ = vr.prepare_fold(a.label, by_path, nb, split, k)
            y, meta, idx = captured["y"], captured["meta"], captured["idx"]
            chosen = np.zeros(len(y), dtype=bool)
            chosen[idx] = True
            # 1) 사본별 앞 동작 복귀 창 제외 집계
            val = set(split["cv"]["folds"][k]["validation_sources"])
            pool = [q for q in split["train_sources"] if q not in val and by_path[q]["completion_ms"] is not None]
            usable = sorted(q for q in pool if starts[q] >= vr.PRECUE_SAMPLES * vr.SAMPLE_MS)
            copies = 0
            excluded_windows = 0
            if "seq" in cond:
                ends = np.arange(1590, 200000, 50)  # 창 끝 시각: 160 샘플 창, 5 샘플 간격(10 ms 격자)
                for path in usable:
                    for c in (1, 2):
                        prior, shift, prp = seq_plan(path, c, usable, starts, nb, cond)
                        copies += 1
                        # 앞 동작 복귀 구간(prp −200~−100 ms)에 창 끝이 있는 창 수. first_valid_ms(앞 동작 완료 + 150) 이전이라 제외된다
                        excluded_windows += int(np.sum((ends >= prp + EARLY[0]) & (ends <= prp + EARLY[1])))
            report["folds"].append({"fold": k, "seq_copies": copies, "excluded_prior_return_windows": excluded_windows,
                                    "chosen_total": int(chosen.sum())})
            # 2) 최근접 비교: 선택된 창을 후보로
            # 학습에 실제로 쓰인 창(d["x_train"]) 기준으로 후보를 만든다. idx 순서가 x_train 순서다.
            cand_idx = np.arange(len(d["x_train"]))
            cand_x = d["x_train"].reshape(len(d["x_train"]), -1).astype(np.float64)
            cand_lab = d["y_train"]
            is_copy = np.array(["#" in meta[i]["source_path"] for i in idx])
            cache_stem = None
            for c in [c for c in cases if c["fold"] == k]:
                stem = f"{c['label']}-{c['split']}-20261021-fold{k}-e{c['epoch']}"
                prep = json.loads((vr.model_dir(a.label, a.split, 20261021, k, a.tag) / "prep.json").read_text(encoding="utf-8"))
                x_all, times = vs.stream_inputs(raw, ts, prep, bias, static)
                tindex = {t: i for i, t in enumerate(times)}
                for key, t, bucket in (("wrong", c["wrong_ms"], "nearest_wrong"), ("correct", c["correct_ms"], "nearest_correct")):
                    if t not in tindex:
                        continue
                    q = x_all[tindex[t]].reshape(-1).astype(np.float64)
                    dist = np.sqrt(((cand_x[cand_idx] - q) ** 2).sum(axis=1))
                    j = cand_idx[int(np.argmin(dist))]
                    report[bucket][CL[int(cand_lab[j])]] += 1
                    if key == "wrong":
                        report["nearest_wrong_source"]["copy" if is_copy[j] else "original"] += 1
            print(f"fold {k}: 사본 {copies}개, 선택 창 {int(chosen.sum())}개", flush=True)
    finally:
        v2.choose_training = original
    out = {"label": a.label, "split": a.split, "folds": report["folds"],
           "nearest_wrong": dict(report["nearest_wrong"]), "nearest_correct": dict(report["nearest_correct"]),
           "nearest_wrong_source": dict(report["nearest_wrong_source"])}
    (HERE / f"prior_return_check-{a.label}-{a.split}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("nearest_wrong", "nearest_correct", "nearest_wrong_source")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
