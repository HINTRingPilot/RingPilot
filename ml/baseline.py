"""Local BLE-01 preparation, deterministic baseline training and validation replay.

Run with ml/.venv/Scripts/python.exe ml/baseline.py --prepare or --train.
No remote services or final-test inference are used.
"""

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
os.environ.setdefault("TF_DETERMINISTIC_OPS", "1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT / "data/annotations/ble-v1"
MANIFEST = ROOT / "data/splits/ble-v1.json"
RUN = ROOT / "ml/runs/BLE-01-r01"
SEED = 20261021
CLASSES = ("NONE", "UP", "DOWN", "LEFT", "RIGHT")
AXES = ("accX", "accY", "accZ", "gyrX", "gyrY", "gyrZ")
OLD = "phone-20261021-091621"
NEW = "phone-20261021-094346"
BG = "phone-20261021-093345"


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_sensor(path):
    with path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["timestamp", *AXES]:
            raise ValueError(f"Invalid axis order: {path}")
        rows = list(reader)
    a = np.array([[float(r[k]) for k in ("timestamp", *AXES)] for r in rows], dtype=np.float64)
    if not np.isfinite(a).all() or a[0, 0] != 0 or not np.all(np.diff(a[:, 0]) == 10):
        raise ValueError(f"Nonfinite/discontinuous sensor file: {path}")
    if len(a) != (300 if path.name.startswith("raw_") else 1000):
        raise ValueError(f"Unexpected row count: {path}")
    return a[:, 0], a[:, 1:]


def positive_count(e):
    return sum(e <= t < e + 150 for t in range(1590, 3000, 50))


def prepare():
    if MANIFEST.exists():
        raise FileExistsError("Split already frozen; use a new manifest version to change it")
    quality = json.loads((ANN / "quality.json").read_text(encoding="utf-8"))
    by_path = {}
    for p in sorted(ANN.glob("*-candidates.json")):
        for a in json.loads(p.read_text(encoding="utf-8"))["annotations"]:
            by_path[a["source_path"]] = a
    assert len(by_path) == 60
    # Decisions are based on sensor traces, before any model prediction.
    # Neither the filename's intended direction nor a sensor-derived completion
    # is independent video/user ground truth.
    holds = {
        f"data/sessions/{OLD}/raw_right.1.csv": "ambiguous_multiple_motion_clusters; retained in held-out test, completion not confirmed",
        f"data/sessions/{NEW}/raw_up.1.csv": "gyro reaches 1002 deg/s; possible saturation; hold rather than assume clean shape",
        f"data/sessions/{NEW}/raw_left.6.csv": "late secondary motion near completion; single completion ambiguous",
        f"data/sessions/{NEW}/raw_right.6.csv": "no 180 ms settled segment; fallback completion is not accepted",
    }
    records = []
    for q in quality:
        src = q["source_path"]
        ts, values = read_sensor(ROOT / src)
        assert digest(ROOT / src) == q["sha256"]
        record = dict(q)
        a = by_path.get(src)
        if a:
            e = a["completion_ms"]
            n = positive_count(e)
            record.update(direction=a["direction"], completion_ms=e, positive_windows=n,
                          original_status=a["status"], original_flags=a["flags"],
                          review_basis="agent_visual_sensor_review_2026-10-21; no video confirmation")
            if src in holds:
                record.update(decision="HOLD", reason=holds[src])
            elif not n:
                record.update(decision="EXCLUDE_BASELINE", reason="zero positive windows after 160-row warmup; keep original completion unchanged")
            else:
                record.update(decision="ACCEPT_SENSOR_LABEL", reason="dominant movement and return visible; keep sensor-derived completion; early/late flags alone do not exclude")
            record["positive_interval_truncated_by_warmup"] = e < 1590
            record["less_than_two_positive_windows"] = n < 2
            record["positive_interval_truncated_by_clip_end"] = bool(e + 150 > ts[-1] + 10)
            record["match_horizon_clipped"] = bool(e + 500 > ts[-1])
            record["split"] = "test" if f"/{OLD}/" in src else "excluded"
        else:
            record.update(direction="NONE", completion_ms=None, decision="ACCEPT_RECORDING_LABEL",
                          reason="idle/other recording label; traces reviewed; intended-command absence is not independently video-verified")
            if f"/{NEW}/" in src:
                record["split"] = "train"
            elif src.endswith(".1.csv"):
                record["split"] = "validation"
            else:
                record["split"] = "test"
        records.append(record)
    rng = np.random.default_rng(SEED)
    for direction in CLASSES[1:]:
        eligible = sorted([r for r in records if f"/{NEW}/" in r["source_path"]
                           and r["direction"] == direction and r["decision"] == "ACCEPT_SENSOR_LABEL"],
                          key=lambda r: int(Path(r["source_path"]).stem.split(".")[-1]))
        assert len(eligible) >= 3
        validation = set(rng.choice(len(eligible), size=2, replace=False).tolist())
        for i, r in enumerate(eligible):
            r["split"] = "validation" if i in validation else "train"
    assert len(records) == 66
    assert len({r["source_path"] for r in records}) == 66
    assert len({r["sha256"] for r in records}) == 66
    manifest = {"version": "ble-v1", "seed": SEED, "classes": CLASSES, "axes": AXES,
                "review_limit": "Sensor-derived operational labels, no video or user confirmation; test predictions unopened",
                "annotation_sha256": {p.name: digest(p) for p in sorted(ANN.glob("*-candidates.json"))},
                "records": records}
    dump(MANIFEST, manifest)
    dump(ANN / "review-decisions.json", records)
    print(json.dumps({"split": dict(Counter(r["split"] for r in records)),
                      "decisions": dict(Counter(r["decision"] for r in records))}))


def windows(record, mean, std):
    ts, raw = read_sensor(ROOT / record["source_path"])
    ends = np.arange(159, len(raw), 5)
    x = np.stack([raw[i-159:i+1] for i in ends])
    y = np.zeros(len(ends), dtype=np.int64)
    categories = []
    e = record["completion_ms"]
    if e is not None:
        mask = (ts[ends] >= e) & (ts[ends] < e+150)
        y[mask] = CLASSES.index(record["direction"])
        # Before completion includes start and movement; split it into fixed bins
        # without using any validation statistics.
        categories = ["pre_start" if t < 500 else "in_progress" if t < e else "post_completion" for t in ts[ends]]
    else:
        categories = [Path(record["source_path"]).name.split(".")[0]] * len(ends)
    x = ((x-mean) / std).astype(np.float32)
    assert x.shape[1:] == (160, 6) and np.isfinite(x).all()
    meta = [{"source_path": record["source_path"], "timestamp_ms": int(ts[i]),
             "target": int(label), "none_group": category} for i, label, category in zip(ends, y, categories)]
    return x, y, meta


def choose_training(y, meta, seed=SEED):
    rng = np.random.default_rng(seed)
    positive = np.flatnonzero(y != 0).tolist()
    # Round-robin by NONE source type, then by source file.
    groups = defaultdict(lambda: defaultdict(list))
    for i in np.flatnonzero(y == 0):
        groups[meta[i]["none_group"]][meta[i]["source_path"]].append(int(i))
    for files in groups.values():
        for indices in files.values():
            rng.shuffle(indices)
    queues = {}
    for name, files in sorted(groups.items()):
        queue = []
        while any(files.values()):
            for src in sorted(files):
                if files[src]:
                    queue.append(files[src].pop())
        queues[name] = queue
    none = []
    positions = Counter()
    while len(none) < len(positive):
        changed = False
        for name, queue in queues.items():
            if positions[name] < len(queue) and len(none) < len(positive):
                none.append(queue[positions[name]])
                positions[name] += 1
                changed = True
        if not changed:
            break
    assert positive and none
    return np.array(sorted(positive+none), dtype=np.int64)


def issue_events(times, scores):
    """Reset per file; emit at second qualifying prediction, rearm on 2 NONEs."""
    events = []
    locked, candidate, count, none_count = False, None, 0, 0
    for t, p in zip(times, scores):
        top = int(np.argmax(p))
        if locked:
            none_count = none_count+1 if top == 0 and p[0] >= .8 else 0
            if none_count >= 2:
                locked, candidate, count, none_count = False, None, 0, 0
            continue
        margin = np.sort(p)[-1] - np.sort(p)[-2]
        if top != 0 and p[top] >= .8 and margin >= .2:
            count = count+1 if top == candidate else 1
            candidate = top
            if count >= 2:
                events.append({"timestamp_ms": int(t), "class_index": top, "score": float(p[top])})
                locked, candidate, count, none_count = True, None, 0, 0
        else:
            candidate, count = None, 0
    return events


def classify_events(record, events):
    e = record["completion_ms"]
    matched = False
    counts = Counter({k: 0 for k in ("correct", "missed", "wrong_direction", "duplicate", "early", "late_unmatched", "background_false")})
    delays = []
    annotated = []
    for event in events:
        event = dict(event)
        t = event["timestamp_ms"]
        if e is None:
            kind = "background_false"
        elif t < e:
            kind = "early"
        elif t > e + 500:
            kind = "late_unmatched"
        elif event["class_index"] != CLASSES.index(record["direction"]):
            kind = "wrong_direction"
        elif matched:
            kind = "duplicate"
        else:
            kind, matched = "correct", True
            delays.append(t-e)
        counts[kind] += 1
        event["kind"] = kind
        annotated.append(event)
    if e is not None and not matched:
        counts["missed"] = 1
    return dict(counts), delays, annotated


def train():
    import tensorflow as tf
    from model import build_model
    from sklearn.metrics import classification_report, confusion_matrix

    if RUN.exists():
        raise FileExistsError("Refusing to overwrite an existing run")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["seed"] == SEED and tuple(manifest["classes"]) == CLASSES
    records = manifest["records"]
    for record in records:
        assert digest(ROOT / record["source_path"]) == record["sha256"], record["source_path"]
    for filename, sha in manifest["annotation_sha256"].items():
        assert digest(ANN / filename) == sha
    training = [r for r in records if r["split"] == "train"]
    validation = [r for r in records if r["split"] == "validation"]
    assert {r["source_path"] for r in training}.isdisjoint(r["source_path"] for r in validation)
    raw_train = np.concatenate([read_sensor(ROOT / r["source_path"])[1] for r in training])
    mean, std = raw_train.mean(axis=0), np.maximum(raw_train.std(axis=0), 1e-6)
    data = {}
    for split, selected in (("train", training), ("validation", validation)):
        chunks = [windows(r, mean, std) for r in selected]
        data[split] = (np.concatenate([c[0] for c in chunks]), np.concatenate([c[1] for c in chunks]), sum([c[2] for c in chunks], []))
    x_train, y_train, meta_train = data["train"]
    indices = choose_training(y_train, meta_train)
    x_val, y_val, meta_val = data["validation"]
    RUN.mkdir(parents=True)
    (RUN / "tmp").mkdir()
    tempfile.tempdir = str(RUN / "tmp")
    shutil.copy2(MANIFEST, RUN / "split.json")
    for file in ("baseline.py", "model.py", "requirements.txt", "review_data.py"):
        shutil.copy2(ROOT / "ml" / file, RUN / file)
    shutil.copytree(ANN, RUN / "annotations")
    dump(RUN / "normalization.json", {"axes": AXES, "mean": mean.tolist(), "std": std.tolist(), "raw_train_rows": len(raw_train), "ddof": 0})
    dump(RUN / "train-windows.json", [meta_train[i] for i in indices])
    dump(RUN / "validation-windows.json", meta_val)
    np.savez_compressed(RUN / "inputs.npz", x_train=x_train[indices], y_train=y_train[indices], x_validation=x_val, y_validation=y_val)
    tf.config.threading.set_intra_op_parallelism_threads(1)
    tf.config.threading.set_inter_op_parallelism_threads(1)
    tf.keras.utils.set_random_seed(SEED)
    tf.config.experimental.enable_op_determinism()
    config = {"run_id": RUN.name, "start_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
              "seed": SEED, "python": sys.version, "tensorflow": tf.__version__, "keras": tf.keras.__version__,
              "numpy": np.__version__, "platform": platform.platform(), "devices": [str(d) for d in tf.config.list_physical_devices()],
              "optimizer": "Adam", "learning_rate": .001, "batch_size": 16, "max_epochs": 100,
              "early_stopping": {"monitor": "val_loss", "patience": 12, "restore_best_weights": True},
              "loss": "sparse_categorical_crossentropy", "augmentation": False, "threshold": .8, "margin": .2,
              "consecutive_direction": 2, "consecutive_none": 2, "event_tolerance_ms": 500,
              "temp_directory": str(RUN / "tmp"),
              "manifest_sha256": digest(MANIFEST), "code_sha256": {p: digest(ROOT/"ml"/p) for p in ("model.py", "baseline.py")},
              "train_classes_all_windows": np.bincount(y_train, minlength=5).tolist(),
              "train_classes_selected": np.bincount(y_train[indices], minlength=5).tolist(),
              "validation_classes": np.bincount(y_val, minlength=5).tolist(),
              "train_none_groups": dict(Counter(meta_train[i]["none_group"] for i in indices if y_train[i] == 0)),
              "git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()}
    (RUN / "working-tree.diff").write_bytes(subprocess.run(["git", "diff", "--binary"], cwd=ROOT, capture_output=True, check=True).stdout)
    (RUN / "git-status.txt").write_bytes(subprocess.run(["git", "status", "--short"], cwd=ROOT, capture_output=True, check=True).stdout)
    (RUN / "environment.txt").write_text("\n".join(sorted(
        f'{d.metadata["Name"]}=={d.version}' for d in importlib.metadata.distributions())) + "\n", encoding="utf-8")
    dump(RUN / "config.json", config)
    model = build_model()
    assert model.count_params() == 9493
    model.compile(optimizer=tf.keras.optimizers.Adam(.001), loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    with (RUN / "model-summary.txt").open("w", encoding="utf-8") as f:
        model.summary(print_fn=lambda line: f.write(line+"\n"))
    options = tf.data.Options()
    options.threading.private_threadpool_size = 1
    ds_train = tf.data.Dataset.from_tensor_slices((x_train[indices], y_train[indices])).shuffle(len(indices), seed=SEED).batch(16).with_options(options)
    ds_val = tf.data.Dataset.from_tensor_slices((x_val, y_val)).batch(16).with_options(options)
    hist = model.fit(ds_train, validation_data=ds_val, epochs=100, verbose=2, shuffle=False, callbacks=[
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=12, restore_best_weights=True),
        tf.keras.callbacks.CSVLogger(str(RUN / "history.csv")),
        tf.keras.callbacks.ModelCheckpoint(str(RUN / "best.keras"), monitor="val_loss", save_best_only=True),
    ])
    model.save(RUN / "model.keras")
    scores = model(x_val, training=False).numpy()
    predicted = scores.argmax(axis=1)
    np.save(RUN / "validation-scores.npy", scores)
    with (RUN / "validation-predictions.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source_path", "timestamp_ms", "target", "predicted", *CLASSES])
        for m, p, v in zip(meta_val, predicted, scores):
            writer.writerow([m["source_path"], m["timestamp_ms"], CLASSES[m["target"]], CLASSES[p], *v.tolist()])
    result = {"run_id": config["run_id"], "end_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
              "epochs": len(hist.history["loss"]), "best_epoch": int(np.argmin(hist.history["val_loss"]))+1,
              "best_val_loss": float(min(hist.history["val_loss"])),
              "validation_window_accuracy": float(np.mean(predicted == y_val)),
              "confusion_matrix": confusion_matrix(y_val, predicted, labels=range(5)).tolist(),
              "class_report": classification_report(y_val, predicted, labels=range(5), target_names=CLASSES, zero_division=0, output_dict=True),
              "event_totals": {}, "per_file": [], "final_test_inference": False}
    totals, delays = Counter(), []
    offset = 0
    for r in validation:
        _, labels, meta = windows(r, mean, std)
        n = len(labels)
        events = issue_events([m["timestamp_ms"] for m in meta], scores[offset:offset+n])
        counts, latency, annotated = classify_events(r, events)
        totals.update(counts)
        delays.extend(latency)
        result["per_file"].append({"source_path": r["source_path"], "completion_ms": r["completion_ms"],
                                   "positive_windows": int(np.sum(labels != 0)), "events": annotated, "counts": counts,
                                   "raw_duration_s": r["rows"] / 100,
                                   "inference_exposure_s": (r["rows"] * 10 - 1590) / 1000,
                                   "nominal_scoring_bin_seconds": n * .05})
        offset += n
    assert offset == len(y_val)
    result["event_totals"] = dict(totals)
    result["gesture_count"] = sum(r["direction"] != "NONE" for r in validation)
    result["background_recording_seconds"] = sum(r["rows"]/100 for r in validation if r["direction"] == "NONE")
    result["background_inference_exposure_seconds"] = sum(p["inference_exposure_s"] for p in result["per_file"] if p["completion_ms"] is None)
    result["latency_ms"] = {"n": len(delays), "median": float(np.median(delays)) if delays else None,
                            "p95": float(np.percentile(delays, 95)) if delays else None}
    result["warmup_s"] = 1.59
    result["note"] = "Independent clip replay. Exposure excludes 1590ms warmup; source duration includes the final 10ms sample interval. Nominal scoring bins may extend past clip end. No continuous/board validation."
    dump(RUN / "results.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--run-id", default="BLE-01-r01")
    args = parser.parse_args()
    if args.prepare == args.train:
        parser.error("Choose exactly one of --prepare or --train")
    if not re.fullmatch(r"BLE-01-r[0-9]{2,}", args.run_id):
        parser.error("Invalid run ID")
    RUN = ROOT / "ml/runs" / args.run_id
    prepare() if args.prepare else train()
