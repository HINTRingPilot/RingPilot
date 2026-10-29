"""다른 방향 발행 진단(학습하지 않는다).

저장소에 올린 결과(results/<tag>/<label>-<split>/seed-*.json.gz)의 발행 기록을 동작 시점(가는 피크·끝점·복귀 피크·r)에 맞춰 나눈다.
방향 클립에서 정답과 다른 방향으로 나간 발행은 채점 종류(early·wrong_direction·late_unmatched)와 무관하게 모두 모은다.
clean_success_rate가 이 발행을 모두 실패로 세기 때문이다.

사용: ml/.venv/Scripts/python.exe ml/v2_wrongdir.py --tag noacc-20261029 --label newtcnrotwarpnoacc --split S-P5 --epoch 60
"""
import argparse
import gzip
import json
from collections import Counter

import numpy as np

import v2
import v2_return as vr

OPPOSITE = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
GYRO = {"gyrX": 3, "gyrY": 4, "gyrZ": 5}
REBOUND_MS = 400          # 복귀 피크 뒤 반동을 찾는 구간
SCORING = "extreme_window"


def phase(t, n):
    """발행 시각 t(ms)가 동작의 어느 구간인지. n은 ble-v2-return records의 한 항목."""
    if t < n["outbound_peak_ms"]:
        return "가는 피크 전"
    if t < n["extreme_ms"]:
        return "가는 피크~끝점"
    if t < n["return_peak_ms"]:
        return "끝점~복귀 피크"
    if t < n["event_ms"]:
        return "복귀 피크~r"
    if t <= n["event_ms"] + vr.EXTREME_AFTER_R_MS:
        return "r~r+300"
    return "r+300 뒤"


def rebound_dps(n, raw):
    """복귀 피크 뒤 REBOUND_MS 안에서 주축 자이로가 가는 방향 부호로 다시 튄 최대 세기(deg/s, 영점 보정 없음). 없으면 0."""
    sign = 1.0 if n["outbound_sign"] == "+" else -1.0
    i0 = n["return_peak_ms"] // 10
    seg = sign * raw[i0:i0 + REBOUND_MS // 10, GYRO[n["dominant_axis"]]]
    return float(max(seg.max(), 0.0))


def load_results(tag, label, split, by_path, nb):
    out = []
    for s in v2.SEEDS:
        path = vr.OUT / "results" / tag / f"{label}-{split}" / f"seed-{s}.json.gz"
        with gzip.open(path, "rt", encoding="utf-8") as f:
            out.append(vr.rescored(json.load(f), SCORING, by_path, nb))
    return out


def off_direction(results, epoch, nb):
    rows = []
    for res in results:
        for fold in res["folds"]:
            for p in fold["per_epoch"][str(epoch)][SCORING]["per_source"]:
                n = nb.get(p["source_path"])
                if n is None:                       # 배경 클립
                    continue
                truth = v2.CLASSES.index(n["direction"])
                correct_t = [t for t, _, kind in p["events"] if kind == "correct"]
                for t, c, kind in p["events"]:
                    if c == truth:
                        continue
                    rows.append({"seed": res["seed"], "held_out": fold["held_out_session"], "source_path": p["source_path"],
                                 "truth": n["direction"], "issued": v2.CLASSES[c], "kind": kind,
                                 "opposite": v2.CLASSES[c] == OPPOSITE[n["direction"]], "phase": phase(t, n),
                                 "t_minus_r_ms": t - n["event_ms"], "after_correct": any(ct < t for ct in correct_t),
                                 "clip_has_correct": bool(correct_t)})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--epoch", type=int, required=True)
    a = ap.parse_args()
    target = vr.OUT / "wrong-direction" / f"{a.tag}-{a.label}-{a.split}-E{a.epoch}.json"
    if target.exists():
        raise FileExistsError(f"{target}가 이미 있다")
    _, by_path, nb = vr.load()
    rows = off_direction(load_results(a.tag, a.label, a.split, by_path, nb), a.epoch, nb)
    rebound = {p: rebound_dps(n, v2.read_sensor(vr.ROOT / p)[1]) for p, n in nb.items()}
    keys = ("kind", "phase", "opposite", "after_correct", "clip_has_correct", "held_out")
    out = {"tag": a.tag, "label": a.label, "split": a.split, "epoch": a.epoch, "scoring": SCORING, "created_kst": v2.now(),
           "total": len(rows), "counts": {k: {str(v): c for v, c in Counter(r[k] for r in rows).items()} for k in keys},
           "rebound_dps": {"median_by_direction": {d: float(np.median([rebound[p] for p, n in nb.items() if n["direction"] == d]))
                                                   for d in OPPOSITE},
                           "after_correct_clips": {p: rebound[p] for p in sorted({r["source_path"] for r in rows if r["after_correct"]})}},
           "events": rows}
    v2.dump(target, out)
    print("다른 방향 발행", len(rows))
    for k in keys:
        print(f"  {k}: {out['counts'][k]}")


if __name__ == "__main__":
    main()
