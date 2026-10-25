"""BLE v2 보정: 학습용 안의 교차검증으로 고정 epoch E를 고른다. 평가용은 열지 않는다.

사용 (ml/.venv/Scripts/python.exe ml/v2_cal.py <명령> --split <분할> [--run-id ID] [--protocol 경로]):
  init       실행 설정(config.json) 저장. protocol과 현재 코드·주석 목록·분할이 일치해야 한다
  run        seed 하나를 모든 fold에서 학습하고 결과를 seed-<seed>.json에 저장
  run-all    seed 5개를 병렬 프로세스로 run
  summarize  결과 검사 후 E별 점수와 선택된 E를 summary.json에 저장(이미 있으면 거부)
  verify     저장된 결과를 읽기 전용으로 검사하고 summary.json과 재집계가 일치하는지 확인

계획: docs/TrainingPlan.md "BLE v2 실험" 절차 3. (seed, fold)마다 60 epoch까지 한 번 학습하고
후보 epoch가 끝난 시점마다 검증 fold를 replay한다. Adam 학습률이 고정이라 E epoch에서 멈춘
별도 학습과 같은 가중치다(test_v2_cal.py가 확인).

실행기 버전: 1 = 최초(커밋 bd62fa4, V2-*-cal 결과가 이 버전), 2 = 보호 검사와 실행 환경 기록 추가.
과거 결과(버전 1)는 현재 코드와 달라도 손상으로 보지 않고, config에 기록된 코드 버전을 git 이력에서
꺼내 대조한다. 새 실행(버전 2 이상)은 현재 코드가 config와 일치해야 한다. 과거 config·protocol은
고치지 않으며, 코드가 바뀌면 새 protocol과 새 run-id로 실행한다.
"""

import argparse
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from collections import Counter

import numpy as np

import v2
from v2 import DOC, ROOT, digest, dump, now

RUNS = ROOT / "ml/runs"
CODE_FILES = ("v2.py", "v2_cal.py", "model.py")
EARLY_NEAR_MS = 100
RUNNER_VERSION = 2
MAX_ISSUES_SHOWN = 25
DEFAULT_PROTOCOL = DOC / "results/protocol.json"


class Mismatch(Exception):
    """해시·목록·결과 파일이 기록과 다를 때."""


def default_run_id(split):
    return f"V2-{split}-cal"


def results_dir(run_id):
    return DOC / "results" / run_id


def scores_dir(run_id):
    return RUNS / run_id


def code_hashes():
    return {f: digest(ROOT / "ml" / f) for f in CODE_FILES}


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def raise_issues(title, issues):
    if issues:
        shown = issues[:MAX_ISSUES_SHOWN]
        more = f"\n  … 외 {len(issues) - len(shown)}건" if len(issues) > len(shown) else ""
        raise Mismatch(title + "\n  - " + "\n  - ".join(shown) + more)


# ---------------------------------------------------------------- 일치 검사

def annotation_list_issues(data, root=ROOT):
    """records.json이 가리키는 원본 목록이 디스크의 세션 폴더와 같은지(추가·누락 파일)."""
    issues = []
    recorded = {r["source_path"] for r in data["records"]}
    on_disk = set()
    for info in data["sessions"].values():
        folder = root / "data/sessions" / info["folder"]
        on_disk |= {f"data/sessions/{info['folder']}/{p.name}" for p in folder.glob("*.csv")}
    for p in sorted(on_disk - recorded):
        issues.append(f"records에 없는 원본이 디스크에 있다: {p}")
    for p in sorted(recorded - on_disk):
        issues.append(f"records에 있는 원본이 디스크에 없다: {p}")
    return issues


def protocol_issues(protocol, split_name, records_path=None, split_path=None, current_code=None, check_annotation_list=True):
    """protocol이 가리키는 분할·records·코드가 현재와 같은지. 다르면 목록을 돌려준다."""
    records_path = records_path or v2.RECORDS
    split_path = split_path or v2.SPLITS / f"v2-{split_name}.json"
    current_code = current_code or code_hashes()
    issues = []
    if protocol.get("split_sha256", {}).get(split_name) != digest(split_path):
        issues.append(f"분할 {split_name}의 해시가 protocol과 다르다")
    if protocol.get("records_sha256") != digest(records_path):
        issues.append("records.json의 해시가 protocol과 다르다")
    for f, sha in protocol.get("code_sha256", {}).items():
        if current_code.get(f) != sha:
            issues.append(f"코드 {f}가 protocol에 고정한 버전과 다르다")
    if check_annotation_list:
        data = json.loads(records_path.read_text(encoding="utf-8"))
        issues += annotation_list_issues(data)
        for name, sha in data["annotation_sha256"].items():
            if digest(records_path.parent / name) != sha:
                issues.append(f"주석 후보 파일 {name}의 해시가 records와 다르다")
    return issues


def config_issues(config, split_name, protocol_path=None, current_code=None, records_path=None, split_path=None):
    """run·summarize 전에: config에 고정한 코드·records·분할·protocol이 현재와 같은지."""
    records_path = records_path or v2.RECORDS
    split_path = split_path or v2.SPLITS / f"v2-{split_name}.json"
    current_code = current_code or code_hashes()
    issues = []
    if config.get("runner_version", 1) < RUNNER_VERSION:
        issues.append(f"이 config는 실행기 버전 {config.get('runner_version', 1)}의 것이다(현재 {RUNNER_VERSION}). "
                      "새 실행은 새 protocol·새 run-id로 init해야 한다")
    if config.get("split") != split_name:
        issues.append(f"config의 분할 {config.get('split')}이 요청한 {split_name}과 다르다")
    if config.get("split_sha256") != digest(split_path):
        issues.append("분할 파일의 해시가 config와 다르다")
    if config.get("records_sha256") != digest(records_path):
        issues.append("records.json의 해시가 config와 다르다")
    for f, sha in config.get("code_sha256", {}).items():
        if current_code.get(f) != sha:
            issues.append(f"코드 {f}가 init 이후 바뀌었다")
    protocol_path = protocol_path or (ROOT / config["protocol_path"] if config.get("protocol_path") else None)
    if protocol_path is None or not protocol_path.exists():
        issues.append("config가 가리키는 protocol 파일이 없다")
    elif config.get("protocol_sha256") != digest(protocol_path):
        issues.append("protocol 파일의 해시가 config와 다르다")
    return issues


def git_show_text(head, relpath):
    out = subprocess.run(["git", "show", f"{head}:{relpath}"], cwd=ROOT, capture_output=True)
    return out.stdout if out.returncode == 0 else None


def recorded_code_issues(config, show=git_show_text):
    """config에 기록된 코드 해시가 그 당시 git 커밋(config.git_head)의 파일과 같은지(과거 결과 확인용)."""
    import hashlib
    issues = []
    head = config.get("git_head")
    if not head:
        return ["config에 git_head가 없어 기록된 코드 버전을 확인할 수 없다"]
    for f, sha in config.get("code_sha256", {}).items():
        raw = show(head, f"ml/{f}")
        if raw is None:
            issues.append(f"git {head[:7]}에서 ml/{f}를 찾지 못했다(기록된 코드 버전 확인 불가)")
        elif hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest() != sha:
            issues.append(f"ml/{f}의 기록 해시가 git {head[:7]}의 파일과 다르다")
    return issues


def results_issues(config, split_obj, seed_results):
    """seed·fold·epoch 누락, 중복 원본, 결과와 config·분할의 불일치를 찾는다."""
    issues = []
    seeds = [r.get("seed") for r in seed_results]
    if len(set(seeds)) != len(seeds):
        issues.append(f"seed가 중복됐다: {sorted(seeds)}")
    if sorted(set(seeds)) != sorted(config["seeds"]):
        issues.append(f"seed 목록이 config와 다르다: 결과 {sorted(set(seeds))}, config {sorted(config['seeds'])}")
    epochs = sorted(str(e) for e in config["epoch_candidates"])
    max_epoch = max(config["epoch_candidates"])
    folds_cfg = split_obj["cv"]["folds"]
    evaluation = set(split_obj["eval_sources"])
    required = ("event_totals", "per_source", "val_loss", "window_accuracy", "train_loss")
    for r in seed_results:
        s = r.get("seed")
        if r.get("split") != config["split"]:
            issues.append(f"seed {s}: 분할이 {r.get('split')}이다(config {config['split']})")
        if [f.get("fold") for f in r.get("folds", [])] != list(range(config["n_folds"])):
            issues.append(f"seed {s}: fold 목록이 {[f.get('fold') for f in r.get('folds', [])]}이다(기대 0~{config['n_folds'] - 1})")
        seen_in_seed = {e: Counter() for e in epochs}
        for f in r.get("folds", []):
            k = f.get("fold")
            if not isinstance(k, int) or not 0 <= k < len(folds_cfg):
                continue
            expected = sorted(folds_cfg[k]["validation_sources"])
            if f.get("held_out_session") != folds_cfg[k].get("held_out_session"):
                issues.append(f"seed {s} fold {k}: 검증 세션이 분할과 다르다")
            if sorted(f.get("per_epoch", {})) != epochs:
                issues.append(f"seed {s} fold {k}: epoch 목록이 {sorted(f.get('per_epoch', {}))}이다(기대 {epochs})")
            if len(f.get("train_loss_by_epoch", [])) != max_epoch:
                issues.append(f"seed {s} fold {k}: 학습 손실 길이 {len(f.get('train_loss_by_epoch', []))} (기대 {max_epoch})")
            for e in epochs:
                entry = f.get("per_epoch", {}).get(e)
                if entry is None:
                    continue
                if any(key not in entry for key in required):
                    issues.append(f"seed {s} fold {k} E{e}: 필수 항목 누락")
                    continue
                got = [p["source_path"] for p in entry["per_source"]]
                dup = [p for p, n in Counter(got).items() if n > 1]
                if dup:
                    issues.append(f"seed {s} fold {k} E{e}: 중복 원본 {dup[:3]}")
                if sorted(set(got)) != expected:
                    miss, extra = sorted(set(expected) - set(got)), sorted(set(got) - set(expected))
                    issues.append(f"seed {s} fold {k} E{e}: 검증 원본이 분할과 다르다(누락 {len(miss)}, 초과 {len(extra)})")
                if set(got) & evaluation:
                    issues.append(f"seed {s} fold {k} E{e}: 평가용 원본이 결과에 있다")
                seen_in_seed[e].update(got)
                totals = Counter()
                for p in entry["per_source"]:
                    totals.update(p["counts"])
                    emitted = sum(v for key, v in p["counts"].items() if key != "missed")
                    if emitted != len(p["events"]):
                        issues.append(f"seed {s} fold {k} E{e}: {p['source_path']}의 발행 로그와 집계가 다르다")
                if {a: b for a, b in totals.items() if b} != {a: b for a, b in entry["event_totals"].items() if b}:
                    issues.append(f"seed {s} fold {k} E{e}: 원본별 합계가 event_totals와 다르다")
        for e, counter in seen_in_seed.items():
            repeated = [p for p, n in counter.items() if n > 1]
            if repeated:
                issues.append(f"seed {s} E{e}: 원본이 두 fold의 검증에 있다 {repeated[:3]}")
        if config.get("runner_version", 1) >= 2:
            rt = r.get("runtime") or {}
            if r.get("runner_version") != config["runner_version"]:
                issues.append(f"seed {s}: 결과의 실행기 버전이 config와 다르다")
            if not runtime_ok(rt):
                issues.append(f"seed {s}: 스레드 1개·결정성 연산이 확인되지 않았다 {rt}")
    return issues


# ---------------------------------------------------------------- init

def init(split_name, run_id=None, protocol_path=None):
    run_id = run_id or default_run_id(split_name)
    protocol_path = protocol_path or DEFAULT_PROTOCOL
    if not protocol_path.exists():
        raise FileNotFoundError(f"{protocol_path}가 먼저 있어야 한다")
    out = results_dir(run_id)
    if (out / "config.json").exists():
        raise FileExistsError(f"{out}/config.json이 이미 있다. 덮어쓰지 않는다")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    v2.verify()
    raise_issues("protocol이 현재 코드·주석 목록·분할과 다르다:", protocol_issues(protocol, split_name))
    data, by_path = v2.load_records()
    split = v2.load_split(split_name)
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
    try:
        protocol_rel = str(protocol_path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        protocol_rel = str(protocol_path)
    config = {"run_id": run_id, "created_kst": now(), "runner_version": RUNNER_VERSION, "split": split_name,
              "split_sha256": digest(v2.SPLITS / f"v2-{split_name}.json"), "records_sha256": digest(v2.RECORDS),
              "protocol_path": protocol_rel, "protocol_sha256": digest(protocol_path),
              "seeds": v2.SEEDS, "epoch_candidates": v2.EPOCH_CANDIDATES,
              "max_epoch": max(v2.EPOCH_CANDIDATES), "n_folds": len(folds),
              "python": sys.version, "platform": platform.platform(), **versions,
              "code_sha256": code_hashes(), "git_head": git("rev-parse", "HEAD"),
              "git_status_short": git("status", "--short").splitlines(),
              "required_runtime": {"intra_op_threads": 1, "inter_op_threads": 1, "op_determinism": True},
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


def runtime_ok(rt):
    """새 실행의 요구: 스레드 1개, 연산 결정성 켜짐, 그리고 그 설정이 실제로 적용됐다고 기록됨."""
    return bool(rt) and rt.get("tf_threads_fixed") is True and rt.get("op_determinism") is True \
        and rt.get("intra_op_threads") == 1 and rt.get("inter_op_threads") == 1


def runtime_info():
    """실제로 적용된 TensorFlow 설정. 학습 후에 읽어 적용 여부를 기록한다."""
    import tensorflow as tf
    try:    # 공개 API에는 조회 함수가 없다(TF 2.21 확인). 내부 함수가 없으면 확인 불가(None)로 기록해 새 실행이 거부된다
        from tensorflow.python.framework import config as tf_config
        determinism = bool(tf_config.is_op_determinism_enabled())
    except (ImportError, AttributeError):
        determinism = None
    return {"tf_threads_fixed": v2.tf_threads_fixed,
            "intra_op_threads": tf.config.threading.get_intra_op_parallelism_threads(),
            "inter_op_threads": tf.config.threading.get_inter_op_parallelism_threads(),
            "op_determinism": determinism,
            "env": {k: os.environ.get(k) for k in ("TF_ENABLE_ONEDNN_OPTS", "TF_DETERMINISTIC_OPS", "TF_CPP_MIN_LOG_LEVEL")},
            "tensorflow": tf.__version__, "devices": [d.device_type for d in tf.config.list_physical_devices()],
            "pid": os.getpid()}


def run_seed(split_name, seed, out_dir, score_dir, folds=None, epochs=v2.EPOCH_CANDIDATES, log=print):
    """seed 하나를 모든 fold에서 학습·재생한다. 결과는 dict로 돌려주고 점수 배열은 score_dir에 둔다."""
    data, by_path = v2.load_records()
    split = v2.load_split(split_name)
    score_dir.mkdir(parents=True, exist_ok=True)
    result = {"seed": seed, "split": split_name, "runner_version": RUNNER_VERSION, "epochs": list(epochs), "folds": []}
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
    result["runtime"] = runtime_info()
    result["seconds"] = round(time.time() - t_start, 1)
    return result


def load_config(run_id):
    path = results_dir(run_id) / "config.json"
    if not path.exists():
        raise FileNotFoundError(f"{path}가 없다. 먼저 init해야 한다")
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_run(split_name, seed, run_id=None):
    run_id = run_id or default_run_id(split_name)
    out = results_dir(run_id)
    config = load_config(run_id)
    assert seed in config["seeds"], seed
    raise_issues("config에 고정한 항목이 현재와 다르다. run을 거부한다:", config_issues(config, split_name))
    target = out / f"seed-{seed}.json"
    if target.exists():
        raise FileExistsError(f"{target}가 이미 있다. 덮어쓰지 않는다")
    result = run_seed(split_name, seed, out, scores_dir(run_id))
    if not runtime_ok(result["runtime"]):
        raise Mismatch(f"스레드 1개·결정성 연산이 적용되지 않았다. 결과를 저장하지 않는다: {result['runtime']}")
    dump(target, result)
    print("saved", target, f"{result['seconds']}s")


def cmd_run_all(split_name, parallel, run_id=None, protocol_arg=None):
    run_id = run_id or default_run_id(split_name)
    out = results_dir(run_id)
    config = load_config(run_id)
    raise_issues("config에 고정한 항목이 현재와 다르다. run-all을 거부한다:", config_issues(config, split_name))
    pending = [s for s in config["seeds"] if not (out / f"seed-{s}.json").exists()]
    print("pending seeds:", pending)
    procs = []
    for s in pending:
        log = open(out / f"seed-{s}.log", "w", encoding="utf-8")
        procs.append((s, subprocess.Popen([sys.executable, str(ROOT / "ml/v2_cal.py"), "run", "--split", split_name,
                                           "--seed", str(s), "--run-id", run_id],
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


def load_seed_results(out, config):
    results = []
    for s in config["seeds"]:
        path = out / f"seed-{s}.json"
        if not path.exists():
            raise FileNotFoundError(f"{path}가 없다. seed가 모두 끝나야 요약한다")
        results.append(json.loads(path.read_text(encoding="utf-8")))
    return results


def check_results(config, split_name, seed_results):
    """결과 파일 검사 + 코드 버전 확인. 새 실행은 현재 코드와, 과거 결과는 기록된 당시 코드와 대조한다."""
    split_obj = v2.load_split(split_name)
    issues = results_issues(config, split_obj, seed_results)
    if config.get("runner_version", 1) >= RUNNER_VERSION:
        issues += config_issues(config, split_name)
        kind = "새 실행(현재 코드와 대조)"
    else:
        issues += recorded_code_issues(config)
        if config.get("split_sha256") != digest(v2.SPLITS / f"v2-{split_name}.json"):
            issues.append("분할 파일의 해시가 config와 다르다")
        if config.get("records_sha256") != digest(v2.RECORDS):
            issues.append("records.json의 해시가 config와 다르다")
        kind = f"과거 결과(실행기 버전 {config.get('runner_version', 1)}, 기록된 코드 {config.get('git_head', '')[:7]}와 대조)"
    return kind, issues


def cmd_summarize(split_name, run_id=None):
    run_id = run_id or default_run_id(split_name)
    out = results_dir(run_id)
    if (out / "summary.json").exists():
        raise FileExistsError(f"{out}/summary.json이 이미 있다. 덮어쓰지 않는다(다시 확인하려면 verify)")
    config = load_config(run_id)
    seed_results = load_seed_results(out, config)
    kind, issues = check_results(config, split_name, seed_results)
    raise_issues(f"결과 검사 실패 ({kind}):", issues)
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
    print_summary(run_id, summary, tuple(config["epoch_candidates"]))


def print_summary(run_id, summary, epochs):
    print(f"{run_id}: chosen E = {summary['chosen_E']} (동점 후보 {summary['tied_epochs']})")
    print(f"{'E':>4} {'mean score':>11} {'min':>8} {'max':>8} {'correct':>8} {'unmatched':>10} {'bg/min':>7} {'val_loss':>9}")
    for e in epochs:
        t = summary["per_epoch"][str(e)]
        bg = t["mean_background_false_per_min"]
        print(f"{e:>4} {t['mean_score']:>11.4f} {t['score_min']:>8.4f} {t['score_max']:>8.4f} {t['mean_correct']:>8.1f} "
              f"{t['mean_unmatched']:>10.1f} {'-' if bg is None else format(bg, '.2f'):>7} {t['mean_val_loss']:>9.4f}")


def cmd_verify(split_name, run_id=None):
    """읽기 전용: 결과 검사 + 저장된 summary.json과 재집계 일치 확인. 아무 파일도 쓰지 않는다."""
    run_id = run_id or default_run_id(split_name)
    out = results_dir(run_id)
    config = load_config(run_id)
    seed_results = load_seed_results(out, config)
    kind, issues = check_results(config, split_name, seed_results)
    raise_issues(f"결과 검사 실패 ({kind}):", issues)
    again = summarize_dir(seed_results, tuple(config["epoch_candidates"]))
    note = "summary.json 없음"
    if (out / "summary.json").exists():
        saved = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        diffs = [e for e in again["per_epoch"] if abs(again["per_epoch"][e]["mean_score"] - saved["per_epoch"][e]["mean_score"]) > 1e-12]
        if saved["chosen_E"] != again["chosen_E"] or diffs:
            raise Mismatch(f"재집계가 저장된 summary와 다르다: 선택 E {saved['chosen_E']}→{again['chosen_E']}, 점수가 다른 E {diffs}")
        note = "저장된 summary.json과 선택 E·모든 E의 평균 점수가 일치"
    print(f"{run_id}: OK — {kind}; 선택 E={again['chosen_E']}; {note}")
    return again


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=("init", "run", "run-all", "summarize", "verify"))
    p.add_argument("--split", required=True, choices=v2.SPLIT_NAMES)
    p.add_argument("--seed", type=int)
    p.add_argument("--parallel", type=int, default=5)
    p.add_argument("--run-id")
    p.add_argument("--protocol", help="init에서 쓸 protocol 파일(기본 docs/experiments/ble-v2/results/protocol.json)")
    a = p.parse_args()
    from pathlib import Path
    if a.command == "init":
        init(a.split, a.run_id, Path(a.protocol) if a.protocol else None)
    elif a.command == "run":
        if a.seed is None:
            p.error("--seed가 필요하다")
        cmd_run(a.split, a.seed, a.run_id)
    elif a.command == "run-all":
        cmd_run_all(a.split, a.parallel, a.run_id)
    elif a.command == "summarize":
        cmd_summarize(a.split, a.run_id)
    else:
        cmd_verify(a.split, a.run_id)
