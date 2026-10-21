"""BLE-06: augmentation x depth 2x2 on the BLE-06-cal folds, fixed E.

A: 2-layer, no aug | B: 2-layer, aug | C: 3-layer, no aug | D: 3-layer, aug.
Commands: --prepare (freeze protocol), --train, --summarize.
Augmentation is applied to training sources only; every variant inherits its parent fold.
Per-window scores at the fixed E are saved so BLE-07a can replay post-processing.
"""

import argparse
import json
import shutil
import sys
import tempfile

import baseline as base
import experiment6_cal as cal
import numpy as np

ROOT = base.ROOT
DOC = ROOT / "docs/experiments/ble-v1/results/BLE-06"
RUNS = ROOT / "ml/runs/BLE-06"
CONDITIONS = {"A": (2, False), "B": (2, True), "C": (3, False), "D": (3, True)}
ROTATION_DEG, ACC_STD, GYRO_STD, VARIANTS = 5.0, 0.02, 0.2, 4


def rotation(rng):
    axis = rng.normal(size=3)
    axis /= np.linalg.norm(axis)
    a = np.deg2rad(rng.uniform(-ROTATION_DEG, ROTATION_DEG))
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(a) * k + (1 - np.cos(a)) * (k @ k)


def variants(raw, source_index):
    """4 variants of a raw source: one rigid rotation per variant + clipped Gaussian noise."""
    out = []
    for v in range(VARIANTS):
        rng = np.random.default_rng([base.SEED, source_index, v])
        r = rotation(rng)
        y = np.concatenate([raw[:, :3] @ r.T, raw[:, 3:] @ r.T], axis=1)
        for cols, std in ((slice(0, 3), ACC_STD), (slice(3, 6), GYRO_STD)):
            y[:, cols] += np.clip(rng.normal(0, std, y[:, cols].shape), -3 * std, 3 * std)
        out.append(y)
    return out


def windows_raw(record, ts, raw, mean, std):
    ends = np.arange(159, len(raw), 5)
    x = np.stack([raw[i - 159:i + 1] for i in ends])
    y = np.zeros(len(ends), dtype=np.int64)
    e = record["completion_ms"]
    if e is not None:
        y[(ts[ends] >= e) & (ts[ends] < e + 150)] = base.CLASSES.index(record["direction"])
        groups = ["pre_start" if t < 500 else "in_progress" if t < e else "post_completion" for t in ts[ends]]
    else:
        groups = [record["source_path"].split("/")[-1].split(".")[0]] * len(ends)
    meta = [{"source_path": record["source_path"], "timestamp_ms": int(ts[i]), "target": int(l), "none_group": g}
            for i, l, g in zip(ends, y, groups)]
    return ((x - mean) / std).astype(np.float32), y, meta


def fold_data(manifest, folds, k, augment):
    direction, train_bg, val_bg = cal.pools(manifest)
    held = set(folds["folds"][k]["validation_direction_sources"])
    train = [r for r in direction if r["source_path"] not in held] + train_bg
    val = [r for r in direction if r["source_path"] in held] + val_bg
    assert {r["source_path"] for r in train}.isdisjoint(r["source_path"] for r in val)
    raws = [base.read_sensor(ROOT / r["source_path"]) for r in train]
    allraw = np.concatenate([v for _, v in raws])
    mean, std = allraw.mean(axis=0), np.maximum(allraw.std(axis=0), 1e-6)  # original sources only
    xs, ys, metas = [], [], []
    for i, (r, (ts, raw)) in enumerate(zip(train, raws)):
        versions = [raw] + (variants(raw, i) if augment and r["direction"] != "NONE" else [])
        for v, data in enumerate(versions):
            x, y, m = windows_raw(r, ts, data, mean, std)
            xs.append(x); ys.append(y)
            metas += [dict(mm, source_path=f'{mm["source_path"]}#v{v}') for mm in m]
    x, y = np.concatenate(xs), np.concatenate(ys)
    idx = base.choose_training(y, metas)
    val_chunks = [(r, *base.windows(r, mean, std)) for r in val]
    return {"x_train": x[idx], "y_train": y[idx], "val": val_chunks,
            "train_counts": np.bincount(y[idx], minlength=5).tolist()}


def build(depth):
    from tensorflow import keras
    L = keras.layers
    if depth == 2:
        from model import build_model
        return build_model(160)
    return keras.Sequential([
        L.Input(shape=(160, 6)), L.Conv1D(16, 5, padding="same", activation="relu"), L.MaxPooling1D(2), L.Dropout(.2),
        L.Conv1D(32, 5, padding="same", activation="relu"), L.MaxPooling1D(2), L.Dropout(.25),
        L.Conv1D(32, 3, padding="same", activation="relu"), L.MaxPooling1D(2),
        L.Flatten(), L.Dropout(.3), L.Dense(5, activation="softmax")], name="ringpilot_cnn_3layer")


def prepare():
    if (DOC / "protocol.json").exists():
        raise FileExistsError("Protocol already frozen")
    summary = json.loads((cal.DOC / "summary.json").read_text(encoding="utf-8"))
    E = summary["chosen_E"]
    protocol = {"experiment": "BLE-06", "created_before_training_kst": cal.now(), "E": E,
                "calibration_summary_sha256": base.digest(cal.DOC / "summary.json"),
                "folds_sha256": base.digest(cal.FOLDS), "manifest_sha256": base.digest(base.MANIFEST),
                "seeds": cal.SEEDS, "conditions": {k: {"depth": d, "augmentation": a} for k, (d, a) in CONDITIONS.items()},
                "depth3": "Conv16k5-Pool2-Drop.2 -> Conv32k5-Pool2-Drop.25 -> Conv32k3-Pool2 -> Flatten(640) -> Drop.3 -> Dense5 (no hidden Dense)",
                "augmentation": {"variants_per_training_source": VARIANTS, "scope": "direction training sources only (not background, not validation)",
                                 "rigid_rotation_deg": f"uniform +-{ROTATION_DEG}, random axis, one per variant, applied to acc and gyro",
                                 "noise_std": {"acc": ACC_STD, "gyro": GYRO_STD}, "noise_clip": "3 sigma",
                                 "normalization": "mean/std from original (unaugmented) training sources of the fold",
                                 "none_selection": "baseline.choose_training over all training windows (matches positive count)"},
                "caveat": "augmentation raises the number of positive windows and hence the selected NONE count; steps per epoch differ across conditions at the same E",
                "judgement": {"pairing": "each of B, C, D versus A, same seed and folds",
                              "metrics": "per-seed sum over folds of correct events and unmatched emissions",
                              "candidate": "mean correct delta >= +2 AND correct delta > 0 in >=4 of 5 seeds AND mean unmatched delta <= 0",
                              "worse": "mean correct delta <= -2 AND correct delta < 0 in >=4 of 5 seeds AND mean unmatched delta >= 0",
                              "otherwise": "undecidable (keep A)",
                              "margin_basis": "+-2 events is about one seed-spread sd of A at E=10 (range 13~19 in calibration)"},
                "final_test_inference": False}
    base.dump(DOC / "protocol.json", protocol)
    print(json.dumps(protocol["judgement"], ensure_ascii=False))


def train():
    import tensorflow as tf
    manifest = cal.load_manifest()
    protocol = json.loads((DOC / "protocol.json").read_text(encoding="utf-8"))
    folds = json.loads(cal.FOLDS.read_text(encoding="utf-8"))
    assert protocol["folds_sha256"] == base.digest(cal.FOLDS)
    E = protocol["E"]
    if RUNS.exists():
        raise FileExistsError("Refusing to overwrite BLE-06 runs")
    RUNS.mkdir(parents=True); (RUNS / "tmp").mkdir(); tempfile.tempdir = str(RUNS / "tmp")
    for f in ("baseline.py", "experiment6_cal.py", "experiment6.py", "model.py"):
        shutil.copy2(ROOT / "ml" / f, RUNS / f)
    tf.config.threading.set_intra_op_parallelism_threads(1)
    tf.config.threading.set_inter_op_parallelism_threads(1)
    tf.config.experimental.enable_op_determinism()
    options = tf.data.Options(); options.threading.private_threadpool_size = 1
    cache, results = {}, []
    for name, (depth, aug) in CONDITIONS.items():
        for k in range(cal.N_FOLDS):
            cache[(aug, k)] = cache.get((aug, k)) or fold_data(manifest, folds, k, aug)
    for name, (depth, aug) in CONDITIONS.items():
        for seed in cal.SEEDS:
            for k in range(cal.N_FOLDS):
                d = cache[(aug, k)]
                x_val = np.concatenate([c[1] for c in d["val"]])
                tf.keras.backend.clear_session(); tf.keras.utils.set_random_seed(seed)
                model = build(depth)
                model.compile(optimizer=tf.keras.optimizers.Adam(.001), loss="sparse_categorical_crossentropy")
                ds = tf.data.Dataset.from_tensor_slices((d["x_train"], d["y_train"])).shuffle(len(d["y_train"]), seed=seed).batch(16).with_options(options)
                hist = model.fit(ds, epochs=E, verbose=0, shuffle=False)
                scores = model(x_val, training=False).numpy()
                np.save(RUNS / f"scores-{name}-s{seed}-f{k}.npy", scores)
                totals, per_source = cal.score_events(d["val"], scores)
                results.append({"condition": name, "seed": seed, "fold": k, "params": model.count_params(),
                                "train_windows": len(d["y_train"]), "train_loss": float(hist.history["loss"][-1]),
                                "event_totals": totals, "per_source": per_source})
                print(f"{name} seed={seed} fold={k} windows={len(d['y_train'])} {totals}", flush=True)
    base.dump(RUNS / "results.json", {"created_kst": cal.now(), "python": sys.version, "tensorflow": tf.__version__,
                                      "E": E, "results": results, "final_test_inference": False})
    shutil.copy2(RUNS / "results.json", DOC / "results.json")


def per_seed(results, name):
    rows = {}
    for seed in cal.SEEDS:
        sel = [r for r in results if r["condition"] == name and r["seed"] == seed]
        assert len(sel) == cal.N_FOLDS
        t = lambda key: sum(r["event_totals"].get(key, 0) for r in sel)
        rows[seed] = {"correct": t("correct"), "unmatched": sum(t(u) for u in cal.UNMATCHED), "early": t("early")}
    return rows


def summarize():
    protocol = json.loads((DOC / "protocol.json").read_text(encoding="utf-8"))
    results = json.loads((DOC / "results.json").read_text(encoding="utf-8"))["results"]
    rows = {n: per_seed(results, n) for n in CONDITIONS}
    out = {"experiment": "BLE-06", "E": protocol["E"], "per_seed": rows, "verdict": {}, "mean": {}}
    for n, r in rows.items():
        out["mean"][n] = {k: float(np.mean([v[k] for v in r.values()])) for k in ("correct", "unmatched", "early")}
    for n in "BCD":
        dc = [rows[n][s]["correct"] - rows["A"][s]["correct"] for s in cal.SEEDS]
        du = [rows[n][s]["unmatched"] - rows["A"][s]["unmatched"] for s in cal.SEEDS]
        mc, mu = float(np.mean(dc)), float(np.mean(du))
        up, down = sum(x > 0 for x in dc), sum(x < 0 for x in dc)
        verdict = "candidate" if mc >= 2 and up >= 4 and mu <= 0 else "worse" if mc <= -2 and down >= 4 and mu >= 0 else "undecidable"
        out["verdict"][n] = {"mean_delta_correct": mc, "delta_correct_by_seed": dc, "mean_delta_unmatched": mu,
                             "delta_unmatched_by_seed": du, "seeds_up": up, "seeds_down": down, "verdict": verdict}
    cands = [n for n in "BCD" if out["verdict"][n]["verdict"] == "candidate"]
    out["selected"] = max(cands, key=lambda n: out["mean"][n]["correct"] - out["mean"][n]["unmatched"]) if cands else "A"
    base.dump(DOC / "summary.json", out)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    p = argparse.ArgumentParser(); g = p.add_mutually_exclusive_group(required=True)
    for name in ("prepare", "train", "summarize"):
        g.add_argument(f"--{name}", action="store_true")
    a = p.parse_args()
    prepare() if a.prepare else train() if a.train else summarize()
