"""연속 기록의 동작마다 입력을 바꿔 재생해 무발행 원인 후보를 나눈다(실험 consecutive-01, 2026-11-01).

사용: ml/.venv/Scripts/python.exe docs/experiments/ble-v2/consecutive-01/consec_ablation.py [--lobes]
조건(대상 동작 시작 = 가는 볼록 앞에서 |자이로|가 가장 작은 지점):
  base    원래 입력
  restN   N ms만 남기고 그 앞을 바꾼다(앞 동작의 어느 부분이 문제인지)
  rest    창 안에서 대상 동작 시작 전 원시값을 기록 첫 정지 구간 값으로 바꾼다(앞 동작 파형 제거 + 회전각 기준이 대상 시작으로 감)
  reref   원시값은 그대로 두고 회전각만 대상 동작 시작에서 0이 되게 옮긴다(회전각 기준만 바꿈)
  scaleK  대상 동작 구간 자이로(영점 뺀 값)를 K배로 줄인다(세기만 바꿈)
  slowK   대상 동작 구간을 K배 느리게 늘린다(속도만 바꿈, 뒤는 잘림)
영점은 보드와 같은 온라인 방식(원래 기록으로 잡은 값)을 모든 조건에 쓴다.
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "ml"))
import tensorflow as tf  # noqa: E402
import v2_stream as vs  # noqa: E402

HERE = Path(__file__).resolve().parent
M = ROOT / "ml/models/newtcnrotwarpnoacc-ALL-seed-20261021-E60"
CL = ["NONE", "UP", "DOWN", "LEFT", "RIGHT"]
SPAN_AFTER_MS = 400        # 대상 판정 구간: 가는 볼록 시작 ~ 돌아오는 볼록 끝 + 400 ms
REST_ROWS = slice(100, 900)  # 기록 첫 정지 구간(1~9 s, |자이로| < 25 dps 확인)

model = tf.keras.models.load_model(M / "e60.keras")
prep = json.loads((M / "export.json").read_text(encoding="utf-8"))
ts, raw = vs.read_stream(HERE / "continuous.1.csv")
bias, static = vs.still_estimates(raw)
W, S = prep["window"], prep["stride"]
mean, std = np.array(prep["norm_mean_6axis"]), np.array(prep["norm_std_6axis"])
g = raw[:, 3:6] - bias


def lobes():
    """주축(Y) 볼록: |값| > 60 dps에서 시작해 같은 부호·|값| > 30인 동안 이어진다. (시작 행, 끝 행, 피크 행, 부호)."""
    out, i, y = [], 0, g[:, 1]
    while i < len(y):
        if abs(y[i]) > 60:
            j, sign = i, np.sign(y[i])
            while j + 1 < len(y) and np.sign(y[j + 1]) == sign and abs(y[j + 1]) > 30:
                j += 1
            out.append((i, j, i + int(np.argmax(np.abs(y[i:j + 1]))), int(sign)))
            i = j + 1
        else:
            i += 1
    return out


def inputs(r, ends, ref=None):
    """stream_inputs와 같은 입력을 지정한 창 끝 행들에 대해 만든다. ref(행)가 창 안이면 회전각을 그 행에서 0으로 옮긴다."""
    win = r[ends[:, None] + np.arange(-(W - 1), 1)[None, :]]
    xn = ((win - mean) / std).astype(np.float32)
    gyro = xn[:, :, 3:6].astype(np.float64) * std[3:6] + mean[3:6] - bias[ends][:, None, :]
    ang = np.cumsum(gyro * (prep["sample_ms"] / 1000), axis=1)
    ang -= ang[:, :1, :]
    if ref is not None:
        k = np.clip(ref - (ends - (W - 1)), 0, W - 1)
        ang -= ang[np.arange(len(ends)), k][:, None, :]
    ang = ang / prep["angle_scale_deg"]
    if prep["angle_mean"] is not None:
        ang = (ang - prep["angle_mean"]) / prep["angle_std"]
    return np.concatenate([xn[:, :, 3:6], ang.astype(np.float32)], axis=2)


def motion_start(go_start):
    """가는 볼록 시작 앞 300 ms 안에서 |자이로|가 가장 작은 행."""
    lo = max(0, go_start - 30)
    mag = np.linalg.norm(g[lo:go_start + 1], axis=1)
    return lo + int(np.argmin(mag))


def variant(name, s, e):
    """대상 동작 [s, e] 행에 조건 name을 적용한 (원시값 사본, 바뀐 대상 끝 행)."""
    r = raw.copy()
    if name.startswith("rest"):
        keep = int(name[4:] or 0) // 10                  # restN: 대상 시작 앞 N ms는 원래 값으로 남긴다
        r[:s - keep] = np.resize(raw[REST_ROWS], (s - keep, 6))
    elif name.startswith("scale"):
        k = float(name[5:])
        r[s:e + 1, 3:6] = bias[s:e + 1] + g[s:e + 1] * k
    elif name.startswith("slow"):
        k = float(name[4:])
        n = int(round((e - s + 1) * k))
        src = np.linspace(s, e, n)
        seg = np.stack([np.interp(src, np.arange(len(raw)), raw[:, c]) for c in range(6)], axis=1)
        tail = raw[e + 1:]
        r[s:] = np.concatenate([seg, tail])[:len(raw) - s]
        e = s + n - 1
    return r, e


def score(r, s, e, direction, ref=None):
    """대상 판정 구간의 정답 방향 최고 점수와, 잠김 없이 발행 조건(1위 ≥ .8, 2위와 .2 차, 2회 연속)을 넘는지."""
    ends = np.arange(W - 1, len(raw), S)
    ends = ends[(ends >= s) & (ends <= e + SPAN_AFTER_MS // 10)]
    p = model.predict(inputs(r, ends, ref), batch_size=256, verbose=0)
    d = CL.index(direction)
    srt = np.sort(p, axis=1)
    ok = (p.argmax(axis=1) == d) & (p[:, d] >= .8) & (srt[:, -1] - srt[:, -2] >= .2)
    fire = bool(np.any(ok[1:] & ok[:-1]))
    return float(p[:, d].max()), fire


L = lobes()
if "--lobes" in sys.argv:
    for a, b, k, sign in L:
        print(f"{ts[k]:7.0f} {'+' if sign > 0 else '-'} {abs(g[k, 1]):5.0f} dps  {ts[a]:.0f}~{ts[b]:.0f}")
    sys.exit()

# 동작 = 400 dps 이상 가는 볼록 + 바로 뒤(250 ms 안) 반대 부호 볼록. 위는 +로 가서 -로 돌아온다(빠른 위 구간 기록 기준).
# 16.5~20 s 번갈아 구간은 방향이 기록과 대조되지 않은 추정이다
targets, i = [], 0
while i < len(L) - 1:
    a, b, k, sign = L[i]
    a2, b2, k2, sign2 = L[i + 1]
    if abs(g[k, 1]) >= 400 and sign2 == -sign and ts[a2] - ts[b] <= 250:
        targets.append((motion_start(a), b2, "UP" if sign > 0 else "DOWN", ts[k]))
        i += 2
    else:
        i += 1

conds = ["base", "rest", "rest150", "rest300", "rest600", "reref", "scale0.7", "scale0.5", "slow1.3", "slow1.6"]
print(f"{'가는 피크 ms':>10} {'방향':>4} {'앞 동작까지 ms':>12} | " + " | ".join(f"{c:>7}" for c in conds))
rows = []
for s, e, d, peak in targets:
    prev = [t for t in targets if t[1] < s]
    gap = s - prev[-1][1] if prev else None
    res = {}
    for c in conds:
        if c == "reref":
            res[c] = score(raw, s, e, d, ref=s)
        else:
            r, e2 = variant(c, s, e)
            res[c] = score(r, s, e2, d)
    rows.append({"peak_ms": peak, "dir": d, "start_ms": float(ts[s]), "end_ms": float(ts[e]),
                 "rest_before_ms": None if gap is None else gap * 10, **{c: {"max": round(v[0], 3), "fire": v[1]} for c, v in res.items()}})
    cells = " | ".join(f"{v[0]:5.2f}{' *' if v[1] else '  '}" for v in res.values())
    print(f"{peak:10.0f} {d:>4} {('-' if gap is None else gap * 10):>12} | {cells}")
(HERE / "consec_ablation.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
