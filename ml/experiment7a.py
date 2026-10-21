"""BLE-07a: post-processing search on clip replay of the BLE-06 CV predictions.

Clip result only (35 direction gestures + 20 s validation background per fold); not continuous use.
Commands: --prepare (freeze grid and rule), --run.
"""

import argparse
from itertools import product
import json

import baseline as base
import experiment6 as e6
import experiment6_cal as cal
import numpy as np

ROOT = base.ROOT
DOC = ROOT / "docs/experiments/ble-v1/results/BLE-07a"
GRID = {"threshold": (.6, .7, .8, .9), "margin": (.1, .2, .3), "consecutive": (1, 2, 3), "rearm": (1, 2, 3)}
DEFAULT = {"threshold": .8, "margin": .2, "consecutive": 2, "rearm": 2}


def issue(times, scores, threshold, margin, consecutive, rearm):
    events, locked, cand, count, nones = [], False, None, 0, 0
    for t, p in zip(times, scores):
        top = int(np.argmax(p))
        if locked:
            nones = nones + 1 if top == 0 and p[0] >= threshold else 0
            if nones >= rearm:
                locked, cand, count, nones = False, None, 0, 0
            continue
        s = np.sort(p)
        if top != 0 and p[top] >= threshold and s[-1] - s[-2] >= margin:
            count = count + 1 if top == cand else 1
            cand = top
            if count >= consecutive:
                events.append({"timestamp_ms": int(t), "class_index": top, "score": float(p[top])})
                locked, cand, count, nones = True, None, 0, 0
        else:
            cand, count = None, 0
    return events


def evaluate(cond, chunks, params):
    rows = {}
    for seed in cal.SEEDS:
        c = u = early = 0
        for k in range(cal.N_FOLDS):
            scores = np.load(e6.RUNS / f"scores-{cond}-s{seed}-f{k}.npy")
            off = 0
            for r, _, labels, meta in chunks[k]:
                n = len(labels)
                ev = issue([m["timestamp_ms"] for m in meta], scores[off:off + n], **params)
                counts, _, _ = base.classify_events(r, ev)
                c += counts["correct"]; early += counts["early"]
                u += sum(counts[x] for x in cal.UNMATCHED)
                off += n
        rows[seed] = (c, u, early)
    return {"mean_correct": float(np.mean([v[0] for v in rows.values()])),
            "mean_unmatched": float(np.mean([v[1] for v in rows.values()])),
            "mean_early": float(np.mean([v[2] for v in rows.values()])),
            "correct_range": [min(v[0] for v in rows.values()), max(v[0] for v in rows.values())],
            "mean_score": float(np.mean([v[0] - v[1] for v in rows.values()]))}


def distance(params):
    return sum(GRID[k].index(params[k]) != GRID[k].index(DEFAULT[k]) for k in GRID)


def prepare():
    if (DOC / "protocol.json").exists():
        raise FileExistsError("Protocol already frozen")
    base.dump(DOC / "protocol.json", {
        "experiment": "BLE-07a", "created_before_search_kst": cal.now(), "grid": GRID, "default": DEFAULT,
        "inputs": "BLE-06 saved per-window scores at fixed E for conditions A-D, 5 seeds x 5 folds",
        "selection_rule": "maximise mean over seeds of (correct - unmatched emissions); ties go to the setting closer to the default (fewer changed parameters), then the lower grid index",
        "comparison": "path 1 = tune on A; path 2 = tune on the BLE-06 selected condition; all four are also tuned for reference",
        "limits": ["search and evaluation use the same CV predictions, so tuned scores are optimistic",
                   "clip replay only; no continuous data", "background is 20 s per fold, same clips every fold"],
        "final_test_inference": False})


def run():
    protocol = json.loads((DOC / "protocol.json").read_text(encoding="utf-8"))
    manifest = cal.load_manifest()
    folds = json.loads(cal.FOLDS.read_text(encoding="utf-8"))
    chunks = {k: e6.fold_data(manifest, folds, k, False)["val"] for k in range(cal.N_FOLDS)}
    selected = json.loads((e6.DOC / "summary.json").read_text(encoding="utf-8"))["selected"]
    out = {"experiment": "BLE-07a", "protocol_sha256": base.digest(DOC / "protocol.json"), "ble06_selected": selected, "conditions": {}}
    keys = list(GRID)
    for cond in "ABCD":
        results = []
        for values in product(*GRID.values()):
            params = dict(zip(keys, values))
            results.append({"params": params, **evaluate(cond, chunks, params)})
        best_score = max(r["mean_score"] for r in results)
        best = min((r for r in results if r["mean_score"] == best_score), key=lambda r: (distance(r["params"]), [GRID[k].index(r["params"][k]) for k in keys]))
        default = next(r for r in results if r["params"] == DEFAULT)
        out["conditions"][cond] = {"default": default, "best": best, "top5": sorted(results, key=lambda r: -r["mean_score"])[:5]}
        print(cond, "default", default["mean_score"], default["mean_correct"], default["mean_unmatched"], "best", best["params"], best["mean_score"], best["mean_correct"], best["mean_unmatched"], flush=True)
    base.dump(DOC / "summary.json", out)


if __name__ == "__main__":
    p = argparse.ArgumentParser(); g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--prepare", action="store_true"); g.add_argument("--run", action="store_true")
    a = p.parse_args()
    prepare() if a.prepare else run()
