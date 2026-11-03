"""실사용 기록 점검: PC 재생(보드 규칙)과 보드 발행 비교, 동작 후보별 정상·무발행·다른 방향.
사용: ml/.venv/Scripts/python.exe docs/experiments/ble-v2/field-02/field_check.py <폴더> [--old]  (continuous.1.csv, 사이드카, board_gestures.csv)
--old: quiet 지우기 없이(11-03 첫 시험 때 규칙) 재생해 동작 후보를 그 발행으로 센다.
동작 후보는 field-01과 같다: 주축(Y) 볼록 |값| >= 400 dps 뒤 250 ms 안의 반대 부호 볼록. 사람이 확인한 정답이 아니다.
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
DIR = Path(sys.argv[1])
M = ROOT / "ml/models/newtcnrotwarpnoacc-ALL-seed-20261021-E60"
model = tf.keras.models.load_model(M / "e60.keras")
prep = json.loads((M / "export.json").read_text(encoding="utf-8"))
ts, raw = vs.read_stream(DIR / "continuous.1.csv")
first = json.loads((DIR / "continuous.1.csv.capture.json").read_text(encoding="utf-8"))["first_board_slot"]
board = [((int(r["slot"]) - first) * 10, r["dir"]) for r in csv.DictReader(open(DIR / "board_gestures.csv", encoding="utf-8"))]
# 보드는 켠 뒤 샘플 수로 판정 격자(50 ms)를 정한다. 기록이 중간부터면 앞 행을 버려 격자를 보드 발행 시점에 맞춘다
skip = (board[0][0] // 10 - (prep["window"] - 1)) % prep["stride"] if board else 0
ts, raw = ts[skip:], raw[skip:]
bias, static = vs.still_estimates(raw)
ev = ve.replay(lambda x: model.predict_on_batch(x), raw, ts, prep, bias, static, ve.MODES["issue150"],
               quiet_ms=None if "--old" in sys.argv else ve.QUIET_MS)
print(f"격자 맞춤: 앞 {skip}행 버림")
pc = [(e["timestamp_ms"], CL[e["class_index"]]) for e in ev]
same = pc == board
print(f"보드 {len(board)}건, PC {len(pc)}건, 시각·방향 일치 {same}")

g = raw[:, 3:6] - bias
y = g[:, 1]
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
    a2, b2, _, s2 = lob[n + 1]
    if abs(y[k]) >= 400 and s2 == -s and ts[a2] - ts[b] <= 250:
        cands.append((ts[a], ts[b2], "UP" if s > 0 else "DOWN"))
        used |= {n, n + 1}
counts = {"정상": 0, "무발행": 0, "다른 방향 포함": 0}
matched = set()
events = pc if "--old" in sys.argv else board
for a, b, d in cands:
    hit = [e for e in events if a <= e[0] <= b + 400]
    matched |= set(hit)
    prev = [e for e in events if e[0] < a]
    gap = f"{(a - prev[-1][0]) / 1000:.2f}s 뒤" if prev else "-"
    if hit and all(e[1] == d for e in hit):
        counts["정상"] += 1
        continue
    kind = "다른 방향 포함" if hit else "무발행"
    counts[kind] += 1
    print(f"  {kind} {a / 1000:6.2f}s {d:4} 직전 발행 {prev[-1][1] if prev else '-'} {gap} 발행 {[e[1] for e in hit]}")
print(f"후보 {len(cands)}: {counts}, 후보 밖 발행 {len(events) - len(matched)} {[e for e in events if e not in matched]}")
