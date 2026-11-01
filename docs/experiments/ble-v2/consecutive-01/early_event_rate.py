"""복귀 초반 반대 방향 발행 비율을 실제 발행 기준으로 센다(진행기록 2026-11-01, 2번).

기준 시각: 라벨 기준 복귀 피크 = 동작 피크 + 320 ms(return_align.py와 같다).
복귀 초반 구간: 라벨 복귀 피크 대비 [−260, −140] ms(100건 추적에서 반대 방향 점수가 높았던 구간).
세는 것: 선택 E fold 모델마다 재생 발행 목록(잠금·2회 연속·점수 차이 조건을 거친 결과) 중 반대 방향 발행이 구간 안에 있는 대상의 비율.
비교용: 앞선 기준(구간 안 어느 창이든 반대 방향 점수 ≥ 0.8)을 같은 대상에 적용한 값.
사용(저장소 루트에서): ml/.venv/Scripts/python.exe docs/experiments/ble-v2/consecutive-01/early_event_rate.py --tag seq-local-20261101
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
GAP_MS = 320
EARLY = (-260, -140)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()
    folder = HERE / f"comparison-{a.tag}"
    targets = json.loads((HERE / "consec_ablation.json").read_text(encoding="utf-8"))
    out = {}
    for lab in ("newtcnrotwarpnoacc", "newtcnrotwarpnoaccseq"):
        for grp, pick in (("comfortable", lambda g: 23000 <= g["peak_ms"] < 31000), ("fast", lambda g: g["peak_ms"] < 13000)):
            gs = [g for g in targets if pick(g)]
            ev_hit = sc_hit = n = 0
            for f in sorted(folder.glob(f"{lab}-*-fold*-e*.json")):
                r = json.loads(f.read_text(encoding="utf-8"))
                if r["epoch"] != r["selected_E"]:
                    continue
                z = np.load(f.with_suffix(".npz"))
                times, scores = z["times"], z["scores"]
                for g in gs:
                    rp = g["peak_ms"] + GAP_MS
                    rev_dir = "DOWN" if g["dir"] == "UP" else "UP"
                    lo, hi = rp + EARLY[0], rp + EARLY[1]
                    n += 1
                    if any(CL[e["class_index"]] == rev_dir and lo <= e["timestamp_ms"] <= hi for e in r["events"]):
                        ev_hit += 1
                    rev = CL.index(rev_dir)
                    m = (times >= lo) & (times <= hi)
                    if m.any() and scores[m, rev].max() >= 0.8:
                        sc_hit += 1
            out[f"{lab}-{grp}"] = {"targets": n, "event_in_early_window": ev_hit, "score08_in_early_window": sc_hit}
            print(f"{lab:24s} {grp:12s} 대상 {n:4d} | 실제 발행 기준 {ev_hit:4d} ({ev_hit / n * 100:5.1f}%) | 점수 0.8 기준 {sc_hit:4d} ({sc_hit / n * 100:5.1f}%)")
    (folder / "early_event_rate.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
