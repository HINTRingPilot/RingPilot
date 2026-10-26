"""BLE v2 라벨 시각 비교: 기존 e(완전히 멈춘 시점) vs 새 e(복귀 피크 뒤 주축이 절반으로 내려온 시점 r).

v2_cal.py와 같은 분할·fold·seed·NONE 추출·모델·학습(60 epoch, 1·5·10·20·30·40·60 epoch 예측 저장)을 쓰고,
두 가지만 바꾼다.
  label   old: 방향 라벨 e ≤ t < e+150 ms   new: r ≤ t < r+150 ms (제외 구간 없음, 나머지 NONE)
  scoring old_window: [e, e+500 ms]          new_window: [복귀 피크, r+500 ms]
각 학습 결과를 두 채점으로 모두 매긴다. 발행 규칙(v2.issue_events)과 E 선택 규칙은 그대로다.
  newangle: new 라벨 + 입력에 회전각 3채널 추가(창 시작 대비 누적 자이로, 원시 deg/s × 0.01 s, 45도로 나눔).
            모델은 같은 구조에 입력 채널만 9개(첫 Conv 파라미터 증가, 총 9,733개). model.py·v2.py는 바꾸지 않는다.
새 e는 tools/derive-return-labels.js가 만든 data/annotations/ble-v2-return/records.json에서 읽는다.

사용 (ml/.venv/Scripts/python.exe ml/v2_return.py <명령>):
  run --label old|new|newangle --split C|S-P1..S-P5 --seed N   한 seed의 모든 fold 학습·채점
  run-all [--parallel 8]                              빠진 (label, split, seed)를 모두 실행
  summarize                                           summary.json 작성(이미 있으면 거부)
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from collections import Counter

import numpy as np

import v2
from v2 import CLASSES, DOC, ROOT, digest, dump, now

NEW_RECORDS = ROOT / "data/annotations/ble-v2-return/records.json"
EXP = "return-label-01"
OUT = DOC / EXP
RUNS = ROOT / "ml/runs" / EXP
LABELS = ("old", "new", "newangle")
SCORINGS = ("old_window", "new_window")


def load():
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
    """label=new면 방향 원본의 completion_ms를 r로 바꾼 사본. v2.windows가 이 값으로 라벨을 붙인다."""
    if label == "old":
        return by_path
    assert label in ("new", "newangle")
    out = {}
    for p, r in by_path.items():
        r = dict(r)
        if r["completion_ms"] is not None:
            r["completion_ms"] = nb[p]["event_ms"]
        out[p] = r
    return out


def window_of(path, by_path, nb, scoring):
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
        counts, delays, kinds = classify(record, events, window_of(record["source_path"], by_path, nb, scoring))
        totals.update(counts)
        per_source.append({"source_path": record["source_path"], "counts": counts, "delays_ms": delays, "events": kinds})
        offset += n
    assert offset == len(scores)
    return dict(totals), per_source


ANGLE_SCALE_DEG = 45.0


def with_angle(windows):
    """v2.windows를 감싸 회전각 3채널을 붙인다. 정규화된 자이로를 원시 deg/s로 되돌리고, 클립별 중앙값을
    영점으로 빼서 창 안에서 누적한다. 원시 자이로에 약 10 dps 치우침이 있어 보정 없이는 1.6초에 약 16도가 쌓인다.
    클립 중앙값은 비인과적이다(보드에서는 정지 구간에서 갱신하는 영점 추정으로 대신한다)."""
    def wrapped(record, mean, std, root=ROOT):
        x, y, meta = windows(record, mean, std, root)
        _, raw = v2.read_sensor(Path(root) / record["source_path"])
        bias = np.median(raw[:, 3:6], axis=0)
        gyro = x[:, :, 3:6].astype(np.float64) * std[3:6] + mean[3:6] - bias
        angle = np.cumsum(gyro * 0.01, axis=1)
        angle -= angle[:, :1, :]
        return np.concatenate([x, (angle / ANGLE_SCALE_DEG).astype(np.float32)], axis=2), y, meta
    return wrapped


def fit_snapshots_channels(x_train, y_train, x_val, seed, epochs):
    """v2.fit_snapshots와 같은 학습. 모델만 model.build_model 구성에서 입력 채널 수를 바꿔 만든다."""
    tf = v2.configure_tf()
    from model import build_model

    class Snapshot(tf.keras.callbacks.Callback):
        def __init__(self):
            super().__init__()
            self.scores = {}

        def on_epoch_end(self, epoch, logs=None):
            if epoch + 1 in epochs:
                self.scores[epoch + 1] = self.model(x_val, training=False).numpy()

    options = tf.data.Options()
    options.threading.private_threadpool_size = 1
    tf.keras.backend.clear_session()
    tf.keras.utils.set_random_seed(seed)
    config = build_model(v2.WINDOW).get_config()
    config["layers"][0]["config"]["batch_shape"] = (None, v2.WINDOW, x_train.shape[2])
    config.pop("build_input_shape", None)
    for layer in config["layers"]:
        layer.pop("build_config", None)      # 층마다 저장된 6채널 입력 모양을 지워 새 채널 수로 다시 빌드한다
    tf.keras.backend.clear_session()
    tf.keras.utils.set_random_seed(seed)
    model = tf.keras.Sequential.from_config(config)
    model.compile(optimizer=tf.keras.optimizers.Adam(.001), loss="sparse_categorical_crossentropy")
    ds = (tf.data.Dataset.from_tensor_slices((x_train, y_train)).shuffle(len(y_train), seed=seed)
          .batch(16).with_options(options))
    snap = Snapshot()
    hist = model.fit(ds, epochs=max(epochs), verbose=0, shuffle=False, callbacks=[snap])
    return snap.scores, hist.history["loss"], model.count_params()


def result_path(label, split, seed):
    """원본 결과(수 MB씩)는 깃 제외 폴더에 둔다. 저장소에는 OUT/results/에 gzip 사본을 올린다."""
    return RUNS / "results" / f"{label}-{split}" / f"seed-{seed}.json"


def cmd_run(label, split_name, seed):
    target = result_path(label, split_name, seed)
    if target.exists():
        raise FileExistsError(f"{target}가 이미 있다. 덮어쓰지 않는다")
    _, by_path, nb = load()
    recs = relabel(by_path, nb, label)
    if label == "newangle":
        v2.windows = with_angle(v2.windows)
    split = v2.load_split(split_name)
    score_dir = RUNS / f"{label}-{split_name}"
    score_dir.mkdir(parents=True, exist_ok=True)
    result = {"experiment": EXP, "label": label, "split": split_name, "seed": seed, "created_kst": now(),
              "code_sha256": {f: digest(ROOT / "ml" / f) for f in ("v2.py", "v2_return.py", "model.py")},
              "records_sha256": digest(v2.RECORDS), "new_records_sha256": digest(NEW_RECORDS),
              "epochs": list(v2.EPOCH_CANDIDATES), "folds": []}
    t_start = time.time()
    for k in range(split["cv"]["n_folds"]):
        t0 = time.time()
        d = v2.fold_sets(recs, split, k)
        x_val = np.concatenate([c[1] for c in d["val"]])
        if label == "newangle":
            scores, train_loss, n_params = fit_snapshots_channels(d["x_train"], d["y_train"], x_val, seed, tuple(v2.EPOCH_CANDIDATES))
            result["model_params"] = n_params
        else:
            scores, train_loss = v2.fit_snapshots(d["x_train"], d["y_train"], x_val, seed, tuple(v2.EPOCH_CANDIDATES))
        np.savez_compressed(score_dir / f"seed-{seed}-fold-{k}-scores.npz",
                            **{f"e{e}": scores[e].astype(np.float32) for e in v2.EPOCH_CANDIDATES})
        per_epoch = {}
        for e in v2.EPOCH_CANDIDATES:
            per_epoch[str(e)] = {s: dict(zip(("totals", "per_source"), score(d["val"], scores[e], by_path, nb, s))) for s in SCORINGS}
        result["folds"].append({"fold": k, "held_out_session": split["cv"]["folds"][k].get("held_out_session"),
                                "train_windows_selected": d["train_counts"], "per_epoch": per_epoch,
                                "seconds": round(time.time() - t0, 1)})
        print(f"{label} {split_name} seed {seed} fold {k}: {round(time.time() - t0, 1)}s", flush=True)
    result["seconds"] = round(time.time() - t_start, 1)
    result["tf_threads_fixed"] = v2.tf_threads_fixed
    dump(target, result)
    print("saved", target)


def cmd_run_all(parallel):
    jobs = [(lab, sp, s) for lab in LABELS for sp in v2.SPLIT_NAMES for s in v2.SEEDS
            if not result_path(lab, sp, s).exists()]
    print("pending:", len(jobs), flush=True)
    logs = OUT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    running, failed = [], []
    for lab, sp, s in jobs:
        log = open(logs / f"{lab}-{sp}-seed-{s}.log", "w", encoding="utf-8")
        p = subprocess.Popen([sys.executable, str(ROOT / "ml/v2_return.py"), "run", "--label", lab, "--split", sp, "--seed", str(s)],
                             cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        running.append(((lab, sp, s), p, log))
        while sum(p.poll() is None for _, p, _ in running) >= parallel:
            time.sleep(2)
    for job, p, log in running:
        if p.wait():
            failed.append(job)
        log.close()
    print("failed:", failed or "none")
    if failed:
        sys.exit(1)


def epoch_stats(seed_results, epoch, scoring):
    """seed별로 fold를 합친 뒤 seed 평균을 낸다."""
    per_seed = []
    for res in seed_results:
        sources = [p for f in res["folds"] for p in f["per_epoch"][str(epoch)][scoring]["per_source"]]
        gest = [p for p in sources if p["source_path"].rsplit("/", 1)[-1].startswith("raw_")]
        c = Counter()
        for p in gest:
            c.update(p["counts"])
        bg = [p for p in sources if not p["source_path"].rsplit("/", 1)[-1].startswith("raw_")]
        unmatched = sum(c[k] for k in v2.UNMATCHED_ON_GESTURE)
        no_issue = sum(1 for p in gest if not p["events"])
        early_clips = sum(1 for p in gest if any(ev[2] == "early" for ev in p["events"]))
        delays = [d for p in gest for d in p["delays_ms"]]
        per_seed.append({"n": len(gest), "correct": c["correct"], "unmatched": unmatched,
                         "selection_score": (c["correct"] - unmatched) / len(gest),
                         "success_rate": c["correct"] / len(gest),
                         "early_clip_rate": early_clips / len(gest), "no_issue_rate": no_issue / len(gest),
                         "wrong_direction": c["wrong_direction"], "duplicate": c["duplicate"], "late": c["late_unmatched"],
                         "background_false": sum(p["counts"].get("background_false", 0) for p in bg), "background_clips": len(bg),
                         "delay_median_ms": float(np.median(delays)) if delays else None})
    keys = ("success_rate", "selection_score", "early_clip_rate", "no_issue_rate")
    out = {k: float(np.mean([s[k] for s in per_seed])) for k in keys}
    out["success_rate_range"] = [min(s["success_rate"] for s in per_seed), max(s["success_rate"] for s in per_seed)]
    out["background_false_per_clip"] = float(np.mean([s["background_false"] / s["background_clips"] for s in per_seed]))
    d = [s["delay_median_ms"] for s in per_seed if s["delay_median_ms"] is not None]
    out["delay_median_ms"] = float(np.mean(d)) if d else None
    out["per_seed"] = per_seed
    return out


def cmd_summarize(name="summary.json"):
    target = OUT / name
    if target.exists():
        raise FileExistsError(f"{target}가 이미 있다")
    summary = {"experiment": EXP, "created_kst": now(), "rule": "E는 seed 평균 selection_score 최대, 같으면 작은 E", "panels": {}}
    labels = [lab for lab in LABELS if all(result_path(lab, sp, s).exists() for sp in v2.SPLIT_NAMES for s in v2.SEEDS)]
    summary["labels"] = labels
    for lab in labels:
        for sp in v2.SPLIT_NAMES:
            res = [json.loads(result_path(lab, sp, s).read_text(encoding="utf-8")) for s in v2.SEEDS]
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
        for sp in v2.SPLIT_NAMES:
            row = [sp]
            for lab in summary.get("labels", LABELS):
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
    r.add_argument("--split", choices=v2.SPLIT_NAMES, required=True)
    r.add_argument("--seed", type=int, required=True)
    a = sub.add_parser("run-all")
    a.add_argument("--parallel", type=int, default=8)
    m = sub.add_parser("summarize")
    m.add_argument("--out", default="summary.json")
    args = p.parse_args()
    if args.cmd == "run":
        cmd_run(args.label, args.split, args.seed)
    elif args.cmd == "run-all":
        cmd_run_all(args.parallel)
    else:
        cmd_summarize(args.out)


if __name__ == "__main__":
    main()
