"""consecutive-01 33초 기록의 가운데(번갈아) 구간을 보드 모델(ALL)·현재 규칙으로 재생한다.
11-03 재채점의 낮은 값(fold 모델, 정답 약 40%)과 실사용 체감의 차이가 모델·규칙 차이로 설명되는지 본다.
사용: ml/.venv/Scripts/python.exe docs/experiments/ble-v2/field-02/record33_all_model.py
"""
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
REC = HERE.parent / "consecutive-01"
M = ROOT / "ml/models/newtcnrotwarpnoacc-ALL-seed-20261021-E60"
model = tf.keras.models.load_model(M / "e60.keras")
prep = json.loads((M / "export.json").read_text(encoding="utf-8"))
ts, raw = vs.read_stream(REC / "continuous.1.csv")
gestures = json.loads((REC / "consec_ablation.json").read_text(encoding="utf-8"))
bias, static = vs.still_estimates(raw)
mid = gestures[5:-5]

result = {"가운데 동작": [{"시작_s": g["start_ms"] / 1000, "방향": g["dir"]} for g in mid], "규칙": {}}
for name, mode, quiet in (("지우기 없음", ve.MODES["none"], None), ("발행 뒤 지우기", ve.MODES["issue150"], None), ("현재(quiet150 포함)", ve.MODES["issue150"], ve.QUIET_MS)):
    ev = ve.replay(lambda x: model.predict_on_batch(x), raw, ts, prep, bias, static, mode, quiet_ms=quiet)
    rows = {}
    for part, (a, b) in {"빠른 위": (0, 5), "가운데": (5, len(gestures) - 5), "편한 간격": (len(gestures) - 5, len(gestures))}.items():
        right = wrong = 0
        for i in range(a, b):
            end = gestures[i + 1]["start_ms"] if i + 1 < len(gestures) else ts[-1]
            inside = [e for e in ev if gestures[i]["start_ms"] <= e["timestamp_ms"] < end]
            right += any(CL[e["class_index"]] == gestures[i]["dir"] for e in inside)
            wrong += any(CL[e["class_index"]] != gestures[i]["dir"] for e in inside)
        rows[part] = {"정답": int(right), "오답": int(wrong), "동작": b - a}
    rows["발행"] = [[round(e["timestamp_ms"] / 1000, 2), CL[e["class_index"]]] for e in ev if mid[0]["start_ms"] <= e["timestamp_ms"] < gestures[-5]["start_ms"]]
    result["규칙"][name] = rows

(HERE / "record33-all-model.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
