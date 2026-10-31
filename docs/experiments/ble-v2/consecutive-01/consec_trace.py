"""연속 기록을 저장 모델로 재생해 동작마다 점수·잠금 상태를 본다. 발행을 보드 기록과 맞춰 본다."""
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "ml"))
import tensorflow as tf  # noqa: E402
import v2  # noqa: E402
import v2_stream as vs  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
CSV, LOG = Path(sys.argv[1]), Path(sys.argv[2])
M = ROOT / "ml/models/newtcnrotwarpnoacc-ALL-seed-20261021-E60"
CL = ["NONE", "UP", "DOWN", "LEFT", "RIGHT"]

model = tf.keras.models.load_model(M / "e60.keras")
prep = json.loads((M / "export.json").read_text(encoding="utf-8"))
a = np.loadtxt(CSV, delimiter=",", skiprows=1)
ts, raw = a[:, 0], a[:, 1:]
print("rows", len(a), "duration s", ts[-1] / 1000, "timestamp gaps != 10:", int((np.diff(ts) != 10).sum()))
bias, static = vs.still_estimates(raw)
x, times = vs.stream_inputs(raw, ts, prep, bias, static)
p = model.predict(x, batch_size=512, verbose=0)

# 발행 규칙을 따라가며 판정마다 잠금·재무장을 남긴다
locked = candidate = None
locked, count, nc = False, 0, 0
state, events = [], []
for t, s in zip(times, p):
    top = int(np.argmax(s))
    srt = np.sort(s)
    if locked:
        nc = nc + 1 if top == 0 and s[0] >= .8 else 0
        state.append("L")
        if nc >= 2:
            locked, candidate, count, nc = False, None, 0, 0
        continue
    state.append("U")
    if top != 0 and s[top] >= .8 and srt[-1] - srt[-2] >= .2:
        count = count + 1 if top == candidate else 1
        candidate = top
        if count >= 2:
            events.append((t, CL[top], float(s[top])))
            locked, candidate, count, nc = True, None, 0, 0
    else:
        candidate, count = None, 0
state = np.array(state)
t = np.array(times)

# 보드 발행: 재생 첫 발행과 맞는 슬롯 오프셋을 찾아 시각을 비교한다
rows = [re.search(r"gesture,seq=(\d+) dir=(\w+) score=([\d.]+) slot=(\d+)", l) for l in LOG.read_text(encoding="utf-8").splitlines()]
rows = [r for r in rows if r]
last = rows[-8:] if len(rows) >= 8 else rows
print("board events(last):", [(r.group(1), r.group(2), int(r.group(4))) for r in last])
print("replay events:", [(int(a), b, round(c, 3)) for a, b, c in events])

# 동작 볼록: 주축(Y) 자이로 부호가 같은 |값| > 60 dps 구간
g = raw[:, 3:6] - bias
lobes, i = [], 0
y = g[:, 1]
while i < len(y):
    if abs(y[i]) > 60:
        j, sign = i, np.sign(y[i])
        while j + 1 < len(y) and np.sign(y[j + 1]) == sign and abs(y[j + 1]) > 30:
            j += 1
        k = i + int(np.argmax(np.abs(y[i:j + 1])))
        lobes.append((ts[k], "+" if sign > 0 else "-", abs(y[k]), ts[i], ts[j]))
        i = j + 1
    else:
        i += 1
print("Y lobes (peak ms, sign, dps):")
for lo in lobes:
    sel = (t >= lo[3]) & (t <= lo[4] + 400)
    q = p[sel]
    best = "" if not sel.any() else f"best {CL[int(q[:, 1:].max(axis=0).argmax()) + 1]} {q[:, 1:].max():.2f}, 후보(≥.8) {int((q[:, 1:].max(axis=1) >= .8).sum())}판정, 잠김 {int((state[sel] == 'L').sum())}/{int(sel.sum())}"
    print(f"  {lo[0]:7.0f} {lo[1]} {lo[2]:5.0f} | {best}")
lock_spans = []
for a0, b0, _ in events:
    j = np.searchsorted(t, a0)
    k = j + 1
    while k < len(t) and state[k] == "L":
        k += 1
    lock_spans.append((a0, t[min(k, len(t) - 1)]))
print("lock spans ms:", [(int(u), int(v), int(v - u)) for u, v in lock_spans])

fig, ax = plt.subplots(2, 1, figsize=(16, 7), sharex=True)
ax[0].plot(ts, g[:, 1], color="#eb6834", label="자이로 Y(주축)")
ax[0].plot(ts, g[:, 0], color="#2a78d6", lw=.7, label="X")
ax[0].plot(ts, g[:, 2], color="#1baf7a", lw=.7, label="Z")
ax[0].legend(frameon=False, ncol=3)
ax[0].set_ylabel("deg/s")
for n, c in ((0, "#8a8984"), (1, "#d03b3b"), (2, "#2a78d6")):
    ax[1].plot(t, p[:, n], color=c, marker=".", ms=3, lw=1, label=CL[n])
ax[1].axhline(.8, color="k", lw=1)
ax[1].fill_between(t, 0, 1, where=state == "L", color="#141413", alpha=.10, label="잠김")
for a0, b0, _ in events:
    for x_ in ax:
        x_.axvline(a0, color="#6250d6", lw=1.3)
    ax[1].text(a0, 1.02, b0, color="#6250d6", ha="center", fontsize=9)
ax[1].legend(frameon=False, ncol=4, loc="lower right")
ax[1].set_xlabel("ms")
fig.tight_layout()
out = Path(__file__).with_name("consec_trace.png")
fig.savefig(out, dpi=95, facecolor="white")
print(out)
