"""실사용 기록 2개를 방향별·앞 동작 관계별로 나눠 센다(11-03 재채점의 아래 방향 약세·번갈아 낮은 값 확인).
사용: ml/.venv/Scripts/python.exe docs/experiments/ble-v2/field-02/field_breakdown.py
각 기록을 quiet 없음·있음으로 재생하고, 실제 보드에 올라가 있던 규칙의 재생이 보드 발행과 같은지 먼저 확인한다.
동작 후보는 field_check.py와 같다. 사람이 확인한 정답이 아니며 후보 방향도 첫 볼록 부호로 정한 값이다.
앞 동작 관계: 시작 간격 FAST_S 안에 앞 후보가 있으면 같은 방향/반대 방향, 없으면 떨어짐.
격리 재생: 후보 구간 밖 자이로를 영점으로 지운 조각을 재생해 모델 방향을 본다. 후보 방향이 볼록을 잘못 짝지은 값인지 가리는 진단이며 정답이 아니다.
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "ml"))
import tensorflow as tf  # noqa: E402
import v2_erase as ve  # noqa: E402
import v2_stream as vs  # noqa: E402

CL = ["NONE", "UP", "DOWN", "LEFT", "RIGHT"]
HERE = Path(__file__).resolve().parent
RECORDS = {"field-01": (HERE.parent / "field-01", None), "field-02": (HERE, ve.QUIET_MS)}  # 기록, 당시 보드 규칙
FAST_S = [0.7, 1.0, 1.5, 2.0]
TOGGLE_AFTER_S = 3.0
M = ROOT / "ml/models/newtcnrotwarpnoacc-ALL-seed-20261021-E60"
model = tf.keras.models.load_model(M / "e60.keras")
prep = json.loads((M / "export.json").read_text(encoding="utf-8"))


def candidates(ts, y):
    lob, i = [], 0
    while i < len(y):
        if abs(y[i]) > 60:
            j, sg = i, np.sign(y[i])
            while j + 1 < len(y) and np.sign(y[j + 1]) == sg and abs(y[j + 1]) > 30:
                j += 1
            lob.append((i, j, i + int(np.argmax(np.abs(y[i:j + 1]))), int(sg)))
            i = j + 1
        else:
            i += 1
    used, cands = set(), []
    for n in range(len(lob) - 1):
        if n in used:
            continue
        a, b, k, s = lob[n]
        a2, b2, _, s2 = lob[n + 1]  # _: 둘째 볼록 최댓값 위치
        if abs(y[k]) >= 400 and s2 == -s and ts[a2] - ts[b] <= 250:
            cands.append((int(ts[a]), int(ts[b2]), "UP" if s > 0 else "DOWN", round(float(abs(y[k]))), round(float(abs(y[_])))))
            used |= {n, n + 1}
    return cands


def outcome(cand, events):
    a, b, d = cand[:3]
    hit = [e for e in events if a <= e[0] <= b + 400]
    if not hit:
        return "무발행"
    return "정상" if all(e[1] == d for e in hit) else "다른 방향 포함"


def tally(rows):
    out = {"정상": 0, "무발행": 0, "다른 방향 포함": 0}
    for r in rows:
        out[r] += 1
    out["합"] = len(rows)
    return out


def isolated(cand, ts, raw, bias, static):
    ia, ib = int(np.searchsorted(ts, cand[0])), int(np.searchsorted(ts, cand[1]))
    lo = max(0, ia - prep["window"])
    lo -= lo % prep["stride"]
    hi = min(len(ts), ib + 100)
    r = raw[lo:hi].copy()
    r[: ia - lo, 3:6] = bias[lo:ia]
    r[ib - lo + 1 :, 3:6] = bias[ib + 1 : hi]
    ev = ve.replay(lambda x: model.predict_on_batch(x), r, ts[lo:hi], prep, bias[lo:hi], static[lo:hi], ve.MODES["issue150"], quiet_ms=None)
    return [CL[e["class_index"]] for e in ev]


def relation(cands, n, fast_s):
    if n == 0 or cands[n][0] - cands[n - 1][0] > fast_s * 1000:
        return "떨어짐"
    return "같은 방향" if cands[n][2] == cands[n - 1][2] else "반대 방향"


result = {}
for name, (folder, board_quiet) in RECORDS.items():
    ts, raw = vs.read_stream(folder / "continuous.1.csv")
    first = json.loads((folder / "continuous.1.csv.capture.json").read_text(encoding="utf-8"))["first_board_slot"]
    board = [((int(r["slot"]) - first) * 10, r["dir"]) for r in csv.DictReader(open(folder / "board_gestures.csv", encoding="utf-8"))]
    skip = (board[0][0] // 10 - (prep["window"] - 1)) % prep["stride"]  # field_check.py와 같은 판정 격자 맞춤
    ts, raw = ts[skip:], raw[skip:]
    bias, static = vs.still_estimates(raw)
    cands = candidates(ts, (raw[:, 3:6] - bias)[:, 1])
    one = {"앞 행 버림": int(skip), "후보": len(cands), "보드 발행": len(board), "시작 간격 중앙값_s": round(float(np.median(np.diff([c[0] for c in cands]))) / 1000, 2)}
    iso = [isolated(c, ts, raw, bias, static) for c in cands]
    iso_kind = ["일치" if v == [c[2]] else "무발행" if not v else "다름" for v, c in zip(iso, cands)]
    one["격리 재생"] = {d: {k: sum(1 for i, c in zip(iso_kind, cands) if c[2] == d and i == k) for k in ("일치", "다름", "무발행")} for d in ("UP", "DOWN")}
    for rule, quiet in (("quiet 없음", None), ("quiet150", ve.QUIET_MS)):
        ev = ve.replay(lambda x: model.predict_on_batch(x), raw, ts, prep, bias, static, ve.MODES["issue150"], quiet_ms=quiet)
        pc = [(e["timestamp_ms"], CL[e["class_index"]]) for e in ev]
        is_board = quiet == board_quiet
        if is_board and pc != board:
            sys.exit(f"{name}: 재생이 보드 발행과 다르다({len(pc)} vs {len(board)})")
        events = board if is_board else pc
        res = [outcome(c, events) for c in cands]
        toggles = [e[0] for e in events if e[1] in ("LEFT", "RIGHT")]
        after = [n for n, c in enumerate(cands) if any(0 < c[0] - t <= TOGGLE_AFTER_S * 1000 for t in toggles)]
        one[rule] = {
            "출처": "보드 발행" if is_board else "PC 재생",
            "전체": tally(res),
            "방향별": {d: tally([r for r, c in zip(res, cands) if c[2] == d]) for d in ("UP", "DOWN")},
            "앞 동작 관계": {
                f"{f}s": {k: tally([res[n] for n in range(len(cands)) if relation(cands, n, f) == k]) for k in ("같은 방향", "반대 방향", "떨어짐")}
                for f in FAST_S
            },
            "전환 뒤": {"전환 발행": len(toggles), f"{TOGGLE_AFTER_S}s 안 후보": tally([res[n] for n in after])},
            "실패": [
                {"시각_s": round(cands[n][0] / 1000, 2), "방향": cands[n][2], "결과": res[n], "볼록_dps": cands[n][3:5], "격리 재생": iso[n], "앞 후보 방향": cands[n - 1][2] if n else None,
                 "앞 후보 간격_s": round((cands[n][0] - cands[n - 1][0]) / 1000, 2) if n else None}
                for n in range(len(cands)) if res[n] != "정상"
            ],
        }
    result[name] = one

out = HERE / "field-breakdown.json"
out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
for name, one in result.items():
    print(f"== {name} 후보 {one['후보']} 보드 발행 {one['보드 발행']} 앞 행 버림 {one['앞 행 버림']} 격리 재생 {one['격리 재생']}")
    for rule in ("quiet 없음", "quiet150"):
        r = one[rule]
        print(f" {rule}({r['출처']}) 전체 {r['전체']}")
        print(f"   방향별 {r['방향별']}")
        print(f"   1.5s 관계 {r['앞 동작 관계']['1.5s']}")
        print(f"   전환 뒤 {r['전환 뒤']}")
        for f in r["실패"]:
            print("     ", f)
