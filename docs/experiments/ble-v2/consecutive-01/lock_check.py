"""잠금 가설 확인(진행기록 2026-11-01, 100건 대조 뒤): 편한 간격 정답보다 앞선 반대 방향 발행이 잠금을 걸어 정답을 밀었는가?

사용(저장소 루트에서): ml/.venv/Scripts/python.exe docs/experiments/ble-v2/consecutive-01/lock_check.py --tag seq-local-20261101
입력: comparison-<tag>의 재생 점수(npz)와 align_reverse.json. 상태기계는 v2.issue_events(R0)와 같은 규칙을 쓴다.
반사실(분석용, 채택 아님): 잠금을 거는 발행을 정답 방향 발행으로 한정했을 때 정답 발행이 언제 나는지 본다.
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


def machine(times, scores, lock_only=None):
    """issue_events와 같은 상태기계. 발행 목록과 (시각, 잠금 상태) 기록을 돌려준다.
    lock_only가 있으면 그 방향 발행만 잠금을 걸고, 나머지 발행은 기록만 하고 잠그지 않는다(반사실)."""
    events, states = [], []
    locked, candidate, count, none_count = False, None, 0, 0
    for t, p in zip(times, scores):
        top = int(np.argmax(p))
        states.append((int(t), locked))
        if locked:
            none_count = none_count + 1 if top == 0 and p[0] >= .8 else 0
            if none_count >= 2:
                locked, candidate, count, none_count = False, None, 0, 0
            continue
        margin = np.sort(p)[-1] - np.sort(p)[-2]
        if top != 0 and p[top] >= .8 and margin >= .2:
            count = count + 1 if top == candidate else 1
            candidate = top
            if count >= 2:
                events.append({"timestamp_ms": int(t), "class_index": top})
                if lock_only is None or CL[top] == lock_only:
                    locked, candidate, count, none_count = True, None, 0, 0
                else:
                    candidate, count = None, 0
        else:
            candidate, count = None, 0
    return events, states


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()
    folder = HERE / f"comparison-{a.tag}"
    cases = json.loads((folder / "align_reverse.json").read_text(encoding="utf-8"))
    rows = []
    cache = {}
    for c in cases:
        stem = f"{c['label']}-{c['split']}-{c['seed']}-fold{c['fold']}-e{c['epoch']}"
        if stem not in cache:
            z = np.load(folder / f"{stem}.npz")
            cache[stem] = (z["times"], z["scores"])
        times, scores = cache[stem]
        events, states = machine(times, scores)
        # 이 사례의 잠금 구간: 오방향 발행 직후부터 해제까지
        lock_at_wrong = next((lk for t, lk in states if t == c["wrong_ms"]), None)
        after = [t for t, lk in states if t > c["wrong_ms"]]
        rel = next((t for t, lk in states if t > c["wrong_ms"] and not lk), None)
        dpeak = c["wrong_ms"] - c["target_peak_ms"]
        i_w = int(np.argmin(np.abs(times - c["wrong_ms"])))
        i_c = int(np.argmin(np.abs(times - c["correct_ms"])))
        rev = CL.index(c["wrong_dir"])
        fwd = CL.index(c["target_dir"])
        # 반사실: 오방향 발행은 잠그지 않는다
        cf_events, _ = machine(times, scores, lock_only=c["target_dir"])
        cf_correct = next((e["timestamp_ms"] for e in cf_events
                           if e["class_index"] == fwd and c["start_ms"] <= e["timestamp_ms"] <= c["end_ms"] + 400), None)
        rows.append({**{k: c[k] for k in ("label", "split", "seed", "fold", "wrong_ms", "correct_ms", "target_peak_ms")},
                     "wrong_minus_peak": dpeak, "locked_before_wrong": bool(lock_at_wrong),
                     "lock_release_ms": rel, "correct_after_release": (c["correct_ms"] - rel) if rel else None,
                     "score_rev_at_wrong": float(scores[i_w, rev]), "score_fwd_at_wrong": float(scores[i_w, fwd]),
                     "score_fwd_at_correct": float(scores[i_c, fwd]),
                     "counterfactual_correct_ms": cf_correct})
    (folder / "lock_check.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    for lab in sorted({r["label"] for r in rows}):
        rs = [r for r in rows if r["label"] == lab]
        print(f"\n{lab} (정답보다 앞선 오방향 {len(rs)}건)")
        print("  오방향 발행 시 이미 잠겨 있던 건:", sum(r["locked_before_wrong"] for r in rs))
        rel = [r["correct_after_release"] for r in rs if r["correct_after_release"] is not None]
        if rel:
            print("  잠금 해제 → 정답 발행 (ms) 중앙값 {:.0f}, 범위 {}~{}".format(np.median(rel), min(rel), max(rel)))
        print("  오방향 시점 점수: 반대 {:.3f}, 정답 방향 {:.3f} (중앙값)".format(
            np.median([r["score_rev_at_wrong"] for r in rs]), np.median([r["score_fwd_at_wrong"] for r in rs])))
        print("  정답 시점 정답 방향 점수 중앙값 {:.3f}".format(np.median([r["score_fwd_at_correct"] for r in rs])))
        cf = [r for r in rs if r["counterfactual_correct_ms"] is not None]
        print("  반사실(오방향이 잠그지 않을 때) 정답 발행 있음 {}/{}건".format(len(cf), len(rs)))
        if cf:
            d = [r["counterfactual_correct_ms"] - r["correct_ms"] for r in cf]
            print("  반사실 정답 시각 − 실제 정답 시각 (ms) 중앙값 {:.0f}, 범위 {}~{}".format(np.median(d), min(d), max(d)))


if __name__ == "__main__":
    main()
