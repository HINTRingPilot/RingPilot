"""실험 field-01: 실사용 기록에서 C 런타임(quiet 지우기 포함)과 PC 재생의 발행을 비교한다.
사용: RINGPILOT_CC=<컴파일러> ml/.venv/Scripts/python.exe docs/experiments/ble-v2/field-01/c_field.py docs/experiments/ble-v2/field-01/continuous.1.csv
"""
import json, sys, tempfile
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "ml"))
import tensorflow as tf
import v2_export_c as xc, v2_erase as ve, v2_stream as vs
ROOT = Path(__file__).resolve().parents[4]
M = ROOT / "ml/models/newtcnrotwarpnoacc-ALL-seed-20261021-E60"
model = tf.keras.models.load_model(M / "e60.keras"); prep = json.loads((M / "export.json").read_text(encoding="utf-8"))
ts, raw = vs.read_stream(Path(sys.argv[1]))
bias, static = vs.still_estimates(raw)
for q in (None, ve.QUIET_MS):
    ev = ve.replay(lambda x: model.predict_on_batch(x), raw, ts, prep, bias, static, ve.MODES["issue150"], quiet_ms=q)
    print("PC quiet", q, len(ev))
with tempfile.TemporaryDirectory() as w:
    xc.write_header(model, prep, Path(w) / "gesture_weights.h")
    same_header = (Path(w) / "gesture_weights.h").read_text(encoding="utf-8") == (ROOT / "firmware/gesture_infer/src/gesture_weights.h").read_text(encoding="utf-8")
    exe = Path(w) / "h.exe"; xc.build_host(w, exe)
    idx, sc, iss, _ = xc.run_stream(exe, raw[:, 3:6], w)
c = [(int(ts[i]), int(k)) for i, k in zip(idx, iss) if k >= 0]
print("header same as board:", same_header, "| C", len(c), "same:", c == [(e["timestamp_ms"], e["class_index"]) for e in ev])
