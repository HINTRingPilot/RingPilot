"""NONE 학습 확인(진행기록 2026-11-01, 복귀 초반 방향 읽기 가설): 복귀 초반 창은 NONE로 지정되는가, 그리고 실제로 학습에 뽑히는가?

사용(저장소 루트에서): ml/.venv/Scripts/python.exe docs/experiments/ble-v2/consecutive-01/none_check.py --label newtcnrotwarpnoacc --split S-P3
각 fold의 학습 집합을 prepare_fold로 만들면서 NONE 추출(choose_training) 입력과 선택 번호를 기록한다. 학습 실행은 하지 않는다.
복귀 초반 창: 창 끝 t가 [복귀 피크 − 200, 복귀 피크 − 100] ms(records의 return_peak_ms 기준)에 있는 창.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "ml"))
import v2  # noqa: E402
import v2_return as vr  # noqa: E402

HERE = Path(__file__).resolve().parent
EARLY = (-200, -100)


def seq_shift(path, c, usable, starts, nb, cond):
    """합성 복사본 path#seq<c>의 시간 이동량(ms). seq_augmenter와 같은 난수 순서로 앞 동작·간격을 다시 뽑고, compose_sequence의 식을 쓴다."""
    seq, aug = cond["seq"], cond["aug"]
    rng = vr.clip_rng(path, 100 + c)
    others = [q for q in usable if q != path]
    prior = others[int(rng.integers(len(others)))]
    gap = float(rng.uniform(0, seq["gap_max_ms"]))
    vr.random_rotation(rng, aug["rot_y_deg"], aug["tilt_deg"])
    start = int(starts[path] / vr.SAMPLE_MS)
    prior_rows = int((nb[prior]["event_ms"] + seq["prior_tail_ms"]) / vr.SAMPLE_MS) - int(starts[prior] / vr.SAMPLE_MS)
    gap_rows = int(gap / vr.SAMPLE_MS)
    return (vr.PRECUE_SAMPLES + prior_rows + gap_rows - start) * vr.SAMPLE_MS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--split", required=True)
    a = ap.parse_args()
    _, by_path, nb = vr.load()
    split = v2.load_split(a.split)
    captured = {}
    original = v2.choose_training

    def capture(y, meta, seed):
        idx = original(y, meta, seed)
        captured["y"], captured["meta"], captured["idx"] = y, meta, idx
        return idx

    v2.choose_training = capture
    rows = []
    try:
        for k in range(split["cv"]["n_folds"]):
            t0 = time.time()
            vr.prepare_fold(a.label, by_path, nb, split, k)
            y, meta, idx = captured["y"], captured["meta"], set(captured["idx"].tolist())
            chosen = np.zeros(len(y), dtype=bool)
            chosen[list(idx)] = True
            cand = {"all_in_progress": 0, "early_in_progress": 0, "early_chosen": 0,
                    "early_seq_copy": 0, "early_seq_copy_chosen": 0, "early_rot_copy": 0, "early_rot_copy_chosen": 0,
                    "early_original": 0, "early_original_chosen": 0, "chosen_none_total": int(np.sum(chosen & (y == 0))),
                    "chosen_pos_total": int(np.sum(chosen & (y > 0)))}
            starts = vr.motion_starts()
            val = set(split["cv"]["folds"][k]["validation_sources"])
            pool = [q for q in split["train_sources"] if q not in val and by_path[q]["completion_ms"] is not None]
            usable = sorted(q for q in pool if starts[q] >= vr.PRECUE_SAMPLES * vr.SAMPLE_MS)
            cond = vr.CONDITIONS[a.label]
            for i, m in enumerate(meta):
                if y[i] != 0 or m["none_group"] != "in_progress":
                    continue
                cand["all_in_progress"] += 1
                src = m["source_path"]
                base = src.split("#")[0]
                if "#seq" in src and base in nb:
                    shift = seq_shift(base, int(src.split("#seq")[1]), usable, starts, nb, cond)
                    rp = nb[base]["return_peak_ms"] + shift
                else:
                    rp = nb[base]["return_peak_ms"] if base in nb else None
                if rp is None:
                    continue
                if not (EARLY[0] <= m["timestamp_ms"] - rp <= EARLY[1]):
                    continue
                cand["early_in_progress"] += 1
                cand["early_chosen"] += int(chosen[i])
                if "#seq" in src:
                    cand["early_seq_copy"] += 1
                    cand["early_seq_copy_chosen"] += int(chosen[i])
                elif "#rot" in src:
                    cand["early_rot_copy"] += 1
                    cand["early_rot_copy_chosen"] += int(chosen[i])
                else:
                    cand["early_original"] += 1
                    cand["early_original_chosen"] += int(chosen[i])
            rows.append({"fold": k, **cand, "seconds": round(time.time() - t0, 1)})
            print(k, cand, flush=True)
    finally:
        v2.choose_training = original
    out = HERE / f"none_check-{a.label}-{a.split}.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
