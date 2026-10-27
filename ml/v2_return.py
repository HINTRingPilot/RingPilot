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
각 학습 결과를 두 채점으로 모두 매긴다. 발행 규칙(v2.issue_events)과 E 선택 규칙은 그대로다.
  old_window  [e, e+500 ms]
  new_window  [복귀 피크, r+500 ms]
새 e는 tools/derive-return-labels.js가 만든 data/annotations/ble-v2-return/records.json에서 읽는다.

사용 (ml/.venv/Scripts/python.exe ml/v2_return.py <명령>):
  run --label old|new|newangle|newtcn|newtcnhard|newtcnnorm|newtcnrt --split C|S-P5 --seed N [--tag T]   한 seed의 모든 fold 학습·채점
  run-all [--parallel 8] [--labels L ...] [--tag T]           빠진 (label, split, seed)를 실행(기본은 모든 조건)
  summarize [--out summary.json] [--tag T]                    요약 작성(이미 있으면 거부)
--tag를 주면 결과는 ml/runs/return-label-01/<T>/, 로그는 OUT/logs/<T>/에 둔다(다른 PC·재실행 결과를 기존 것과 나눔).
로그는 덮어쓰지 않는다(이미 있으면 run-all이 시작하지 않는다).
"""

import argparse
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
EXP = "return-label-01"
OUT = DOC / EXP
RUNS = ROOT / "ml/runs" / EXP
SCORINGS = ("old_window", "new_window")
# 쓰는 분할(사용자 결정). 2026-10-27 오전 C·S-P2·S-P5, 같은 날 newtcnnorm부터 C·S-P5.
# 이전 결과는 6개 분할(v2.SPLIT_NAMES)이나 세 분할로 남아 있다.
SPLITS = ("C", "S-P5")
ANGLE_SCALE_DEG = 45.0
SAMPLE_S = 0.01

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
}
PRECUE_SAMPLES = 90       # 0~890 ms, 동작 신호(1000 ms) 전
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


def augmenter(aug):
    """조건의 aug 설정으로 v2.fold_sets(augment_fn=...)에 넘길 함수를 만든다. None이면 증강하지 않는다."""
    if aug is None:
        return None
    raise ValueError(f"알 수 없는 증강 설정: {aug}")


def prepare_fold(label, by_path, nb, split, k):
    """조건 label의 fold k 학습·검증 집합과 학습 함수를 돌려준다."""
    cond = CONDITIONS[label]
    window_fn = (lambda r, ts, raw, m, s: windows_with_angle(r, ts, raw, m, s, cond["angle_bias"])) if cond["angle"] else None
    none_fn = outbound_none_chooser(nb) if cond["hard"] == "outbound" else None
    d = v2.fold_sets(relabel(by_path, nb, label), split, k, window_fn=window_fn, none_fn=none_fn,
                     augment_fn=augmenter(cond["aug"]))
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
                                "per_epoch": per_epoch, "seconds": round(time.time() - t0, 1)})
        print(f"{label} {split_name} seed {seed} fold {k}: {round(time.time() - t0, 1)}s", flush=True)
    result["seconds"] = round(time.time() - t_start, 1)
    result["tf_threads_fixed"] = v2.tf_threads_fixed
    result["env"] = runtime_env()
    dump(target, result)
    print("saved", target)


def cmd_run_all(parallel, labels=LABELS, tag=None):
    """labels 중 결과가 없는 (label, split, seed)를 돌린다. ml/runs/는 깃 제외라 새 PC에서는 비어 있으니 labels를 지정한다.
    로그는 저장소에 있으므로 덮어쓰지 않는다: 하나라도 이미 있으면 아무것도 시작하지 않는다. 재실행은 새 tag로 한다."""
    jobs = [(lab, sp, s) for lab in labels for sp in SPLITS for s in v2.SEEDS if not result_path(lab, sp, s, tag).exists()]
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


def epoch_stats(seed_results, epoch, scoring):
    """seed별로 fold를 합친 뒤 seed 평균을 낸다."""
    per_seed = []
    for res in seed_results:
        sources = [p for f in res["folds"] for p in f["per_epoch"][str(epoch)][scoring]["per_source"]]
        gest = [p for p in sources if is_gesture(p["source_path"])]
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


def cmd_summarize(name="summary.json", tag=None):
    target = OUT / name
    if target.exists():
        raise FileExistsError(f"{target}가 이미 있다")
    labels = [lab for lab in LABELS if all(result_path(lab, sp, s, tag).exists() for sp in SPLITS for s in v2.SEEDS)]
    summary = {"experiment": EXP, "created_kst": now(), "rule": "E는 seed 평균 selection_score 최대, 같으면 작은 E",
               "tag": tag, "labels": labels, "panels": {}}
    for lab in labels:
        for sp in SPLITS:
            res = [json.loads(result_path(lab, sp, s, tag).read_text(encoding="utf-8")) for s in v2.SEEDS]
            panel = {}
            for sc in SCORINGS:
                by_e = {str(e): epoch_stats(res, e, sc) for e in v2.EPOCH_CANDIDATES}
                best = max(v2.EPOCH_CANDIDATES, key=lambda e: (round(by_e[str(e)]["selection_score"], 12), -e))
                panel[sc] = {"selected_E": best, "by_epoch": by_e}
            summary["panels"][f"{lab}-{sp}"] = panel
    dump(target, summary)
    print_table(summary)


def print_table(summary):
    for sc in SCORINGS:
        print(f"\n== {sc}: 선택 E / 정검출률(seed 평균) / 조기 발행 클립 / 무발행 / 배경 오발행(클립당)")
        for sp in SPLITS:
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
    a.add_argument("--tag")
    m = sub.add_parser("summarize")
    m.add_argument("--out", default="summary.json")
    m.add_argument("--tag")
    args = p.parse_args()
    if args.cmd == "run":
        cmd_run(args.label, args.split, args.seed, args.tag)
    elif args.cmd == "run-all":
        cmd_run_all(args.parallel, args.labels, args.tag)
    else:
        cmd_summarize(args.out, args.tag)


if __name__ == "__main__":
    main()
