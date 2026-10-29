"""BLE v2 라벨 시각 비교: 기존 e(완전히 멈춘 시점) vs 새 e(복귀 피크 뒤 주축이 절반으로 내려온 시점 r).

v2_cal.py와 같은 분할·fold·seed·NONE 추출·모델·학습(60 epoch, 1·5·10·20·30·40·60 epoch 예측 저장)을 쓰고,
조건(CONDITIONS)마다 라벨 시각과 입력만 바꾼다.
  old       방향 라벨 e ≤ t < e+150 ms
  new       방향 라벨 r ≤ t < r+150 ms (제외 구간 없음, 나머지 NONE)
  newangle  new + 회전각 3채널(창 시작 대비 누적 자이로, 클립 중앙값 영점 보정, 45도로 나눔). 입력 9채널
  newtcn    newangle과 같은 입력·라벨, 모델만 TCN(model.build_tcn: 커널 3, dilation 1·2·4·8·16·49, 16채널,
            블록당 합성곱 1개, 드롭아웃 0.1, 정규화 없음, 마지막 시점 판정, 4,613 파라미터)
  newtcnhard newtcn + 학습 NONE 추출 변경: choose_training이 고른 in_progress NONE 수는 그대로 두고 그 절반을
            "가는 피크 ~ 끝점"에 끝나는 창(가는 볼록 하강, 반대 방향 발행이 나던 구간)에서 클립을 돌아가며 뽑는다.
            idle·other·post_completion 선택과 NONE 총량은 바꾸지 않는다.
  newtcnnorm newtcn + 회전각 3채널을 fold 학습 창의 축별 평균·표준편차로 정규화(다른 6채널과 같은 크기로 맞춤).
  newtcnrt   newtcnnorm과 같되 회전각 영점을 인과적으로 잡는다: 클립 0~900 ms(동작 신호 전 정지 구간) 자이로 중앙값.
            첫 판정(1590 ms)보다 앞선 데이터만 쓰므로 실시간 영점 추정에 해당한다.
  newtcnrot  newtcnrt + 학습 원본마다 회전 사본 2개(R = R_tilt·R_y(θ), θ ~ U(±30°), X-Z 평면 임의 축 둘레 ±15°).
            가속도는 중력까지 돌리고 자이로는 원본 0~890 ms 영점을 뺀 뒤 돌려 다시 더한다. 회전각 영점은 사본에서 다시 잡는다.
            계획: docs/superpowers/plans/2026-10-27-v2-augmentation.md §6
  newtcnrotwarp newtcnrot의 회전 사본(같은 R)에 속도 변형을 더한다. s ~ 로그 균등(0.8, 1.25), 890 ms 고정점,
            0~890 ms(영점 구간)는 그대로, 900 ms부터 원본 시각 890 + (t − 890)/s 값을 보간하고 자이로는 영점을 뺀 뒤 1/s배.
            라벨 r' = 890 + s(r − 890). 배경·동작 시작 < 900 ms·양성 창 수가 줄어드는 사본·경계 점프 > 2 dps 사본은 회전만(newtcnrot 사본 그대로).
            계획: 같은 문서 §7(3차 개정)
각 학습 결과를 두 채점으로 모두 매긴다. 발행 규칙(v2.issue_events)과 E 선택 규칙은 그대로다.
  old_window  [e, e+500 ms]
  new_window  [복귀 피크, r+500 ms]
  extreme_window [끝점, r+300 ms] (2026-10-29부터 주 채점). 끝점 = 가는 동작 주축 자이로가 0을 지나 복귀가 시작되는 순간.
              복귀 중 같은 방향 발행은 일러도 정답이다. 이전 결과는 저장된 발행 기록으로 다시 분류한다(rescored).
새 e는 tools/derive-return-labels.js가 만든 data/annotations/ble-v2-return/records.json에서 읽는다.
요약은 모든 방향 클립으로 계산하고, data/annotations/ble-v2/weak-gestures.json의 약한 동작 검출률을 by_epoch[E]["weak"]에 따로 적는다.

사용 (ml/.venv/Scripts/python.exe ml/v2_return.py <명령>):
  run --label old|new|newangle|newtcn|newtcnhard|newtcnnorm|newtcnrt|newtcnrot|newtcnrotwarp --split C|S-P5 --seed N [--tag T]   한 seed의 모든 fold 학습·채점
  run-all [--parallel 8] [--labels L ...] [--splits S ...] [--tag T]   빠진 (label, split, seed)를 실행(기본은 모든 조건·분할)
  summarize [--out summary.json] [--tag T] [--splits S ...] [--exclude-weak]   요약 작성(이미 있으면 거부). --exclude-weak이면 약한 동작을 정검출·E 선택에서 뺀다
--tag를 주면 결과는 ml/runs/return-label-01/<T>/, 로그는 OUT/logs/<T>/에 둔다(다른 PC·재실행 결과를 기존 것과 나눔).
로그는 덮어쓰지 않는다(이미 있으면 run-all이 시작하지 않는다).
"""

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from collections import Counter

import numpy as np

import v2
from v2 import CLASSES, DOC, ROOT, digest, dump, now

NEW_RECORDS = ROOT / "data/annotations/ble-v2-return/records.json"
WEAK_GESTURES = ROOT / "data/annotations/ble-v2/weak-gestures.json"
CANDIDATES = ROOT / "data/annotations/ble-v2"          # *-candidates.json의 main_motion_start_ms(속도 증강 조건)
EXP = "return-label-01"
OUT = DOC / EXP
RUNS = ROOT / "ml/runs" / EXP
SCORINGS = ("old_window", "new_window", "extreme_window")
EXTREME_AFTER_R_MS = 300   # extreme_window의 끝 = r + 300 ms(2026-10-29 r+200에서 늘림. 실기기 체감 확인 전 잠정값)
# 쓰는 분할(사용자 결정). 2026-10-27 오전 C·S-P2·S-P5, 같은 날 newtcnnorm부터 C·S-P5.
# 이전 결과는 6개 분할(v2.SPLIT_NAMES)이나 세 분할로 남아 있다.
SPLITS = ("C", "S-P5")
ANGLE_SCALE_DEG = 45.0
SAMPLE_S = 0.01
SAMPLE_MS = 10.0

# label: 방향 라벨의 기준 시각("settled" = 기존 e, "return" = r), angle: 회전각 채널 추가 여부, model: "cnn" | "tcn",
# hard: 학습 NONE에 반드시 넣을 구간(None = v2.choose_training 그대로, "outbound" = 가는 피크 ~ 끝점),
# angle_norm: 회전각 채널을 fold 학습 창의 평균·표준편차로 정규화할지,
# angle_bias: 회전각 영점("clip" = 클립 전체 중앙값(비인과), "precue" = 클립 0~900 ms 중앙값(인과)),
# aug: 학습 원본 증강 설정(None = 증강 없음). 계획: docs/superpowers/plans/2026-10-27-v2-augmentation.md
_BASE = {"label": "return", "angle": False, "model": "cnn", "hard": None, "angle_norm": False, "angle_bias": "clip",
         "aug": None}
CONDITIONS = {
    "old": {**_BASE, "label": "settled"},
    "new": {**_BASE},
    "newangle": {**_BASE, "angle": True},
    "newtcn": {**_BASE, "angle": True, "model": "tcn"},
    "newtcnhard": {**_BASE, "angle": True, "model": "tcn", "hard": "outbound"},
    "newtcnnorm": {**_BASE, "angle": True, "model": "tcn", "angle_norm": True},
    "newtcnrt": {**_BASE, "angle": True, "model": "tcn", "angle_norm": True, "angle_bias": "precue"},
    "newtcnrot": {**_BASE, "angle": True, "model": "tcn", "angle_norm": True, "angle_bias": "precue",
                  "aug": {"kind": "rotate", "rot_y_deg": 30, "tilt_deg": 15, "copies": 2}},
    "newtcnrotwarp": {**_BASE, "angle": True, "model": "tcn", "angle_norm": True, "angle_bias": "precue",
                      "aug": {"kind": "rotate_warp", "rot_y_deg": 30, "tilt_deg": 15, "copies": 2,
                              "anchor_ms": 890, "scale_min": 0.8, "scale_max": 1.25, "max_jump_dps": 2.0}},
}
PRECUE_SAMPLES = 90       # 0~890 ms, 동작 신호(1000 ms) 전. 속도 변형은 이 행들을 건드리지 않는다(900 ms부터)
AUG_SEED = 20261027       # 증강 난수(학습 seed와 별개, 클립 경로·사본 번호와 함께 쓴다)
ANGLE = slice(6, 9)
LABELS = tuple(CONDITIONS)


# ---------------------------------------------------------------- 데이터

def load():
    """기존 records와 새 라벨을 읽고, 새 라벨이 같은 records·원본에서 만들어졌는지 확인한다."""
    data, by_path = v2.load_records()
    new = json.loads(NEW_RECORDS.read_text(encoding="utf-8"))
    if new["based_on_sha256"] != digest(v2.RECORDS):
        raise ValueError("새 라벨이 현재 records.json에서 만든 것이 아니다")
    nb = {r["source_path"]: r for r in new["records"]}
    for path, r in nb.items():
        if digest(ROOT / path) != r["sha256"]:
            raise ValueError(f"원본이 바뀌었다: {path}")
    gestures = {p for p, r in by_path.items() if r["completion_ms"] is not None}
    if gestures != set(nb):
        raise ValueError("새 라벨과 방향 원본 목록이 다르다")
    return data, by_path, nb


def relabel(by_path, nb, label):
    """조건의 라벨 기준이 r이면 방향 원본의 completion_ms를 r로 바꾼 사본을 돌려준다. v2.windows가 이 값으로 라벨을 붙인다."""
    if CONDITIONS[label]["label"] == "settled":
        return by_path
    out = {}
    for p, r in by_path.items():
        r = dict(r)
        if r["completion_ms"] is not None:
            r["completion_ms"] = nb[p]["event_ms"]
        out[p] = r
    return out


def windows_with_angle(record, ts, raw, mean, std, bias_mode="clip"):
    """v2.windows_from_raw에 회전각 3채널을 붙인다. 정규화된 자이로를 원시 deg/s로 되돌리고, 영점을 빼서 창 안에서 누적한다.
    원시 자이로에 약 10 dps 치우침이 있어 보정 없이는 1.6초에 약 16도가 쌓인다.
    bias_mode "clip"은 클립 전체 중앙값(비인과), "precue"는 클립 0~900 ms 중앙값(첫 판정 전 데이터만, 인과).
    영점은 넘겨받은 raw에서 잡는다. 증강 사본이면 사본의 raw다(창과 영점이 같은 신호에서 나와야 한다)."""
    x, y, meta = v2.windows_from_raw(record, ts, raw, mean, std)
    gyro_raw = raw[:PRECUE_SAMPLES, 3:6] if bias_mode == "precue" else raw[:, 3:6]
    bias = np.median(gyro_raw, axis=0)
    gyro = x[:, :, 3:6].astype(np.float64) * std[3:6] + mean[3:6] - bias
    angle = np.cumsum(gyro * SAMPLE_S, axis=1)
    angle -= angle[:, :1, :]
    return np.concatenate([x, (angle / ANGLE_SCALE_DEG).astype(np.float32)], axis=2), y, meta


def outbound_none_chooser(nb):
    """v2.choose_training의 선택에서 in_progress NONE 절반을 "가는 피크 ~ 끝점"에 끝나는 창으로 바꾼다.

    in_progress 개수, 다른 NONE 종류의 선택, 양성 창은 그대로다. 끝점 근처 창이 모자라면 원래 선택으로 채운다.
    """
    def choose(y, meta, seed=v2.SEED):
        idx = v2.choose_training(y, meta, seed)
        in_progress = lambda i: y[i] == 0 and meta[i]["none_group"] == "in_progress"

        def outbound(i):
            n = nb.get(meta[i]["source_path"])
            return n is not None and n["extreme_ms"] is not None and in_progress(i)                 and n["outbound_peak_ms"] <= meta[i]["timestamp_ms"] <= n["extreme_ms"]

        chosen = [int(i) for i in idx if in_progress(i)]
        pools = {}
        for i in range(len(y)):
            if outbound(i):
                pools.setdefault(meta[i]["source_path"], []).append(i)
        rng = np.random.default_rng(seed + 1)
        for src in sorted(pools):
            rng.shuffle(pools[src])
        hard = []
        while len(hard) < len(chosen) // 2 and any(pools.values()):
            for src in sorted(pools):
                if pools[src] and len(hard) < len(chosen) // 2:
                    hard.append(pools[src].pop())
        picked = hard + [i for i in chosen if not outbound(i)][:len(chosen) - len(hard)]
        picked += [i for i in chosen if i not in set(picked)][:len(chosen) - len(picked)]
        assert len(set(picked)) == len(chosen)
        return np.array(sorted([int(i) for i in idx if not in_progress(i)] + picked), dtype=np.int64)
    return choose


def normalize_angle(d):
    """회전각 채널을 fold 학습 창(선택된 학습 창)의 축별 평균·표준편차로 정규화한다. 검증 창은 통계에 쓰지 않는다."""
    a = d["x_train"][:, :, ANGLE].astype(np.float64)
    mean, std = a.mean(axis=(0, 1)), np.maximum(a.std(axis=(0, 1)), 1e-6)
    d["angle_mean"], d["angle_std"] = mean, std
    d["x_train"][:, :, ANGLE] = ((a - mean) / std).astype(np.float32)
    for chunk in d["val"]:
        x = chunk[1]
        x[:, :, ANGLE] = ((x[:, :, ANGLE].astype(np.float64) - mean) / std).astype(np.float32)


def tcn(channels):
    from model import build_tcn
    return build_tcn(v2.WINDOW, channels=channels)


def rotation_matrix(axis, deg):
    """단위 축 axis 둘레로 deg도 돌리는 행렬(로드리게스 공식)."""
    a = np.asarray(axis, dtype=np.float64)
    a = a / np.linalg.norm(a)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    t = np.radians(deg)
    return np.eye(3) + np.sin(t) * k + (1 - np.cos(t)) * (k @ k)


def random_rotation(rng, rot_y_deg, tilt_deg):
    """R = R_tilt · R_y(θ). θ ~ U(−rot_y, +rot_y). R_tilt는 X-Z 평면의 임의 축(방향각 ~ U(0°, 360°)) 둘레로 φ ~ U(−tilt, +tilt)."""
    theta = rng.uniform(-rot_y_deg, rot_y_deg)
    psi = np.radians(rng.uniform(0, 360))
    phi = rng.uniform(-tilt_deg, tilt_deg)
    return rotation_matrix((np.cos(psi), 0.0, np.sin(psi)), phi) @ rotation_matrix((0.0, 1.0, 0.0), theta)


def rotate_raw(raw, rot, bias):
    """센서 좌표계를 rot만큼 돌린 원시 사본. 가속도는 중력까지 함께 돌린다.
    자이로 영점은 센서 고유 성질이라 돌리지 않는다: gyro' = R(gyro − b) + b."""
    out = raw.copy()
    out[:, 0:3] = raw[:, 0:3] @ rot.T
    out[:, 3:6] = (raw[:, 3:6] - bias) @ rot.T + bias
    return out


def clip_rng(source_path, copy):
    """클립·사본마다 고정된 난수. fold·처리 순서와 무관하게 같은 클립·사본은 같은 변형을 받는다."""
    h = int.from_bytes(hashlib.sha256(source_path.encode("utf-8")).digest()[:8], "little")
    return np.random.default_rng([AUG_SEED, h, copy])


def rotate_augmenter(aug):
    """학습 원본마다 회전 사본 aug["copies"]개. 방향·배경 모두 돌린다(회전 = 동작 클립이라는 지름길을 막는다)."""
    def augment(record, ts, raw):
        bias = np.median(raw[:PRECUE_SAMPLES, 3:6], axis=0)
        copies = []
        for c in range(1, aug["copies"] + 1):
            rot = random_rotation(clip_rng(record["source_path"], c), aug["rot_y_deg"], aug["tilt_deg"])
            copies.append(({**record, "source_path": f"{record['source_path']}#rot{c}"}, rotate_raw(raw, rot, bias), len(raw)))
        return copies
    return augment


def warp_raw(raw, s, bias, anchor_ms):
    """anchor_ms 고정점 속도 변형. 0~890 ms(PRECUE_SAMPLES행)는 그대로, 900 ms부터 원본 시각 anchor + (t − anchor)/s의 값을
    축별 선형 보간한다. 자이로는 영점을 빼고 1/s배(같은 각도를 다른 속도로 돈다), 가속도는 보간만 한다.
    (사본, 유효 행 수, 경계 점프 dps)를 돌려준다. 원본 범위(마지막 행 시각) 밖 행은 마지막 유효 행으로 채운다(그 창은 학습에서 빠진다).
    경계 점프는 첫 변형 행에서 배율이 갑자기 바뀌어 생기는 차이: max_axis |보간값 − b|·|1/s − 1|."""
    t = np.arange(len(raw)) * SAMPLE_MS
    src = anchor_ms + (t[PRECUE_SAMPLES:] - anchor_ms) / s
    src = src[src <= t[-1]]
    seg = np.stack([np.interp(src, t, raw[:, j]) for j in range(raw.shape[1])], axis=1)
    jump = float(np.max(np.abs(seg[0, 3:6] - bias)) * abs(1 / s - 1))
    seg[:, 3:6] = (seg[:, 3:6] - bias) / s + bias
    out = raw.copy()
    n = PRECUE_SAMPLES + len(seg)
    out[PRECUE_SAMPLES:n] = seg
    out[n:] = out[n - 1]
    return out, n, jump


def positive_windows(e, rows, valid_rows):
    """라벨 시각 e의 양성 창(e ≤ t < e+150 ms) 중 마지막 샘플이 유효 행 안에 있는 판정 창 수."""
    t = v2.decision_times(rows)
    t = t[t <= (valid_rows - 1) * SAMPLE_MS]
    return int(np.sum((t >= e) & (t < e + v2.POSITIVE_MS)))


def motion_starts():
    """방향 원본의 주동작 시작 시각(ms, 활동 신호 누적 에너지 1% 시점)."""
    return {a["source_path"]: a["main_motion_start_ms"] for f in sorted(CANDIDATES.glob("*-candidates.json"))
            for a in json.loads(f.read_text(encoding="utf-8"))["annotations"]}


def rotate_warp_augmenter(aug, starts=None):
    """newtcnrot과 같은 회전 사본(같은 난수 순서·같은 사본 이름)에 속도 변형을 더한다. s는 R 다음에 같은 난수에서 뽑는다.
    속도 조건을 못 넘는 사본은 회전만 적용한 newtcnrot 사본 그대로 둔다. augment.stats에 사본별 처리 결과를 센다."""
    starts = motion_starts() if starts is None else starts
    lo, hi = np.log(aug["scale_min"]), np.log(aug["scale_max"])
    anchor = aug["anchor_ms"]
    stats = Counter()

    def augment(record, ts, raw):
        path = record["source_path"]
        bias = np.median(raw[:PRECUE_SAMPLES, 3:6], axis=0)
        copies = []
        for c in range(1, aug["copies"] + 1):
            rng = clip_rng(path, c)
            rot = rotate_raw(raw, random_rotation(rng, aug["rot_y_deg"], aug["tilt_deg"]), bias)
            s = float(np.exp(rng.uniform(lo, hi)))
            copy, why = ({**record, "source_path": f"{path}#rot{c}"}, rot, len(raw)), None
            e = record["completion_ms"]
            if e is None:
                why = "background"
            elif starts[path] < PRECUE_SAMPLES * SAMPLE_MS:
                why = "early_start"
            else:
                r2 = anchor + s * (e - anchor)
                warped, n, jump = warp_raw(rot, s, bias, anchor)
                if positive_windows(r2, len(raw), n) != positive_windows(e, len(raw), len(raw)):
                    why = "positive_loss"       # 양성 창이 첫 판정 앞으로 당겨지거나 원본 범위 밖으로 밀림
                elif jump > aug["max_jump_dps"]:
                    why = "jump"
                else:
                    copy = ({**record, "source_path": f"{path}#rot{c}", "completion_ms": r2}, warped, n)
            stats[why or "warp"] += 1
            copies.append(copy)
        return copies
    augment.stats = stats
    return augment


def augmenter(aug):
    """조건의 aug 설정으로 v2.fold_sets(augment_fn=...)에 넘길 함수를 만든다. None이면 증강하지 않는다."""
    if aug is None:
        return None
    if aug["kind"] == "rotate":
        return rotate_augmenter(aug)
    if aug["kind"] == "rotate_warp":
        return rotate_warp_augmenter(aug)
    raise ValueError(f"알 수 없는 증강 설정: {aug}")


def prepare_fold(label, by_path, nb, split, k):
    """조건 label의 fold k 학습·검증 집합과 학습 함수를 돌려준다."""
    cond = CONDITIONS[label]
    window_fn = (lambda r, ts, raw, m, s: windows_with_angle(r, ts, raw, m, s, cond["angle_bias"])) if cond["angle"] else None
    none_fn = outbound_none_chooser(nb) if cond["hard"] == "outbound" else None
    augment_fn = augmenter(cond["aug"])
    d = v2.fold_sets(relabel(by_path, nb, label), split, k, window_fn=window_fn, none_fn=none_fn, augment_fn=augment_fn)
    d["train_aug_stats"] = dict(getattr(augment_fn, "stats", {}))
    if cond["angle_norm"]:
        normalize_angle(d)
    if cond["model"] == "tcn":
        return d, lambda *args: v2.fit_snapshots(*args, model_fn=tcn)
    return d, v2.fit_snapshots


# ---------------------------------------------------------------- 채점

def success_window(path, by_path, nb, scoring):
    """(성공 구간 시작, 끝, 지연 기준). 배경 원본이면 None."""
    old_e = by_path[path]["completion_ms"]
    if old_e is None:
        return None
    if scoring == "old_window":
        return old_e, old_e + v2.MATCH_MS, old_e
    n = nb[path]
    if scoring == "extreme_window":
        return n["extreme_ms"], n["event_ms"] + EXTREME_AFTER_R_MS, n["event_ms"]
    return n["score_start_ms"], n["score_end_ms"], n["event_ms"]


def classify(record, events, window):
    """v2.classify_events와 같은 분류를 구간 [start, end]로 한다."""
    matched = False
    counts = Counter({k: 0 for k in ("correct", "missed", "wrong_direction", "duplicate", "early", "late_unmatched", "background_false")})
    delays, kinds = [], []
    for event in events:
        t = event["timestamp_ms"]
        if window is None:
            kind = "background_false"
        elif t < window[0]:
            kind = "early"
        elif t > window[1]:
            kind = "late_unmatched"
        elif event["class_index"] != CLASSES.index(record["direction"]):
            kind = "wrong_direction"
        elif matched:
            kind = "duplicate"
        else:
            kind, matched = "correct", True
            delays.append(t - window[2])
        counts[kind] += 1
        kinds.append([t, event["class_index"], kind])
    if window is not None and not matched:
        counts["missed"] = 1
    return dict(counts), delays, kinds


def score(val_chunks, scores, by_path, nb, scoring):
    totals, offset, per_source = Counter(), 0, []
    for record, _, labels, meta in val_chunks:
        n = len(labels)
        events = v2.issue_events([m["timestamp_ms"] for m in meta], scores[offset:offset + n])
        counts, delays, kinds = classify(record, events, success_window(record["source_path"], by_path, nb, scoring))
        totals.update(counts)
        per_source.append({"source_path": record["source_path"], "counts": counts, "delays_ms": delays, "events": kinds})
        offset += n
    assert offset == len(scores)
    return dict(totals), per_source


# ---------------------------------------------------------------- 실행

def run_dir(tag=None):
    """실행 결과 폴더. tag가 있으면 RUNS/<tag>로 나눠 다른 PC·재실행 결과와 섞이지 않게 한다(없으면 이전 실험 경로)."""
    if tag is None:
        return RUNS
    if not re.fullmatch(r"[A-Za-z0-9._-]+", tag):
        raise ValueError(f"tag는 영문·숫자·._-만 쓴다: {tag!r}")
    return RUNS / tag


def log_dir(tag=None):
    return OUT / "logs" if tag is None else OUT / "logs" / tag


def result_path(label, split, seed, tag=None):
    """원본 결과(수 MB씩)는 깃 제외 폴더에 둔다. 저장소에는 OUT/results/(tag가 있으면 OUT/results/<tag>/)에 gzip 사본을 올린다."""
    return run_dir(tag) / "results" / f"{label}-{split}" / f"seed-{seed}.json"


def runtime_env():
    """실행 환경. CPU·라이브러리가 다르면 같은 코드·seed라도 E5 이후 결과가 달라진다(README 재현성 절)."""
    import tensorflow as tf
    return {"python": platform.python_version(), "numpy": np.__version__, "tensorflow": tf.__version__,
            "os": platform.platform(), "cpu": platform.processor(), "logical_cpus": os.cpu_count(), "venv": sys.prefix,
            **{k: os.environ.get(k) for k in ("TF_ENABLE_ONEDNN_OPTS", "TF_DETERMINISTIC_OPS")}}


def cmd_run(label, split_name, seed, tag=None):
    target = result_path(label, split_name, seed, tag)
    if target.exists():
        raise FileExistsError(f"{target}가 이미 있다. 덮어쓰지 않는다")
    _, by_path, nb = load()
    split = v2.load_split(split_name)
    score_dir = run_dir(tag) / f"{label}-{split_name}"
    score_dir.mkdir(parents=True, exist_ok=True)
    epochs = tuple(v2.EPOCH_CANDIDATES)
    result = {"experiment": EXP, "label": label, "condition": CONDITIONS[label], "split": split_name, "seed": seed,
              "tag": tag, "created_kst": now(),
              "code_sha256": {f: digest(ROOT / "ml" / f) for f in ("v2.py", "v2_return.py", "model.py")},
              "records_sha256": digest(v2.RECORDS), "new_records_sha256": digest(NEW_RECORDS),
              "epochs": list(epochs), "folds": []}
    t_start = time.time()
    for k in range(split["cv"]["n_folds"]):
        t0 = time.time()
        d, fit = prepare_fold(label, by_path, nb, split, k)
        x_val = np.concatenate([c[1] for c in d["val"]])
        scores, _ = fit(d["x_train"], d["y_train"], x_val, seed, epochs)
        result["model_params"] = tcn(d["x_train"].shape[2]).count_params() if CONDITIONS[label]["model"] == "tcn"             else v2.model_params(d["x_train"].shape[2])
        np.savez_compressed(score_dir / f"seed-{seed}-fold-{k}-scores.npz", **{f"e{e}": scores[e].astype(np.float32) for e in epochs})
        per_epoch = {str(e): {s: dict(zip(("totals", "per_source"), score(d["val"], scores[e], by_path, nb, s))) for s in SCORINGS}
                     for e in epochs}
        result["folds"].append({"fold": k, "held_out_session": split["cv"]["folds"][k].get("held_out_session"),
                                "train_windows_selected": d["train_counts"],
                                "updates_per_epoch": -(-len(d["y_train"]) // v2.BATCH_SIZE),
                                "train_aug_copies": d["train_aug_copies"], "train_aug_skipped": d["train_aug_skipped"],
                                "train_windows_excluded": d["train_windows_excluded"],
                                "train_aug_stats": d["train_aug_stats"], "train_none_groups": d["train_none_groups"],
                                "per_epoch": per_epoch, "seconds": round(time.time() - t0, 1)})
        print(f"{label} {split_name} seed {seed} fold {k}: {round(time.time() - t0, 1)}s", flush=True)
    result["seconds"] = round(time.time() - t_start, 1)
    result["tf_threads_fixed"] = v2.tf_threads_fixed
    result["env"] = runtime_env()
    dump(target, result)
    print("saved", target)


def cmd_run_all(parallel, labels=LABELS, tag=None, splits=SPLITS):
    """labels 중 결과가 없는 (label, split, seed)를 돌린다. ml/runs/는 깃 제외라 새 PC에서는 비어 있으니 labels를 지정한다.
    로그는 저장소에 있으므로 덮어쓰지 않는다: 하나라도 이미 있으면 아무것도 시작하지 않는다. 재실행은 새 tag로 한다."""
    jobs = [(lab, sp, s) for lab in labels for sp in splits for s in v2.SEEDS if not result_path(lab, sp, s, tag).exists()]
    logs = log_dir(tag)
    existing = [f"{lab}-{sp}-seed-{s}.log" for lab, sp, s in jobs if (logs / f"{lab}-{sp}-seed-{s}.log").exists()]
    if existing:
        raise FileExistsError(f"{logs}에 로그가 이미 있다(덮어쓰지 않는다. 새 --tag를 쓴다): {existing[:3]} 외 {max(0, len(existing) - 3)}개")
    print("pending:", len(jobs), flush=True)
    logs.mkdir(parents=True, exist_ok=True)
    running, failed = [], []
    for lab, sp, s in jobs:
        log = open(logs / f"{lab}-{sp}-seed-{s}.log", "x", encoding="utf-8")
        cmd = [sys.executable, str(ROOT / "ml/v2_return.py"), "run", "--label", lab, "--split", sp, "--seed", str(s)]
        proc = subprocess.Popen(cmd + (["--tag", tag] if tag else []), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        running.append(((lab, sp, s), proc, log))
        while sum(p.poll() is None for _, p, _ in running) >= parallel:
            time.sleep(2)
    for job, proc, log in running:
        if proc.wait():
            failed.append(job)
        log.close()
    print("failed:", failed or "none")
    if failed:
        sys.exit(1)


# ---------------------------------------------------------------- 요약

def is_gesture(source_path):
    return source_path.rsplit("/", 1)[-1].startswith("raw_")


def load_weak():
    """약한 동작 클립 경로. 원본이 목록을 만들 때와 같은지 확인한다."""
    data = json.loads(WEAK_GESTURES.read_text(encoding="utf-8"))
    for e in data["entries"]:
        if digest(ROOT / e["source_path"]) != e["sha256"]:
            raise ValueError(f"약한 동작 원본이 바뀌었다: {e['source_path']}")
    return frozenset(e["source_path"] for e in data["entries"])


def rescored(res, scoring, by_path, nb, source="new_window"):
    """결과에 scoring 채점이 없으면 source 채점의 발행 기록(시각, 방향)을 scoring 구간으로 다시 분류해 채운다.
    발행 규칙은 채점 구간과 무관하므로, 같은 발행을 다시 분류한 것은 학습 직후 그 구간으로 채점한 것과 같다."""
    for fold in res["folds"]:
        for ep in fold["per_epoch"].values():
            if scoring in ep:
                continue
            totals, per_source = Counter(), []
            for p in ep[source]["per_source"]:
                if p["source_path"] not in by_path:      # 지금 데이터에서 빠진 원본(예: 라벨 감사 제외)은 다시 채점하지 않는다
                    continue
                events = [{"timestamp_ms": t, "class_index": c} for t, c, _ in p["events"]]
                counts, delays, kinds = classify(by_path[p["source_path"]], events,
                                                 success_window(p["source_path"], by_path, nb, scoring))
                totals.update(counts)
                per_source.append({"source_path": p["source_path"], "counts": counts, "delays_ms": delays, "events": kinds})
            ep[scoring] = {"totals": dict(totals), "per_source": per_source}
    return res


def epoch_stats(seed_results, epoch, scoring, skip=frozenset(), only=None):
    """seed별로 fold를 합친 뒤 seed 평균을 낸다. skip의 방향 클립은 세지 않고, only를 주면 그 방향 클립만 센다."""
    per_seed = []
    for res in seed_results:
        sources = [p for f in res["folds"] for p in f["per_epoch"][str(epoch)][scoring]["per_source"]]
        gest = [p for p in sources if is_gesture(p["source_path"]) and p["source_path"] not in skip
                and (only is None or p["source_path"] in only)]
        bg = [p for p in sources if not is_gesture(p["source_path"])]
        c = Counter()
        for p in gest:
            c.update(p["counts"])
        unmatched = sum(c[k] for k in v2.UNMATCHED_ON_GESTURE)
        # 정답 발행이 있고, 클립 안에 다른 방향 발행이 하나도 없는 경우(실제 사용에서 잘못된 명령이 안 나간 성공)
        clean = sum(1 for p in gest if p["counts"].get("correct")
                    and len({ev[1] for ev in p["events"]}) == 1)
        delays = [d for p in gest for d in p["delays_ms"]]
        per_seed.append({"n": len(gest), "correct": c["correct"], "unmatched": unmatched,
                         "selection_score": (c["correct"] - unmatched) / len(gest),
                         "success_rate": c["correct"] / len(gest),
                         "clean_success_rate": clean / len(gest),
                         "early_clip_rate": sum(1 for p in gest if any(ev[2] == "early" for ev in p["events"])) / len(gest),
                         "no_issue_rate": sum(1 for p in gest if not p["events"]) / len(gest),
                         "wrong_direction": c["wrong_direction"], "duplicate": c["duplicate"], "late": c["late_unmatched"],
                         "background_false": sum(p["counts"].get("background_false", 0) for p in bg), "background_clips": len(bg),
                         "delay_median_ms": float(np.median(delays)) if delays else None})
    keys = ("success_rate", "clean_success_rate", "selection_score", "early_clip_rate", "no_issue_rate")
    out = {k: float(np.mean([s[k] for s in per_seed])) for k in keys}
    out["success_rate_range"] = [min(s["success_rate"] for s in per_seed), max(s["success_rate"] for s in per_seed)]
    out["background_false_per_clip"] = float(np.mean([s["background_false"] / s["background_clips"] for s in per_seed]))
    d = [s["delay_median_ms"] for s in per_seed if s["delay_median_ms"] is not None]
    out["delay_median_ms"] = float(np.mean(d)) if d else None
    out["per_seed"] = per_seed
    return out


def cmd_summarize(name="summary.json", tag=None, exclude_weak=False, splits=SPLITS):
    target = OUT / name
    if target.exists():
        raise FileExistsError(f"{target}가 이미 있다")
    labels = [lab for lab in LABELS if all(result_path(lab, sp, s, tag).exists() for sp in splits for s in v2.SEEDS)]
    weak = load_weak()
    skip = weak if exclude_weak else frozenset()
    _, by_path, nb = load()
    summary = {"experiment": EXP, "created_kst": now(), "rule": "E는 seed 평균 selection_score 최대, 같으면 작은 E",
               "tag": tag, "labels": labels, "splits": list(splits),
               "weak_gestures": {"file": WEAK_GESTURES.relative_to(ROOT).as_posix(), "sha256": digest(WEAK_GESTURES),
                                 "clips": len(weak), "excluded_from_main": exclude_weak},
               "panels": {}}
    for lab in labels:
        for sp in summary.get("splits", SPLITS):
            res = [rescored(json.loads(result_path(lab, sp, s, tag).read_text(encoding="utf-8")), "extreme_window", by_path, nb)
                   for s in v2.SEEDS]
            panel = {}
            for sc in SCORINGS:
                by_e = {str(e): epoch_stats(res, e, sc, skip) for e in v2.EPOCH_CANDIDATES}
                for e in v2.EPOCH_CANDIDATES:
                    w = epoch_stats(res, e, sc, only=weak)
                    by_e[str(e)]["weak"] = {k: w[k] for k in ("clean_success_rate", "no_issue_rate", "success_rate")}
                    by_e[str(e)]["weak"]["clip_evaluations_per_seed"] = w["per_seed"][0]["n"]
                best = max(v2.EPOCH_CANDIDATES, key=lambda e: (round(by_e[str(e)]["selection_score"], 12), -e))
                panel[sc] = {"selected_E": best, "by_epoch": by_e}
            summary["panels"][f"{lab}-{sp}"] = panel
    dump(target, summary)
    print_table(summary)


def print_table(summary):
    for sc in SCORINGS:
        print(f"\n== {sc}: 선택 E / 정검출률(seed 평균) / 조기 발행 클립 / 무발행 / 배경 오발행(클립당)")
        for sp in summary.get("splits", SPLITS):
            row = [sp]
            for lab in summary["labels"]:
                p = summary["panels"][f"{lab}-{sp}"][sc]
                s = p["by_epoch"][str(p["selected_E"])]
                row.append(f"{lab}: E{p['selected_E']:<2} {s['success_rate']*100:5.1f}% early {s['early_clip_rate']*100:4.1f}% "
                           f"none {s['no_issue_rate']*100:4.1f}% bg {s['background_false_per_clip']:.2f}")
            print("  " + " | ".join(row))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--label", choices=LABELS, required=True)
    r.add_argument("--split", choices=SPLITS, required=True)
    r.add_argument("--seed", type=int, required=True)
    r.add_argument("--tag")
    a = sub.add_parser("run-all")
    a.add_argument("--parallel", type=int, default=8)
    a.add_argument("--labels", nargs="+", choices=LABELS, default=list(LABELS))
    a.add_argument("--splits", nargs="+", choices=SPLITS, default=list(SPLITS))
    a.add_argument("--tag")
    m = sub.add_parser("summarize")
    m.add_argument("--out", default="summary.json")
    m.add_argument("--tag")
    m.add_argument("--exclude-weak", action="store_true")
    m.add_argument("--splits", nargs="+", choices=SPLITS, default=list(SPLITS))
    args = p.parse_args()
    if args.cmd == "run":
        cmd_run(args.label, args.split, args.seed, args.tag)
    elif args.cmd == "run-all":
        cmd_run_all(args.parallel, args.labels, args.tag, args.splits)
    else:
        cmd_summarize(args.out, args.tag, args.exclude_weak, args.splits)


if __name__ == "__main__":
    main()
