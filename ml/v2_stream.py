"""연속 스트림 재생(계획 Task 8 준비). 긴 녹화를 판정 주기마다 학습 때와 같은 입력으로 만들고, 발행 상태를 끊지 않고 이어서 채점한다.

학습 입력은 클립마다 0~890 ms(정지 구간)로 자이로 영점과 시작 자세 중력을 잡는다. 실제 사용은 끊김 없는 스트림이라
그 시점까지의 데이터로 "직전 정지 구간"을 찾아 쓰는 still_estimates가 대신한다. precue_estimates로 클립 방식을 그대로 넣으면
학습 때 만든 입력과 같아야 한다(테스트로 확인). 입력 처리 순서는 v2_return.prep_values의 recipe와 같고, 보드 C 구현의 기준이다.
"""
import csv
from pathlib import Path

import numpy as np

import v2
import v2_return as vr

STILL_SAMPLES = 50        # 정지 판정 구간(0.5 s)
STILL_STD_DPS = 3.0       # 이 구간 자이로 축별 표준편차가 모두 이 값보다 작으면 정지로 본다(첫 설정값, 녹화로 조정)


def read_stream(path):
    """길이 제한 없이 timestamp + 6축 CSV를 읽는다(v2.read_sensor는 파일 이름별 행 수를 검사해 긴 녹화를 못 읽는다)."""
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["timestamp", *v2.AXES]:
            raise ValueError(f"축 순서가 다르다: {path}")
        a = np.array([[float(r[k]) for k in ("timestamp", *v2.AXES)] for r in reader], dtype=np.float64)
    if len(a) < v2.WINDOW or not np.isfinite(a).all() or not np.all(np.diff(a[:, 0]) == vr.SAMPLE_MS):
        raise ValueError(f"짧거나 값이 이상하거나 10 ms 간격이 끊겼다: {path}")
    return a[:, 0], a[:, 1:]


def precue_estimates(raw):
    """클립 방식: 0~890 ms 자이로 중앙값(영점)과 가속도 평균(시작 자세 중력)을 모든 시점에 쓴다."""
    bias = np.median(raw[:vr.PRECUE_SAMPLES, 3:6], axis=0)
    static = raw[:vr.PRECUE_SAMPLES, 0:3].mean(axis=0)
    return np.tile(bias, (len(raw), 1)), np.tile(static, (len(raw), 1))


def still_estimates(raw, samples=STILL_SAMPLES, still_std=STILL_STD_DPS):
    """인과 방식: 각 시점까지의 마지막 정지 구간에서 자이로 중앙값(영점)과 가속도 평균을 잡는다.
    정지 구간이 나오기 전에는 처음 samples개를 쓴다(켤 때 정지해 있다고 가정)."""
    win = np.lib.stride_tricks.sliding_window_view(raw, samples, axis=0)          # (n - samples + 1, 6, samples)
    still = (win[:, 3:6, :].std(axis=2) < still_std).all(axis=1)
    bias = np.empty((len(raw), 3))
    static = np.empty((len(raw), 3))
    b, s = np.median(raw[:samples, 3:6], axis=0), raw[:samples, 0:3].mean(axis=0)
    for i in range(len(raw)):
        j = i - samples + 1
        if j >= 0 and still[j]:
            b, s = np.median(win[j, 3:6, :], axis=1), win[j, 0:3, :].mean(axis=1)
        bias[i], static[i] = b, s
    return bias, static


def stream_inputs(raw, ts, prep, gyro_bias, acc_static):
    """판정 시점(창 끝)마다 학습과 같은 입력을 만든다. gyro_bias·acc_static은 시점별 (n, 3) 값이고 창 끝 시점 값을 쓴다."""
    window, stride = prep["window"], prep["stride"]
    ends = np.arange(window - 1, len(raw), stride)
    win = raw[ends[:, None] + np.arange(-(window - 1), 1)[None, :]]                  # (판정 수, window, 6)
    mean, std = np.array(prep["norm_mean_6axis"]), np.array(prep["norm_std_6axis"])
    xn = ((win - mean) / std).astype(np.float32)
    if prep.get("acc_mode"):
        raise ValueError(f"가속도 처리 {prep['acc_mode']}는 지원하지 않는다(지난 조건, 커밋 1162a44 이전 이력)")
    parts = [xn[:, :, 0:3], xn[:, :, 3:6]]
    if "angX" in prep["input_channels"]:
        gyro = xn[:, :, 3:6].astype(np.float64) * std[3:6] + mean[3:6] - gyro_bias[ends][:, None, :]
        angle = np.cumsum(gyro * (prep["sample_ms"] / 1000), axis=1)
        angle -= angle[:, :1, :]
        angle = (angle / prep["angle_scale_deg"]).astype(np.float32)
        if prep["angle_mean"] is not None:
            angle = ((angle.astype(np.float64) - prep["angle_mean"]) / prep["angle_std"]).astype(np.float32)
        parts.append(angle)
    x = np.concatenate(parts, axis=2)
    if prep["input_channels"][0] == "gyrX":                                          # drop_acc
        x = x[:, :, 3:]
    assert x.shape[2] == len(prep["input_channels"])
    return x, [int(ts[i]) for i in ends]


def replay(model, raw, ts, prep, estimates="still", issue_fn=v2.issue_events):
    """스트림 전체를 한 번에 재생한다. 발행 상태는 파일 안에서 끊지 않는다. (판정 시각, 점수, 발행 목록)을 돌려준다."""
    est = still_estimates(raw) if estimates == "still" else precue_estimates(raw)
    x, times = stream_inputs(raw, ts, prep, *est)
    scores = model.predict(x, batch_size=512, verbose=0)
    return times, scores, issue_fn(times, scores)
