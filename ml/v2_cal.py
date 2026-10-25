"""BLE v2 보정: 학습용 안의 교차검증으로 고정 epoch E를 고른다. 평가용은 열지 않는다.

사용 (ml/.venv/Scripts/python.exe ml/v2_cal.py <명령> --split <분할>):
  init       실행 설정(config.json) 저장. protocol이 먼저 있어야 한다
  run        seed 하나를 모든 fold에서 학습하고 결과를 seed-<seed>.json에 저장
  run-all    seed 5개를 병렬 프로세스로 run
  summarize  seed 결과를 합쳐 E별 점수와 선택된 E를 summary.json에 저장

계획: docs/TrainingPlan.md "BLE v2 실험" 절차 3. (seed, fold)마다 60 epoch까지 한 번 학습하고
후보 epoch가 끝난 시점마다 검증 fold를 replay한다. Adam 학습률이 고정이라 E epoch에서 멈춘
별도 학습과 같은 가중치다(test_v2_cal.py가 확인).
"""

import argparse
import importlib.metadata
import json
import platform
import subprocess
import sys
import time

import numpy as np

import v2
from v2 import DOC, ROOT, digest, dump, now

RUNS = ROOT / "ml/runs"
CODE_FILES = ("v2.py", "v2_cal.py", "model.py")
EARLY_NEAR_MS = 100


def run_id(split):
    return f"V2-{split}-cal"


def results_dir(split):
    return DOC / "results" / run_id(split)


def scores_dir(split):
    return RUNS / run_id(split)


def code_hashes():
    return {f: digest(ROOT / "ml" / f) for f in CODE_FILES}


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


# ---------------------------------------------------------------- init

def init(split_name):
    protocol_path = DOC / "results/protocol.json"
    if not protocol_path.exists():
        raise FileNotFoundError("protocol.json이 먼저 있어야 한다(python ml/v2.py protocol)")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    out = results_dir(split_name)
    if (out / "config.json").exists():
        raise FileExistsError(f"{out}/config.json이 이미 있다. 덮어쓰지 않는다")
    v2.verify()
    data, by_path = v2.load_records()
    split = v2.load_split(split_name)
    assert protocol["split_sha256"][split_name] == digest(v2.SPLITS / f"v2-{split_name}.json"), "protocol과 분할이 다르다"
    assert protocol["records_sha256"] == digest(v2.RECORDS), "protocol과 records가 다르다"
    folds = []
    for k in range(split["cv"]["n_folds"]):
        d = v2.fold_sets(by_path, split, k)
        folds.append({"fold": k, "held_out_session": split["cv"]["folds"][k].get("held_out_session"),
                      "train_sources": d["train_sources"], "validation_sources": d["val_sources"],
                      "train_windows_all": d["train_all_counts"], "train_windows_selected": d["train_counts"],
                      "train_none_groups": d["train_none_groups"],
                      "validation_windows": int(sum(len(c[2]) for c in d["val"])),
                      "normalization": {"axes": v2.AXES, "mean": d["mean"].tolist(), "std": d["std"].tolist(), "ddof": 0}})
    versions = {n: importlib.metadata.version(n) for n in ("tensorflow", "keras", "numpy")}
    config = {"run_id": run_id(split_name), "created_kst": now(), "split": split_name,
              "split_sha256": digest(v2.SPLITS / f"v2-{split_name}.json"), "records_sha256": digest(v2.RECORDS),
              "protocol_sha256": digest(protocol_path), "seeds": v2.SEEDS, "epoch_candidates": v2.EPOCH_CANDIDATES,
              "max_epoch": max(v2.EPOCH_CANDIDATES), "n_folds": len(folds),
              "python": sys.version, "platform": platform.platform(), **versions,
              "code_sha256": code_hashes(), "git_head": git("rev-parse", "HEAD"),
              "git_status_short": git("status", "--short").splitlines(),
              "folds": folds, "eval_sources_opened": False}
    dump(out / "config.json", config)
    (out / "environment.txt").write_text(
        "\n".join(sorted(f'{d.metadata["Name"]}=={d.version}' for d in importlib.metadata.distributions())) + "\n",
        encoding="utf-8", newline="\n")
    print("init", out, "folds", [(f["fold"], f["train_sources"], f["validation_sources"]) for f in folds])


# ---------------------------------------------------------------- run

def val_loss(scores, labels):
    p = np.clip(scores[np.arange(len(labels)), labels], 1e-7, 1.0)
    return float(-np.log(p).mean())


def run_seed(split_name, seed, out_dir, score_dir, folds=None, epochs=v2.EPOCH_CANDIDATES, log=print):
    """seed 하나를 모든 fold에서 학습·재생한다. 결과는 dict로 돌려주고 점수 배열은 score_dir에 둔다."""
    data, by_path = v2.load_records()
    split = v2.load_split(split_name)
    score_dir.mkdir(parents=True, exist_ok=True)
    result = {"seed": seed, "split": split_name, "epochs": list(epochs), "folds": []}
    t_start = time.time()
    for k in (range(split["cv"]["n_folds"]) if folds is None else folds):
        t0 = time.time()
        d = v2.fold_sets(by_path, split, k)
        x_val = np.concatenate([c[1] for c in d["val"]])
        y_val = np.concatenate([c[2] for c in d["val"]])
        meta = sum([c[3] for c in d["val"]], [])
        scores, train_loss = v2.fit_snapshots(d["x_train"], d["y_train"], x_val, seed, tuple(epochs))
        np.savez_compressed(score_dir / f"seed-{seed}-fold-{k}-scores.npz", **{f"e{e}": scores[e].astype(np.float32) for e in epochs})
        dump(score_dir / f"seed-{seed}-fold-{k}-windows.json",
             [{"source_path": m["source_path"], "timestamp_ms": m["timestamp_ms"], "target": m["target"]} for m in meta])
        per_epoch = {}
        for e in epochs:
            totals, per_source = v2.score_events(d["val"], scores[e])
            by_src = {r["source_path"]: r for r, *_ in d["val"]}
            for p in per_source:
                r = by_src[p["source_path"]]
                p.update(completion_ms=r["completion_ms"], direction=r["direction"], rows=r["rows"], session=r["session"])
            predicted = scores[e].argmax(axis=1)
            per_epoch[str(e)] = {"event_totals": totals, "per_source": per_source,
                                 "val_loss": val_loss(scores[e], y_val), "window_accuracy": float((predicted == y_val).mean()),
                                 "train_loss": float(train_loss[e - 1])}
        result["folds"].append({"fold": k, "held_out_session": split["cv"]["folds"][k].get("held_out_session"),
                                "train_loss_by_epoch": [float(v) for v in train_loss], "per_epoch": per_epoch,
                                "seconds": round(time.time() - t0, 1)})
        log(f"seed {seed} fold {k}: {round(time.time() - t0, 1)}s " +
            " ".join(f"E{e}={per_epoch[str(e)]['event_totals'].get('correct', 0)}" for e in epochs))
    result["seconds"] = round(time.time() - t_start, 1)
    return result


def cmd_run(split_name, seed):
    out = results_dir(split_name)
    config = json.loads((out / "config.json").read_text(encoding="utf-8"))
    assert seed in config["seeds"], seed
    assert config["code_sha256"] == code_hashes(), "init 이후 코드가 바뀌었다. 새 실행으로 다시 init해야 한다"
    assert config["split_sha256"] == digest(v2.SPLITS / f"v2-{split_name}.json")
    target = out / f"seed-{seed}.json"
    if target.exists():
        raise FileExistsError(f"{target}가 이미 있다. 덮어쓰지 않는다")
    result = run_seed(split_name, seed, out, scores_dir(split_name))
    dump(target, result)
    print("saved", target, f"{result['seconds']}s")


def cmd_run_all(split_name, parallel):
    out = results_dir(split_name)
    config = json.loads((out / "config.json").read_text(encoding="utf-8"))
    pending = [s for s in config["seeds"] if not (out / f"seed-{s}.json").exists()]
    print("pending seeds:", pending)
    procs = []
    for s in pending:
        log = open(out / f"seed-{s}.log", "w", encoding="utf-8")
        procs.append((s, subprocess.Popen([sys.executable, str(ROOT / "ml/v2_cal.py"), "run", "--split", split_name, "--seed", str(s)],
                                          cwd=ROOT, stdout=log, stderr=subprocess.STDOUT), log))
        while sum(p.poll() is None for _, p, _ in procs) >= parallel:
            time.sleep(2)
    failed = []
    for s, p, log in procs:
        code = p.wait()
        log.close()
        if code:
            failed.append(s)
    print("failed seeds:", failed or "none")
    if failed:
        sys.exit(1)


# ---------------------------------------------------------------- summarize

def percentile95(values):
    return float(np.percentile(values, 95)) if values else None


def mean_or_none(values):
    values = [v for v in values if v is not None]
    return float(np.mean(values)) if values else None


def summarize_seed_epoch(folds, epoch):
    """seed 하나, E 하나: 모든 fold의 per_source를 합쳐 점수와 상세 집계를 낸다."""
    per_source = [p for f in folds for p in f["per_epoch"][str(epoch)]["per_source"]]
    score, correct, unmatched, n_direction = v2.selection_score(per_source)
    kinds = {k: sum(p["counts"].get(k, 0) for p in per_source) for k in
             ("correct", "missed", "wrong_direction", "duplicate", "early", "late_unmatched", "background_false")}
    delays = [d for p in per_source for d in p["delays_ms"]]
    early_near = sum(1 for p in per_source if p["completion_ms"] is not None
                     for ev in p["events"] if ev["kind"] == "early" and p["completion_ms"] - ev["timestamp_ms"] <= EARLY_NEAR_MS)
    background = [p for p in per_source if not p["source_path"].rsplit("/", 1)[-1].startswith("raw_")]
    exposure_s = sum((p["rows"] * 10 - v2.FIRST_T) / 1000 for p in background)
    clipped = [p["source_path"] for p in per_source
               if p["completion_ms"] is not None and p["completion_ms"] + v2.MATCH_MS > v2.LAST_T]
    return {"score": score, "correct": correct, "unmatched": unmatched, "direction_sources": n_direction, "kinds": kinds,
            "background_exposure_s": exposure_s,
            "background_false_per_min": kinds["background_false"] / (exposure_s / 60) if exposure_s else None,
            "early_within_100ms": early_near, "delay_ms": {"n": len(delays), "median": float(np.median(delays)) if delays else None,
                                                           "p95": percentile95(delays)},
            "match_horizon_clipped_sources": clipped,
            "val_loss_mean_over_folds": float(np.mean([f["per_epoch"][str(epoch)]["val_loss"] for f in folds])),
            "window_accuracy_mean_over_folds": float(np.mean([f["per_epoch"][str(epoch)]["window_accuracy"] for f in folds]))}


def summarize_dir(seed_results, epochs=v2.EPOCH_CANDIDATES):
    """seed별 결과(dict 목록)를 합친다. 선택 규칙: 5 seed 점수 평균 최대, 동점이면 작은 E."""
    table = {}
    for e in epochs:
        per_seed = {r["seed"]: summarize_seed_epoch(r["folds"], e) for r in seed_results}
        scores = [v["score"] for v in per_seed.values()]
        table[e] = {"mean_score": float(np.mean(scores)), "score_min": float(min(scores)), "score_max": float(max(scores)),
                    "mean_correct": float(np.mean([v["correct"] for v in per_seed.values()])),
                    "mean_unmatched": float(np.mean([v["unmatched"] for v in per_seed.values()])),
                    "mean_background_false_per_min": mean_or_none([v["background_false_per_min"] for v in per_seed.values()]),
                    "mean_val_loss": float(np.mean([v["val_loss_mean_over_folds"] for v in per_seed.values()])),
                    "per_seed": {str(s): v for s, v in per_seed.items()}}
    best = max(round(t["mean_score"], 12) for t in table.values())
    chosen = min(e for e in epochs if round(table[e]["mean_score"], 12) == best)
    tied = [e for e in epochs if round(table[e]["mean_score"], 12) == best]
    return {"per_epoch": {str(e): t for e, t in table.items()}, "chosen_E": chosen, "tied_epochs": tied}


def cmd_summarize(split_name):
    out = results_dir(split_name)
    config = json.loads((out / "config.json").read_text(encoding="utf-8"))
    seed_results = []
    for s in config["seeds"]:
        path = out / f"seed-{s}.json"
        if not path.exists():
            raise FileNotFoundError(f"{path}가 없다. 5 seed가 모두 끝나야 요약한다")
        seed_results.append(json.loads(path.read_text(encoding="utf-8")))
    summary = summarize_dir(seed_results, tuple(config["epoch_candidates"]))
    chosen = str(summary["chosen_E"])
    per_fold = {}
    for fold in range(config["n_folds"]):
        per_fold[str(fold)] = {str(r["seed"]): v2.selection_score(
            r["folds"][fold]["per_epoch"][chosen]["per_source"])[:3] for r in seed_results}
    summary.update(run_id=config["run_id"], created_kst=now(), split=split_name, protocol_sha256=config["protocol_sha256"],
                   config_sha256=digest(out / "config.json"),
                   selection_rule="5 seed 점수 평균이 가장 큰 E, 같으면 작은 E. 점수=(정검출−방향 원본 미매칭)÷방향 원본 수, seed마다 모든 fold 합산, 배경 오발행 제외",
                   per_fold_at_chosen_E_score_correct_unmatched=per_fold, eval_sources_opened=False)
    dump(out / "summary.json", summary)
    print(f"{run_id(split_name)}: chosen E = {summary['chosen_E']} (동점 후보 {summary['tied_epochs']})")
    print(f"{'E':>4} {'mean score':>11} {'min':>8} {'max':>8} {'correct':>8} {'unmatched':>10} {'bg/min':>7} {'val_loss':>9}")
    for e in tuple(config["epoch_candidates"]):
        t = summary["per_epoch"][str(e)]
        bg = t["mean_background_false_per_min"]
        print(f"{e:>4} {t['mean_score']:>11.4f} {t['score_min']:>8.4f} {t['score_max']:>8.4f} {t['mean_correct']:>8.1f} "
              f"{t['mean_unmatched']:>10.1f} {'-' if bg is None else format(bg, '.2f'):>7} {t['mean_val_loss']:>9.4f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=("init", "run", "run-all", "summarize"))
    p.add_argument("--split", required=True, choices=v2.SPLIT_NAMES)
    p.add_argument("--seed", type=int)
    p.add_argument("--parallel", type=int, default=5)
    a = p.parse_args()
    if a.command == "init":
        init(a.split)
    elif a.command == "run":
        if a.seed is None:
            p.error("--seed가 필요하다")
        cmd_run(a.split, a.seed)
    elif a.command == "run-all":
        cmd_run_all(a.split, a.parallel)
    else:
        cmd_summarize(a.split)
