"""NONE 배분 비교 전용 실행기. 기존 v2/실행기/결과를 변경하지 않는다.

init-all / run-all / run / verify-all, --protocol PATH. 기준선과 같은 fit_snapshots와
발행·채점을 사용하며, 학습 NONE의 세션·클립 배분만 바꾼다.
"""
import argparse
import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

import v2
import v2_cal
import v2_none_stratified as balanced
import v2_protocol
import v2_protected_manifest as protected

RUNNER_VERSION = 3


def read(path):
    return v2_protocol.read(path)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def protocol_issues(p):
    issues = v2_protocol.input_issues(p)
    if p["spec"].get("strategy") != balanced.STRATEGY:
        issues.append("미지원 NONE strategy")
    if p["spec"].get("fixed_condition_policy") != "inherit_baseline_except_none_allocation":
        issues.append("고정 조건 정책이 다르다")
    if p["spec"].get("none_seed") != v2.SEED:
        issues.append("NONE 선택 seed가 바뀌었다")
    if p["epoch_selection"] != v2_protocol.read(v2_protocol.BASELINE_PROTOCOL)["epoch_selection"]:
        issues.append("epoch 선택 조건이 다르다")
    return issues


def paths(protocol_path, p, split):
    prefix = p["spec"]["run_prefix"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", prefix):
        raise ValueError("잘못된 run_prefix")
    run_id = f"{prefix}-{split}"
    return run_id, Path(protocol_path).parent / "results" / run_id, v2.ROOT / "ml/runs" / run_id


def build_fold(by_path, split, k, sampler=balanced.choose_training):
    val_paths = set(split["cv"]["folds"][k]["validation_sources"])
    evaluation = set(split["eval_sources"])
    if not val_paths <= set(split["train_sources"]) or val_paths & evaluation:
        raise ValueError("검증/평가 원본 분할이 다르다")
    train = [by_path[p] for p in split["train_sources"] if p not in val_paths]
    val = [by_path[p] for p in split["train_sources"] if p in val_paths]
    assert not {r["source_path"] for r in train} & (val_paths | evaluation)
    mean, std = v2.normalization(train)
    chunks = v2.make_chunks(train, mean, std)
    x, y = np.concatenate([c[1] for c in chunks]), np.concatenate([c[2] for c in chunks])
    meta = [m for c in chunks for m in c[3]]
    legacy = v2.choose_training(y, meta, v2.SEED)
    idx = sampler(y, meta, v2.SEED)
    old_groups = Counter(meta[i]["none_group"] for i in legacy if y[i] == 0)
    new_groups = Counter(meta[i]["none_group"] for i in idx if y[i] == 0)
    assert old_groups == new_groups
    np.testing.assert_array_equal(legacy[y[legacy] != 0], idx[y[idx] != 0])
    np.testing.assert_array_equal(np.bincount(y[legacy], minlength=5), np.bincount(y[idx], minlength=5))
    return {
        "x_train": x[idx], "y_train": y[idx], "mean": mean, "std": std,
        "train_all_counts": np.bincount(y, minlength=5).tolist(),
        "train_counts": np.bincount(y[idx], minlength=5).tolist(),
        "train_none_groups": dict(new_groups), "selected_meta": [meta[i] for i in idx],
        "val": v2.make_chunks(val, mean, std), "train_sources": len(train), "val_sources": len(val),
    }


def selection_manifest(d, by_path):
    sessions = defaultdict(Counter)
    clips = defaultdict(Counter)
    for m in d["selected_meta"]:
        if m["target"] == 0:
            sessions[m["none_group"]][by_path[m["source_path"]]["session"]] += 1
            clips[m["none_group"]][m["source_path"]] += 1
    return {"selected_windows": d["selected_meta"], "selection_sha256": fingerprint(d["selected_meta"]),
            "kind_session_counts": {k: dict(v) for k, v in sessions.items()},
            "kind_clip_counts": {k: dict(v) for k, v in clips.items()}}


def init_all(protocol_path):
    p = read(protocol_path)
    v2_cal.raise_issues("protocol 불일치", protocol_issues(p))
    v2.verify()
    _, records = v2.load_records()
    for split_name in p["spec"]["execution_order"]:
        run_id, out, _ = paths(protocol_path, p, split_name)
        if (out / "config.json").exists():
            raise FileExistsError(out / "config.json")
        split = v2.load_split(split_name)
        old_cfg = read(v2.DOC / "results" / f"V2-{split_name}-cal/config.json")
        fold_configs = []
        for k in range(split["cv"]["n_folds"]):
            d = build_fold(records, split, k)
            old = old_cfg["folds"][k]
            assert d["train_counts"] == old["train_windows_selected"]
            assert d["train_all_counts"] == old["train_windows_all"]
            assert d["train_none_groups"] == old["train_none_groups"]
            np.testing.assert_allclose(d["mean"], old["normalization"]["mean"], rtol=0, atol=0)
            np.testing.assert_allclose(d["std"], old["normalization"]["std"], rtol=0, atol=0)
            manifest = selection_manifest(d, records)
            manifest_path = out / f"fold-{k}-training.json"
            protected.write_new(manifest_path, manifest)
            fold_configs.append({"fold": k, "selection_sha256": manifest["selection_sha256"],
                                 "manifest_sha256": v2.digest(manifest_path),
                                 "normalization": old["normalization"],
                                 "train_windows_selected": d["train_counts"], "train_none_groups": d["train_none_groups"],
                                 "kind_session_counts": manifest["kind_session_counts"]})
        cfg = {"run_id": run_id, "runner_version": RUNNER_VERSION, "split": split_name,
               "created_kst": v2.now(), "protocol_path": str(Path(protocol_path).resolve()),
               "protocol_sha256": v2.digest(protocol_path), "code_sha256": p["code_sha256"],
               "records_sha256": p["records_sha256"], "split_sha256": p["split_sha256"][split_name],
               "seeds": list(v2.SEEDS), "epoch_candidates": list(v2.EPOCH_CANDIDATES),
               "n_folds": len(fold_configs), "folds": fold_configs,
               "git_head": v2_cal.git("rev-parse", "HEAD"), "git_status_short": v2_cal.git("status", "--short").splitlines(),
               "python": sys.version, "versions": {n: importlib.metadata.version(n) for n in ("tensorflow", "keras", "numpy")},
               "data_role": "development_diagnostic", "eval_in_model_inputs": False}
        protected.write_new(out / "config.json", cfg)
        protected.write_new(out / "environment.json", {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()})
        print("init", run_id, "folds", len(fold_configs), flush=True)


def load_state(protocol_path, split_name):
    p = read(protocol_path)
    v2_cal.raise_issues("protocol과 현재 입력이 다르다", protocol_issues(p))
    run_id, out, scores = paths(protocol_path, p, split_name)
    cfg = read(out / "config.json")
    if cfg["protocol_sha256"] != v2.digest(protocol_path) or cfg["code_sha256"] != p["code_sha256"]:
        raise ValueError("config와 protocol이 다르다")
    if cfg["split"] != split_name or cfg["runner_version"] != RUNNER_VERSION:
        raise ValueError("config의 분할/실행기 버전이 다르다")
    if cfg["seeds"] != list(v2.SEEDS) or cfg["epoch_candidates"] != list(v2.EPOCH_CANDIDATES):
        raise ValueError("config의 seed/epoch가 다르다")
    for f in cfg["folds"]:
        if f["manifest_sha256"] != v2.digest(out / f"fold-{f['fold']}-training.json"):
            raise ValueError("학습 선택 manifest가 바뀌었다")
    return p, cfg, out, scores


def run_seed(protocol_path, split_name, seed):
    _, cfg, out, score_dir = load_state(protocol_path, split_name)
    if seed not in cfg["seeds"]:
        raise ValueError("config에 없는 seed")
    target = out / f"seed-{seed}.json"
    if target.exists():
        raise FileExistsError(target)
    v2.configure_tf()
    runtime = v2_cal.runtime_info()
    if not v2_cal.runtime_ok(runtime) or runtime["env"]["TF_ENABLE_ONEDNN_OPTS"] != "0":
        raise ValueError(f"학습 전에 실행 조건 불일치: {runtime}")
    _, records = v2.load_records()
    split = v2.load_split(split_name)
    result = {"seed": seed, "split": split_name, "runner_version": RUNNER_VERSION,
              "epochs": cfg["epoch_candidates"], "folds": [], "protocol_sha256": cfg["protocol_sha256"]}
    score_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    for k in range(cfg["n_folds"]):
        t0 = time.monotonic()
        d = build_fold(records, split, k)
        if fingerprint(d["selected_meta"]) != cfg["folds"][k]["selection_sha256"]:
            raise ValueError("init 당시와 학습 창 선택이 다르다")
        x_val = np.concatenate([c[1] for c in d["val"]])
        y_val = np.concatenate([c[2] for c in d["val"]])
        meta = [m for c in d["val"] for m in c[3]]
        snapshots, loss = v2.fit_snapshots(d["x_train"], d["y_train"], x_val, seed, tuple(cfg["epoch_candidates"]))
        score_path = score_dir / f"seed-{seed}-fold-{k}-scores.npz"
        with score_path.open("xb") as stream:
            np.savez_compressed(stream, **{f"e{e}": snapshots[e].astype(np.float32) for e in cfg["epoch_candidates"]})
        protected.write_new(score_dir / f"seed-{seed}-fold-{k}-windows.json", meta)
        per_epoch = {}
        by_path = {c[0]["source_path"]: c[0] for c in d["val"]}
        for e in cfg["epoch_candidates"]:
            totals, per_source = v2.score_events(d["val"], snapshots[e])
            for item in per_source:
                rec = by_path[item["source_path"]]
                item.update(completion_ms=rec["completion_ms"], direction=rec["direction"], rows=rec["rows"], session=rec["session"])
            per_epoch[str(e)] = {"event_totals": totals, "per_source": per_source,
                                 "val_loss": v2_cal.val_loss(snapshots[e], y_val),
                                 "window_accuracy": float((snapshots[e].argmax(axis=1) == y_val).mean()),
                                 "train_loss": float(loss[e - 1])}
        result["folds"].append({"fold": k, "held_out_session": split["cv"]["folds"][k].get("held_out_session"),
                                "train_loss_by_epoch": [float(x) for x in loss], "per_epoch": per_epoch,
                                "seconds": round(time.monotonic() - t0, 2)})
        print(f"{split_name} seed {seed} fold {k}: {time.monotonic() - t0:.1f}s", flush=True)
    result["runtime"] = v2_cal.runtime_info()
    result["seconds"] = round(time.monotonic() - start, 2)
    load_state(protocol_path, split_name)
    if not v2_cal.runtime_ok(result["runtime"]):
        raise ValueError("실행 조건 불일치")
    protected.write_new(target, result)


def verify_run(protocol_path, split_name, save=False):
    _, cfg, out, _ = load_state(protocol_path, split_name)
    results = v2_cal.load_seed_results(out, cfg)
    issues = v2_cal.results_issues(cfg, v2.load_split(split_name), results)
    for r in results:
        if r.get("protocol_sha256") != cfg["protocol_sha256"]:
            issues.append("seed의 protocol 해시가 다르다")
    v2_cal.raise_issues("결과 검사 실패", issues)
    summary = v2_cal.summarize_dir(results, tuple(cfg["epoch_candidates"]))
    target = out / "summary.json"
    if target.exists():
        old = read(target)
        if summary != {k: old[k] for k in summary}:
            raise ValueError("저장된 summary와 재집계가 다르다")
    elif save:
        summary.update(run_id=cfg["run_id"], split=split_name, created_kst=v2.now(),
                       protocol_sha256=cfg["protocol_sha256"], config_sha256=v2.digest(out / "config.json"),
                       data_role="development_diagnostic")
        protected.write_new(target, summary)
    print(f"verified {split_name}: E={summary['chosen_E']}", flush=True)
    return summary


def run_all(protocol_path, parallel):
    if not 1 <= parallel <= 5:
        raise ValueError("parallel은 1~5")
    p = read(protocol_path)
    for split_name in p["spec"]["execution_order"]:
        _, cfg, out, _ = load_state(protocol_path, split_name)
        pending = [s for s in cfg["seeds"] if not (out / f"seed-{s}.json").exists()]
        running = []
        print("start", split_name, "pending", pending, flush=True)
        for s in pending:
            while sum(child.poll() is None for _, child, _ in running) >= parallel:
                time.sleep(1)
            log = (out / f"seed-{s}.log").open("x", encoding="utf-8")
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "run", "--protocol", str(Path(protocol_path).resolve()),
                                      "--split", split_name, "--seed", str(s)], cwd=v2.ROOT, stdout=log, stderr=subprocess.STDOUT)
            running.append((s, child, log))
        failed = []
        for s, child, log in running:
            code = child.wait()
            log.close()
            if code:
                failed.append(s)
        if failed:
            raise RuntimeError(f"{split_name} 실패 seed: {failed}; 로그 확인")
        verify_run(protocol_path, split_name, save=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init-all", "run-all", "run", "verify-all"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--split", choices=v2.SPLIT_NAMES)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--parallel", type=int, default=5)
    args = parser.parse_args()
    if args.command == "init-all":
        init_all(args.protocol)
    elif args.command == "run-all":
        run_all(args.protocol, args.parallel)
    elif args.command == "run":
        if args.split is None or args.seed is None:
            parser.error("run에는 --split과 --seed 필요")
        run_seed(args.protocol, args.split, args.seed)
    else:
        for name in read(args.protocol)["spec"]["execution_order"]:
            verify_run(args.protocol, name)
