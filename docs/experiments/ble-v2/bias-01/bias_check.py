"""실험 bias-01: 학습 영점(클립 0~890 ms)과 실사용 온라인 영점(still_estimates, 보드와 같음)이 얼마나 다른지, 영점이 발행에 영향을 주는지.

사용: ml/.venv/Scripts/python.exe docs/experiments/ble-v2/bias-01/bias_check.py
  A. 학습 기준: data/sessions/phone-20261025-*의 방향 클립마다 앞 90행 자이로 중앙값.
  B. 실사용: field-01·02 연속 기록의 온라인 영점 시계열. 학습 범위를 벗어난 시간, 영점이 튄 순간.
  C. 재생: 같은 기록을 영점만 바꿔 보드 규칙(issue150 + quiet)으로 재생하고 동작 후보별 정상·무발행·다른 방향을 센다.
     online = 지금 보드, fixed = 학습 기준 중앙값으로 고정.
결과: bias-01.json, bias_timeline.png. 동작 후보는 field-01과 같은 검출 규칙이며 사람이 확인한 정답이 아니다.
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "ml"))
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import tensorflow as tf  # noqa: E402
import v2_erase as ve  # noqa: E402
import v2_return as vr  # noqa: E402
import v2_stream as vs  # noqa: E402

HERE = Path(__file__).resolve().parent
FIELDS = {"field-01": ROOT / "docs/experiments/ble-v2/field-01", "field-02": ROOT / "docs/experiments/ble-v2/field-02"}
AXES = ("X", "Y", "Z")
CL = ["NONE", "UP", "DOWN", "LEFT", "RIGHT"]

# ---------------------------------------------------------------- A. 학습 기준
train = []
for session in sorted((ROOT / "data/sessions").glob("phone-20261025-*")):
    for f in sorted(session.glob("raw_*.csv")):
        _, raw = vs.read_stream(f)
        train.append(np.median(raw[:vr.PRECUE_SAMPLES, 3:6], axis=0))
train = np.array(train)
ref = np.median(train, axis=0)
lo, hi = np.percentile(train, 1, axis=0), np.percentile(train, 99, axis=0)
print(f"A. 학습 클립 {len(train)}개 신호 전 영점(dps): 중앙값 {np.round(ref, 2)}, 1~99% {np.round(lo, 2)} ~ {np.round(hi, 2)}")

# ---------------------------------------------------------------- B·C. 실사용
M = ROOT / "ml/models/newtcnrotwarpnoacc-ALL-seed-20261021-E60"
model = tf.keras.models.load_model(M / "e60.keras")
prep = json.loads((M / "export.json").read_text(encoding="utf-8"))
predict = lambda x: model.predict_on_batch(x)


def candidates(ts, raw, bias):
    """field-01과 같은 동작 후보: 주축(Y) 볼록 |값| >= 400 dps 뒤 250 ms 안의 반대 부호 볼록."""
    y = (raw[:, 3:6] - bias)[:, 1]
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
    out, used = [], set()
    for n in range(len(lob) - 1):
        if n in used:
            continue
        a, b, k, s = lob[n]
        a2, b2, _, s2 = lob[n + 1]
        if abs(y[k]) >= 400 and s2 == -s and ts[a2] - ts[b] <= 250:
            out.append((ts[a], ts[b2], "UP" if s > 0 else "DOWN"))
            used |= {n, n + 1}
    return out


def count(events, cands):
    c = {"정상": 0, "무발행": 0, "다른 방향 포함": 0}
    for a, b, d in cands:
        hit = [e for e in events if a <= e[0] <= b + 400]
        c["정상" if hit and all(e[1] == d for e in hit) else ("다른 방향 포함" if hit else "무발행")] += 1
    return c


result = {"train": {"clips": len(train), "median": ref.tolist(), "p1": lo.tolist(), "p99": hi.tolist()}, "fields": {}}
fig, axes = plt.subplots(len(FIELDS), 1, figsize=(11, 3.2 * len(FIELDS)), sharey=True)
for ax, (name, d) in zip(np.atleast_1d(axes), FIELDS.items()):
    ts, raw = vs.read_stream(d / "continuous.1.csv")
    first = json.loads((d / "continuous.1.csv.capture.json").read_text(encoding="utf-8"))["first_board_slot"]
    board = [(int(r["slot"]) - first) * 10 for r in csv.DictReader(open(d / "board_gestures.csv", encoding="utf-8"))]
    skip = (board[0] // 10 - (prep["window"] - 1)) % prep["stride"]  # 보드 판정 격자에 맞춘다(field-02 참고)
    ts, raw = ts[skip:], raw[skip:]
    online, static = vs.still_estimates(raw)

    # B. 시계열 통계
    dev = online - ref
    outside = ((online < lo) | (online > hi)).any(axis=1)
    jumps = np.where(np.abs(np.diff(online, axis=0)).max(axis=1) > 3)[0]
    stats = {
        "samples": len(raw),
        "online_median": np.median(online, axis=0).tolist(),
        "max_abs_dev_from_train": np.abs(dev).max(axis=0).tolist(),
        "time_outside_train_1_99_pct": float(outside.mean() * 100),
        "time_dev_over_3dps_pct": float((np.abs(dev).max(axis=1) > 3).mean() * 100),
        "time_dev_over_5dps_pct": float((np.abs(dev).max(axis=1) > 5).mean() * 100),
        "jumps_over_3dps": [{"t_s": round(float(ts[i + 1]) / 1000, 2), "from": np.round(online[i], 1).tolist(),
                             "to": np.round(online[i + 1], 1).tolist()} for i in jumps],
    }
    print(f"\nB. {name}: 온라인 영점 중앙값 {np.round(stats['online_median'], 2)}, 학습 기준과 최대 차 {np.round(stats['max_abs_dev_from_train'], 1)} dps")
    print(f"   학습 1~99% 범위 밖 {stats['time_outside_train_1_99_pct']:.1f}% 시간, 3 dps 넘게 다름 {stats['time_dev_over_3dps_pct']:.1f}%, 5 dps 넘게 {stats['time_dev_over_5dps_pct']:.1f}%")
    for j in stats["jumps_over_3dps"]:
        print(f"   튐 {j['t_s']:7.2f}s {j['from']} → {j['to']}")

    # C. 영점만 바꿔 재생
    cands = candidates(ts, raw, np.tile(ref, (len(raw), 1)))
    variants = {"online": online, "fixed": np.tile(ref, (len(raw), 1))}
    stats["replay"] = {}
    for vname, bias in variants.items():
        ev = ve.replay(predict, raw, ts, prep, bias, static, ve.MODES["issue150"], quiet_ms=ve.QUIET_MS)
        events = [(e["timestamp_ms"], CL[e["class_index"]]) for e in ev]
        c = count(events, cands)
        stats["replay"][vname] = {"events": len(events), **c}
        print(f"C. {name} {vname:6}: 발행 {len(events)}, 후보 {len(cands)}개 중 {c}")
    result["fields"][name] = stats

    t = ts / 1000
    for a, color in zip(range(3), ("C0", "C1", "C2")):
        ax.plot(t, online[:, a], color=color, lw=1.2, label=f"온라인 {AXES[a]}")
        ax.axhspan(lo[a], hi[a], color=color, alpha=0.12)
    ax.set_title(f"{name}: 온라인 영점(선)과 학습 클립 신호 전 영점 1~99% 범위(띠)")
    ax.set_xlabel("시간(초)")
    ax.set_ylabel("영점(dps)")
    ax.legend(loc="lower right", fontsize=8)
plt.rcParams["font.family"] = "Malgun Gothic"
for a in np.atleast_1d(axes):
    for item in [a.title, a.xaxis.label, a.yaxis.label] + a.get_legend().get_texts():
        item.set_fontfamily("Malgun Gothic")
fig.tight_layout()
fig.savefig(HERE / "bias_timeline.png", dpi=110)
(HERE / "bias-01.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
