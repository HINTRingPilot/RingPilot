"""BLE-03 clip pilot: post-return training labels 150ms vs 300ms.

User requires commands after natural return and cannot collect continuous data
now. This is a bounded clip pilot, not the planned continuous policy selection.
Canonical validation targets (150ms), event anchor/tolerance and output state
machine remain unchanged. Both conditions use exactly the same 221 inputs.
"""

import argparse
import csv
from datetime import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

import baseline as base
import numpy as np

ROOT = base.ROOT
SOURCE = ROOT / "ml/runs/BLE-01-r03"
DATA = ROOT / "ml/runs/BLE-03-inputs"
DOC = ROOT / "docs/experiments/ble-v1/results/BLE-03"
SEEDS = (20261021, 20261022, 20261023)
WIDTHS = (150, 300)


def now():
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def targets(times, completion_ms, direction_index, width_ms):
    times = np.asarray(times)
    result = np.zeros(len(times), dtype=np.int64)
    if completion_ms is not None:
        result[(times >= completion_ms) & (times < completion_ms + width_ms)] = direction_index
    return result


def check_sources():
    manifest = json.loads((SOURCE / "split.json").read_text(encoding="utf-8"))
    assert base.digest(base.MANIFEST) == base.digest(SOURCE / "split.json")
    for r in manifest["records"]:
        assert base.digest(ROOT / r["source_path"]) == r["sha256"]
    return manifest


def prepare():
    if DATA.exists() or (DOC / "protocol.json").exists():
        raise FileExistsError("Refusing to overwrite fixed inputs/protocol")
    manifest = check_sources()
    norm = json.loads((SOURCE / "normalization.json").read_text(encoding="utf-8"))
    mean, std = np.array(norm["mean"]), np.array(norm["std"])
    training = [r for r in manifest["records"] if r["split"] == "train"]
    chunks = [base.windows(r, mean, std) for r in training]
    x = np.concatenate([c[0] for c in chunks])
    y150 = np.concatenate([c[1] for c in chunks])
    meta = sum([c[2] for c in chunks], [])
    by_source = {r["source_path"]: r for r in training}
    y300 = np.zeros(len(y150), dtype=np.int64)
    for i, m in enumerate(meta):
        r = by_source[m["source_path"]]
        y300[i] = targets([m["timestamp_ms"]], r["completion_ms"], base.CLASSES.index(r["direction"]), 300)[0]
    original_meta = json.loads((SOURCE / "train-windows.json").read_text(encoding="utf-8"))
    lookup = {(m["source_path"], m["timestamp_ms"]): i for i, m in enumerate(meta)}
    original_indices = [lookup[(m["source_path"], m["timestamp_ms"])] for m in original_meta]
    source_arrays = np.load(SOURCE / "inputs.npz")
    np.testing.assert_array_equal(x[original_indices], source_arrays["x_train"])
    np.testing.assert_array_equal(y150[original_indices], source_arrays["y_train"])
    # Expand once to include every possible 300ms positive from TRAIN only.
    # Keep this exact union in both conditions; do not resample NONE per policy.
    indices = sorted(set(original_indices) | set(np.flatnonzero(y300).tolist()))
    assert len(indices) == 221
    assert np.sum(y150[indices] != y300[indices]) == 81
    assert set(np.flatnonzero(y150)) <= set(indices)
    assert set(np.flatnonzero(y300)) <= set(indices)
    DATA.mkdir(parents=True)
    np.savez_compressed(DATA / "inputs.npz", x_train=x[indices], y150=y150[indices], y300=y300[indices],
                        x_validation=source_arrays["x_validation"], y_validation=source_arrays["y_validation"])
    base.dump(DATA / "train-windows.json", [dict(meta[i], target150=int(y150[i]), target300=int(y300[i])) for i in indices])
    for filename in ("split.json", "normalization.json", "validation-windows.json"):
        shutil.copy2(SOURCE / filename, DATA / filename)
    protocol = {"experiment": "BLE-03", "stage": "clip_pilot_only", "created_before_training_kst": now(),
                "user_target": "emit only after natural return is complete",
                "user_constraint": "cannot collect continuous data now",
                "not_done": ["continuous policy validation", "new annotation confirmation", "final test", "board inference"],
                "changed_factor": "training positive width after existing completion e: 150ms vs 300ms",
                "training_widths_ms": WIDTHS, "seeds": SEEDS, "class_order": base.CLASSES,
                "shared_train_inputs": 221, "original_train_inputs": 144, "additional_shared_inputs": 77,
                "train_counts_150": np.bincount(y150[indices], minlength=5).tolist(),
                "train_counts_300": np.bincount(y300[indices], minlength=5).tolist(),
                "relabelled_inputs": 81, "class_weight": None, "augmentation": False,
                "pool_rule": "union of original 144 train windows and all 300ms train positives; same inputs and order for both policies",
                "validation_rule": "original 570 windows and canonical 150ms targets unchanged; unweighted val_loss for checkpoint selection in both",
                "event_rule": "same direction in [e,e+500ms], one-to-one; any emission before e remains early, not a success",
                "return_label": "NONE until e (including outbound and return motion), direction for chosen width, then NONE",
                "model": "same 9493-parameter 160x6 CNN", "optimizer": "Adam .001", "batch_size": 16,
                "max_epochs": 100, "early_stopping": "unweighted canonical val_loss; patience12; restore best",
                "postprocessing": "score .8, margin .2, 2 same direction, 2 NONE for rearm",
                "input_sha256": base.digest(DATA / "inputs.npz"), "manifest_sha256": base.digest(DATA / "split.json"),
                "normalization_sha256": base.digest(DATA / "normalization.json"),
                "source_baseline_inputs_sha256": base.digest(SOURCE / "inputs.npz"),
                "decision_rule": "Pilot candidate only if mean correct events increases, mean unmatched emissions does not increase, and neither metric regresses in any seed; no final policy adoption without continuous data.",
                "final_test_inference": False}
    base.dump(DOC / "protocol.json", protocol)
    base.dump(DOC / "train-windows.json", [dict(meta[i], target150=int(y150[i]), target300=int(y300[i])) for i in indices])
    print(json.dumps(protocol, ensure_ascii=False, indent=2))


def train():
    import tensorflow as tf
    from model import build_model
    from experiment2 import evaluate
    protocol = json.loads((DOC / "protocol.json").read_text(encoding="utf-8"))
    manifest = check_sources()
    assert protocol["input_sha256"] == base.digest(DATA / "inputs.npz")
    assert protocol["normalization_sha256"] == base.digest(SOURCE / "normalization.json")
    a = np.load(DATA / "inputs.npz")
    meta = json.loads((DATA / "validation-windows.json").read_text(encoding="utf-8"))
    assert [m["target"] for m in meta] == a["y_validation"].tolist()
    tf.config.threading.set_intra_op_parallelism_threads(1)
    tf.config.threading.set_inter_op_parallelism_threads(1)
    tf.config.experimental.enable_op_determinism()
    for seed_ix, seed in enumerate(SEEDS):
        for condition_ix, width in enumerate(WIDTHS):
            run_id = f"BLE-03-r{seed_ix*2+condition_ix+1:02}"
            run = ROOT / "ml/runs" / run_id
            if run.exists(): raise FileExistsError(f"Refusing to overwrite {run}")
            run.mkdir(parents=True); (run / "tmp").mkdir(); tempfile.tempdir = str(run / "tmp")
            for script in ("baseline.py", "experiment2.py", "experiment3.py", "model.py"):
                shutil.copy2(ROOT / "ml" / script, run / script)
            for file in ("split.json", "normalization.json", "validation-windows.json", "train-windows.json"):
                shutil.copy2(DATA / file, run / file)
            shutil.copy2(DOC / "protocol.json", run / "protocol.json")
            (run / "environment.txt").write_text("\n".join(sorted(
                f'{d.metadata["Name"]}=={d.version}' for d in importlib.metadata.distributions())) + "\n", encoding="utf-8")
            tf.keras.backend.clear_session(); tf.keras.utils.set_random_seed(seed)
            model = build_model(); assert model.count_params() == 9493
            initial = [w.copy() for w in model.get_weights()]
            if condition_ix == 0: control_initial = initial
            else:
                for x, y in zip(initial, control_initial): np.testing.assert_array_equal(x, y)
            model.compile(optimizer=tf.keras.optimizers.Adam(.001), loss="sparse_categorical_crossentropy", metrics=["accuracy"])
            config = {"run_id": run_id, "width_ms": width, "seed": seed, "start_kst": now(),
                      "protocol_sha256": base.digest(DOC / "protocol.json"), "input_sha256": protocol["input_sha256"],
                      "model_code_sha256": base.digest(ROOT / "ml/model.py"), "runner_sha256": base.digest(ROOT / "ml/experiment3.py"),
                      "evaluator_sha256": base.digest(ROOT / "ml/experiment2.py"),
                      "train_targets_sha256": hashlib.sha256(a[f'y{width}'].tobytes()).hexdigest(),
                      "python": sys.version, "tensorflow": tf.__version__, "keras": tf.keras.__version__, "numpy": np.__version__,
                      "initial_weights_identical_within_seed": True, "stage": "clip_pilot_only", "final_test_inference": False}
            base.dump(run / "config.json", config)
            options = tf.data.Options(); options.threading.private_threadpool_size = 1
            ds_train = tf.data.Dataset.from_tensor_slices((a["x_train"], a[f"y{width}"])).shuffle(221, seed=seed).batch(16).with_options(options)
            ds_val = tf.data.Dataset.from_tensor_slices((a["x_validation"], a["y_validation"])).batch(16).with_options(options)
            print(f"BEGIN {run_id} width={width} seed={seed}", flush=True)
            history = model.fit(ds_train, validation_data=ds_val, epochs=100, verbose=2, shuffle=False, callbacks=[
                tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=12, restore_best_weights=True),
                tf.keras.callbacks.CSVLogger(str(run / "history.csv")),
                tf.keras.callbacks.ModelCheckpoint(str(run / "best.keras"), monitor="val_loss", save_best_only=True)])
            model.save(run / "model.keras")
            scores = model(a["x_validation"], training=False).numpy()
            np.save(run / "validation-scores.npy", scores)
            reload = tf.keras.models.load_model(run / "model.keras")
            np.testing.assert_allclose(scores, reload(a["x_validation"], training=False).numpy(), rtol=1e-6, atol=1e-6)
            result = evaluate(manifest, meta, scores)
            result.update(run_id=run_id, width_ms=width, seed=seed, end_kst=now(), stage="clip_pilot_only",
                          epochs=len(history.history["loss"]), best_epoch=int(np.argmin(history.history["val_loss"]))+1,
                          best_val_loss=float(min(history.history["val_loss"])), saved_model_predictions_verified=True)
            base.dump(run / "results.json", result)
            dest = DOC / run_id; dest.mkdir(parents=True)
            for name in ("config.json", "results.json", "history.csv", "environment.txt"):
                shutil.copy2(run / name, dest / name)
            with (dest / "validation-predictions.csv").open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f); writer.writerow(["source_path", "timestamp_ms", "canonical_target", "predicted", *base.CLASSES])
                for m, p in zip(meta, scores):
                    writer.writerow([m["source_path"], m["timestamp_ms"], base.CLASSES[m["target"]], base.CLASSES[int(p.argmax())], *p.tolist()])
            print(f"END {run_id}: {result['event_totals']}", flush=True)


def summarize():
    runs = [json.loads((DOC / f"BLE-03-r{i:02}/results.json").read_text(encoding="utf-8")) for i in range(1, 7)]
    def metrics(r):
        e = r["event_totals"]
        return {"correct_events": e["correct"], "missed_events": e["missed"],
                "unmatched_emissions": sum(e[k] for k in ("early", "wrong_direction", "duplicate", "late_unmatched", "background_false")),
                "early_emissions": e["early"], "macro_f1": r["class_report"]["macro avg"]["f1-score"],
                "window_accuracy": r["validation_window_accuracy"]}
    paired = []
    for seed in SEEDS:
        a, b = [metrics(next(r for r in runs if r["seed"] == seed and r["width_ms"] == width)) for width in WIDTHS]
        paired.append({"seed": seed, "150ms": a, "300ms": b, "delta300_minus150": {k: b[k]-a[k] for k in a}})
    summary = {}
    for width in WIDTHS:
        selected = [metrics(r) for r in runs if r["width_ms"] == width]
        summary[str(width)] = {k: {"mean": float(np.mean([s[k] for s in selected])),
                                  "min": float(min(s[k] for s in selected)), "max": float(max(s[k] for s in selected))} for k in selected[0]}
    candidate = (summary["300"]["correct_events"]["mean"] > summary["150"]["correct_events"]["mean"]
                 and summary["300"]["unmatched_emissions"]["mean"] <= summary["150"]["unmatched_emissions"]["mean"]
                 and all(p["delta300_minus150"]["correct_events"] >= 0 and p["delta300_minus150"]["unmatched_emissions"] <= 0 for p in paired))
    output = {"experiment": "BLE-03", "stage": "clip_pilot_only", "created_kst": now(),
              "protocol_sha256": base.digest(DOC / "protocol.json"), "paired": paired, "condition_summary": summary,
              "retain_as_pilot_candidate": candidate, "final_label_policy_adopted": False,
              "continuous_validation_completed": False, "final_test_inference": False,
              "limits": "Same eight sensor-annotated validation gestures, not independent 24 gestures. Both policies use an expanded 221-input train pool, unlike BLE-01/02's 144 inputs."}
    base.dump(DOC / "summary.json", output)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true"); group.add_argument("--train", action="store_true"); group.add_argument("--summarize", action="store_true")
    args = parser.parse_args()
    prepare() if args.prepare else train() if args.train else summarize()
