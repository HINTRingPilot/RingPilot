"""BLE-06-cal: fixed-epoch calibration with source-level 5-fold CV (TrainingPlan, 개발 평가 v2).

Commands: --prepare (freeze folds + protocol), --train, --summarize.
Baseline A only (2-layer Flatten, 160 rows, 150 ms, no augmentation, no class weight).
The 22 final-evaluation sources (split=test) and the 5 excluded sources are never read.

One training run per (seed, fold) goes to max(E) epochs and is scored at every E.
This equals separate fixed-E runs: Adam with constant lr, no early stopping, and the
same shuffle stream make the first E epochs identical regardless of the stopping point.
"""

import argparse
from collections import Counter
from datetime import datetime
import importlib.metadata
import json
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

import baseline as base
import numpy as np

ROOT = base.ROOT
FOLDS = ROOT / "data/splits/ble-v1-cv5.json"
DOC = ROOT / "docs/experiments/ble-v1/results/BLE-06-cal"
RUNS = ROOT / "ml/runs/BLE-06-cal"
SEEDS = (20261021, 20261022, 20261023, 20261024, 20261025)
EPOCHS = (10, 20, 30, 40, 60)
N_FOLDS = 5
UNMATCHED = ("early", "wrong_direction", "duplicate", "late_unmatched", "background_false")


def now():
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def load_manifest():
    manifest = json.loads(base.MANIFEST.read_text(encoding="utf-8"))
    for r in manifest["records"]:
        assert base.digest(ROOT / r["source_path"]) == r["sha256"], r["source_path"]
    return manifest


def pools(manifest):
    direction = [r for r in manifest["records"] if r["split"] in ("train", "validation") and r["direction"] != "NONE"]
    train_bg = [r for r in manifest["records"] if r["split"] == "train" and r["direction"] == "NONE"]
    val_bg = [r for r in manifest["records"] if r["split"] == "validation" and r["direction"] == "NONE"]
    assert len(direction) == 35 and len(train_bg) == 2 and len(val_bg) == 2
    assert all(r["decision"] == "ACCEPT_SENSOR_LABEL" for r in direction)
    return direction, train_bg, val_bg


def prepare():
    if FOLDS.exists() or (DOC / "protocol.json").exists():
        raise FileExistsError("CV folds/protocol already frozen; use a new version to change")
    manifest = load_manifest()
    direction, train_bg, val_bg = pools(manifest)
    rng = np.random.default_rng(base.SEED)
    assignment, pointer = {}, 0
    for cls in base.CLASSES[1:]:
        sources = sorted(r["source_path"] for r in direction if r["direction"] == cls)
        order = rng.permutation(len(sources))
        # One running pointer across classes keeps fold sizes within one source of each other.
        for i in order:
            assignment[sources[i]] = pointer % N_FOLDS
            pointer += 1
    folds = []
    for k in range(N_FOLDS):
        members = sorted(s for s, f in assignment.items() if f == k)
        by_cls = Counter(next(r["direction"] for r in direction if r["source_path"] == s) for s in members)
        folds.append({"fold": k, "validation_direction_sources": members, "direction_counts": dict(by_cls)})
    value = {"version": "ble-v1-cv5", "seed": base.SEED, "created_kst": now(),
             "manifest_sha256": base.digest(base.MANIFEST),
             "unit": "source file; windows inherit parent fold",
             "folds": folds,
             "training_background_sources": [r["source_path"] for r in train_bg],
             "validation_background_sources": [r["source_path"] for r in val_bg],
             "not_used": "split=test (22 final-evaluation sources) and split=excluded (5)"}
    base.dump(FOLDS, value)
    protocol = {"experiment": "BLE-06-cal", "created_before_training_kst": now(),
                "folds_sha256": base.digest(FOLDS), "manifest_sha256": base.digest(base.MANIFEST),
                "candidate": "A: 2-layer Conv, Flatten readout, 160 rows, 150 ms positive width, no augmentation, no class weight",
                "epochs": EPOCHS, "seeds": SEEDS, "n_folds": N_FOLDS,
                "optimizer": "Adam .001", "batch_size": 16,
                "early_stopping": None, "checkpoint_selection": None,
                "evaluation_note": "one run per (seed,fold) scored at every E; equivalent to separate fixed-E runs",
                "per_fold_recomputed": ["normalization (fold training sources only)", "NONE selection (baseline.choose_training)"],
                "postprocessing": "baseline.issue_events (score>=.8, margin>=.2, 2 consecutive, rearm after 2 NONE>=.8); event window [e, e+500ms]",
                "selection_rule": "per-seed sum over folds of (correct events - unmatched emissions); choose E with the largest mean over seeds; ties go to the smaller E",
                "unmatched_definition": UNMATCHED,
                "background_note": "the same 20 s validation background is replayed in every fold with a different model; not added to observation time",
                "decision_thresholds_for_2x2": "NOT fixed yet; set in the BLE-06 protocol after seeing the A seed range from this calibration",
                "final_test_inference": False}
    base.dump(DOC / "protocol.json", protocol)
    print(json.dumps({"folds": [f["direction_counts"] for f in folds], "sizes": [len(f["validation_direction_sources"]) for f in folds]}))


def fold_data(manifest, folds, k):
    direction, train_bg, val_bg = pools(manifest)
    held = set(folds["folds"][k]["validation_direction_sources"])
    train = [r for r in direction if r["source_path"] not in held] + train_bg
    val = [r for r in direction if r["source_path"] in held] + val_bg
    assert {r["source_path"] for r in train}.isdisjoint(r["source_path"] for r in val)
    raw = np.concatenate([base.read_sensor(ROOT / r["source_path"])[1] for r in train])
    mean, std = raw.mean(axis=0), np.maximum(raw.std(axis=0), 1e-6)
    chunks = [base.windows(r, mean, std) for r in train]
    x = np.concatenate([c[0] for c in chunks])
    y = np.concatenate([c[1] for c in chunks])
    meta = sum([c[2] for c in chunks], [])
    idx = base.choose_training(y, meta)
    val_chunks = [(r, *base.windows(r, mean, std)) for r in val]
    return {"x_train": x[idx], "y_train": y[idx], "val": val_chunks, "mean": mean, "std": std,
            "train_sources": len(train), "train_counts": np.bincount(y[idx], minlength=5).tolist()}


def score_events(val_chunks, scores):
    totals, offset, per_source = Counter(), 0, []
    for r, _, labels, meta in val_chunks:
        n = len(labels)
        events = base.issue_events([m["timestamp_ms"] for m in meta], scores[offset:offset + n])
        counts, delays, _ = base.classify_events(r, events)
        totals.update(counts)
        per_source.append({"source_path": r["source_path"], "counts": counts, "delays_ms": delays})
        offset += n
    assert offset == len(scores)
    return dict(totals), per_source


def train():
    import tensorflow as tf
    from model import build_model

    manifest = load_manifest()
    protocol = json.loads((DOC / "protocol.json").read_text(encoding="utf-8"))
    assert protocol["folds_sha256"] == base.digest(FOLDS) and protocol["manifest_sha256"] == base.digest(base.MANIFEST)
    folds = json.loads(FOLDS.read_text(encoding="utf-8"))
    if RUNS.exists():
        raise FileExistsError("Refusing to overwrite existing calibration runs")
    RUNS.mkdir(parents=True)
    (RUNS / "tmp").mkdir()
    tempfile.tempdir = str(RUNS / "tmp")
    for f in ("baseline.py", "experiment6_cal.py", "model.py"):
        shutil.copy2(ROOT / "ml" / f, RUNS / f)
    (RUNS / "environment.txt").write_text("\n".join(sorted(f'{d.metadata["Name"]}=={d.version}' for d in importlib.metadata.distributions())) + "\n", encoding="utf-8")
    tf.config.threading.set_intra_op_parallelism_threads(1)
    tf.config.threading.set_inter_op_parallelism_threads(1)
    tf.config.experimental.enable_op_determinism()
    data = {k: fold_data(manifest, folds, k) for k in range(N_FOLDS)}
    options = tf.data.Options()
    options.threading.private_threadpool_size = 1

    class Snapshot(tf.keras.callbacks.Callback):
        def __init__(self, x_val):
            super().__init__()
            self.x_val, self.scores = x_val, {}

        def on_epoch_end(self, epoch, logs=None):
            if epoch + 1 in EPOCHS:
                self.scores[epoch + 1] = self.model(self.x_val, training=False).numpy()

    results = []
    for seed in SEEDS:
        for k in range(N_FOLDS):
            d = data[k]
            x_val = np.concatenate([c[1] for c in d["val"]])
            tf.keras.backend.clear_session()
            tf.keras.utils.set_random_seed(seed)
            model = build_model(160)
            model.compile(optimizer=tf.keras.optimizers.Adam(.001), loss="sparse_categorical_crossentropy")
            ds = tf.data.Dataset.from_tensor_slices((d["x_train"], d["y_train"])).shuffle(len(d["y_train"]), seed=seed).batch(16).with_options(options)
            snap = Snapshot(x_val)
            print(f"BEGIN seed={seed} fold={k} train_windows={len(d['y_train'])}", flush=True)
            hist = model.fit(ds, epochs=max(EPOCHS), verbose=0, shuffle=False, callbacks=[snap])
            for e in EPOCHS:
                totals, per_source = score_events(d["val"], snap.scores[e])
                results.append({"seed": seed, "fold": k, "epoch": e, "train_loss": float(hist.history["loss"][e - 1]),
                                "event_totals": totals, "per_source": per_source})
                print(f"  E={e} loss={hist.history['loss'][e-1]:.3f} {totals}", flush=True)
    base.dump(RUNS / "results.json", {"created_kst": now(), "python": sys.version, "tensorflow": tf.__version__,
                                      "numpy": np.__version__, "results": results,
                                      "fold_train_counts": [data[k]["train_counts"] for k in range(N_FOLDS)],
                                      "final_test_inference": False})
    shutil.copy2(RUNS / "results.json", DOC / "results.json")


def summarize():
    raw = json.loads((DOC / "results.json").read_text(encoding="utf-8"))["results"]
    table, per_seed = {}, {}
    for e in EPOCHS:
        rows = []
        for seed in SEEDS:
            sel = [r for r in raw if r["epoch"] == e and r["seed"] == seed]
            assert len(sel) == N_FOLDS
            c = sum(r["event_totals"].get("correct", 0) for r in sel)
            u = sum(sum(r["event_totals"].get(k, 0) for k in UNMATCHED) for r in sel)
            early = sum(r["event_totals"].get("early", 0) for r in sel)
            bg = sum(r["event_totals"].get("background_false", 0) for r in sel)
            rows.append({"seed": seed, "correct": c, "unmatched": u, "early": early, "background_false": bg, "score": c - u})
        per_seed[e] = rows
        table[e] = {"mean_score": float(np.mean([r["score"] for r in rows])),
                    "mean_correct": float(np.mean([r["correct"] for r in rows])),
                    "mean_unmatched": float(np.mean([r["unmatched"] for r in rows])),
                    "correct_range": [min(r["correct"] for r in rows), max(r["correct"] for r in rows)]}
    best = max(table.values(), key=lambda t: t["mean_score"])["mean_score"]
    chosen = min(e for e in EPOCHS if table[e]["mean_score"] == best)
    out = {"experiment": "BLE-06-cal", "created_kst": now(), "protocol_sha256": base.digest(DOC / "protocol.json"),
           "per_epoch": table, "per_seed": per_seed, "chosen_E": chosen,
           "baseline_A_correct_range_at_chosen_E": table[chosen]["correct_range"],
           "final_test_inference": False}
    base.dump(DOC / "summary.json", out)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    for name in ("prepare", "train", "summarize"):
        g.add_argument(f"--{name}", action="store_true")
    a = p.parse_args()
    prepare() if a.prepare else train() if a.train else summarize()
