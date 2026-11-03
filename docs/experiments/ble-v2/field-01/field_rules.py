"""실험 field-01(2026-11-03). 실사용 연속 기록에 발행 규칙 후보를 재생한다.
사용: ml/.venv/Scripts/python.exe docs/experiments/ble-v2/field-01/field_rules.py <continuous.csv>
규칙 후보를 실사용 기록 전체에 재생: quiet = 발행 없이 큰 움직임이 끝나면(|자이로|<30 dps가 Q ms) 지우기, single = 한 판정이라도 T 이상이면 발행."""
import json, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[4]; sys.path.insert(0, str(ROOT / "ml"))
import tensorflow as tf
import v2_stream as vs
M = ROOT / "ml/models/newtcnrotwarpnoacc-ALL-seed-20261021-E60"
model = tf.keras.models.load_model(M / "e60.keras"); prep = json.loads((M / "export.json").read_text(encoding="utf-8"))
CL = ["NONE", "UP", "DOWN", "LEFT", "RIGHT"]
ts0, raw0 = vs.read_stream(Path(sys.argv[1]))
bias, static = vs.still_estimates(raw0)
W, S = prep["window"], prep["stride"]
pred = lambda x: model.predict_on_batch(x)

def replay(quiet=None, single=None, big=300):
    raw = raw0.copy(); x, times = vs.stream_inputs(raw, ts0, prep, bias, static); p = pred(x)
    ends = np.arange(W - 1, len(raw), S); ev = []; pending = None
    L, cand, cnt, nc = False, None, 0, 0; d = 0; armed_big = False
    while d < len(times):
        s = p[d]; top = int(np.argmax(s)); erase = False; end = ends[d]
        if L:
            nc = nc + 1 if top == 0 and s[0] >= .8 else 0
            if nc >= 2: L, cand, cnt, nc = False, None, 0, 0
        else:
            mg = np.sort(s)[-1] - np.sort(s)[-2]
            if top and s[top] >= .8 and mg >= .2:
                cnt = cnt + 1 if top == cand else 1; cand = top
                if cnt >= 2 or (single and s[top] >= single):
                    ev.append((int(times[d]), CL[top])); L, cand, cnt, nc = True, None, 0, 0; pending = d + 3; armed_big = False
            else: cand, cnt = None, 0
        if quiet and not L and pending is None:
            gg = np.abs(raw[end - S + 1:end + 1, 3:6] - bias[end]).max()
            if gg > big: armed_big = True
            q = quiet // 10
            if armed_big and np.abs(raw[end - q + 1:end + 1, 3:6] - bias[end]).max() < 30:
                erase, armed_big = True, False
        if pending is not None and d >= pending: erase, pending = True, None
        if erase:
            raw[:end + 1, 3:6] = bias[end]
            last = int(np.searchsorted(ends, end + W - 1, side="right"))
            if d + 1 < last:
                lo = ends[d + 1] - (W - 1); hi = ends[last - 1] + 1
                redo, _ = vs.stream_inputs(raw[lo:hi], ts0[lo:hi], prep, bias[lo:hi], static[lo:hi]); p[d + 1:last] = pred(redo)
        d += 1
    return ev

g = raw0[:, 3:6] - bias; y = g[:, 1]; lob, i = [], 0
while i < len(y):
    if abs(y[i]) > 60:
        j, sg = i, np.sign(y[i])
        while j + 1 < len(y) and np.sign(y[j + 1]) == sg and abs(y[j + 1]) > 30: j += 1
        lob.append((i, j, i + int(np.argmax(np.abs(y[i:j + 1]))), int(sg))); i = j + 1
    else: i += 1
used, cands = set(), []
for n in range(len(lob) - 1):
    if n in used: continue
    a, b, k, s = lob[n]; a2, b2, k2, s2 = lob[n + 1]
    if abs(y[k]) >= 400 and s2 == -s and ts0[a2] - ts0[b] <= 250:
        cands.append((ts0[a], ts0[b2], "UP" if s > 0 else "DOWN")); used |= {n, n + 1}
def score(ev):
    ok = mis = wrg = 0; matched = set()
    for a, b, d in cands:
        hit = [e for e in ev if a <= e[0] <= b + 400]; matched |= set(hit)
        if any(e[1] == d for e in hit) and all(e[1] == d for e in hit): ok += 1
        elif hit: wrg += 1
        else: mis += 1
    return ok, mis, wrg, len(ev) - len(matched)
print("후보(주 볼록 ≥400 dps)", len(cands))
for name, kw in [("현재", {}), ("quiet100", {"quiet": 100}), ("quiet150", {"quiet": 150}), ("quiet200", {"quiet": 200}), ("single0.95", {"single": .95}), ("single0.99", {"single": .99}), ("quiet150+single0.99", {"quiet": 150, "single": .99})]:
    ev = replay(**kw); ok, mis, wrg, extra = score(ev)
    print(f"{name:20} 정상 {ok:2} 무발행 {mis:2} 다른방향포함 {wrg:2} | 발행 {len(ev)} (후보 밖 {extra})", flush=True)
