"""고정된 기존 예측의 발행 진단·예약 지연 비교. init 후 run; 학습하지 않는다."""
import argparse
import gzip
import json
from collections import Counter
from pathlib import Path

import numpy as np

import v2
import v2_delay_replay as delay
import v2_event_trace as trace
import v2_protected_manifest as protected

OUT = v2.DOC / "event-timing-01"
DELAYS = delay.SUPPORTED_DELAYS_MS
METRICS = ("score", "correct_rate", "no_observed_emit_rate", "raw_no_candidate_rate", "early_clip_rate", "unmatched_per_source", "background_false_per_min")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_paths(strategy, split):
    run_id = f"V2-{split}-cal" if strategy == "legacy" else f"NONE-BAL-01-{split}"
    base = v2.DOC / "results" if strategy == "legacy" else v2.DOC / "none-balance-01/results"
    return base / run_id, v2.ROOT / "ml/runs" / run_id


def panel_specs():
    panels = []
    def add(strategy, split, epoch, phase):
        panel = {"id": f"{strategy}-{split}-E{epoch}", "strategy": strategy, "split": split, "epoch": epoch, "phase": phase}
        if panel["id"] not in {p["id"] for p in panels}:
            panels.append(panel)
    for split in ("S-P5", "C"):
        add("legacy", split, 60, "primary")
    for strategy in ("legacy", "balanced"):
        for split in ("S-P5", "C"):
            base, _ = run_paths(strategy, split)
            for e in sorted({1, 60, read(base / "summary.json")["chosen_E"]}):
                add(strategy, split, e, "supporting")
    for split in ("S-P1", "S-P2", "S-P3", "S-P4"):
        for strategy in ("legacy", "balanced"):
            base, _ = run_paths(strategy, split)
            for e in sorted({1, 60, read(base / "summary.json")["chosen_E"]}):
                add(strategy, split, e, "rotation")
    return panels


def evaluate_source(record, times, base_events, delay_ms, common):
    scheduled = delay.schedule_events(base_events, delay_ms, times[-1], common=common)
    counts, lags, events = v2.classify_events(record, scheduled["events"])
    exposure = delay.common_exposure_ms(times[0], times[-1]) if common else delay.full_exposure_ms(times[0], times[-1])
    return {"source_path": record["source_path"], "session": record["session"],
            "direction": record["direction"], "completion_ms": record["completion_ms"],
            "counts": counts, "delays_ms": lags, "events": events,
            "pending": scheduled["pending"], "excluded": scheduled["excluded"],
            "candidate_count": len(base_events), "exposure_ms": exposure,
            "cutoff_ms": scheduled["cutoff_ms"], "last_observed_ms": int(times[-1]),
            "match_horizon_clipped": record["completion_ms"] is not None and record["completion_ms"] + 500 > times[-1]}


def ratio(a, b):
    return a / b if b else None


def aggregate_sources(rows):
    directional = [p for p in rows if p["completion_ms"] is not None]
    background = [p for p in rows if p["completion_ms"] is None]
    n = len(directional)
    counts = Counter()
    for p in rows:
        counts.update(p["counts"])
    correct = sum(p["counts"]["correct"] for p in directional)
    unmatched = sum(sum(p["counts"][k] for k in v2.UNMATCHED_ON_GESTURE) for p in directional)
    lags = [x for p in directional for x in p["delays_ms"]]
    exposure = sum(p["exposure_ms"] for p in background)
    early_match = sum(ev["kind"] == "early" and ev["class_index"] == v2.CLASSES.index(p["direction"]) for p in directional for ev in p["events"])
    early_mismatch = sum(ev["kind"] == "early" and ev["class_index"] != v2.CLASSES.index(p["direction"]) for p in directional for ev in p["events"])
    return {"direction_sources": n, "background_sources": len(background), "counts": dict(counts),
            "score": ratio(correct - unmatched, n), "correct_rate": ratio(correct, n),
            "no_observed_emit_rate": ratio(sum(not p["events"] for p in directional), n),
            "raw_no_candidate_rate": ratio(sum(p["candidate_count"] == 0 for p in directional), n),
            "early_clip_rate": ratio(sum(any(e["kind"] == "early" for e in p["events"]) for p in directional), n),
            "unmatched_per_source": ratio(unmatched, n), "background_false": counts["background_false"],
            "background_exposure_ms": exposure, "background_false_per_min": ratio(counts["background_false"] * 60000, exposure),
            "background_rate_has_censoring": any(p["pending"] for p in background),
            "delay_ms_n": len(lags), "delay_ms_median": float(np.median(lags)) if lags else None,
            "delay_ms_p95": float(np.percentile(lags, 95)) if lags else None,
            "early_direction_match": early_match, "early_direction_mismatch": early_mismatch,
            "pending": sum(len(p["pending"]) for p in rows),
            "pending_only_sources": sum(bool(p["pending"]) and not p["events"] for p in rows),
            "pending_direction": sum(len(p["pending"]) for p in directional),
            "pending_background": sum(len(p["pending"]) for p in background),
            "excluded_candidates": sum(len(p["excluded"]) for p in rows),
            "clipped_sources": [p["source_path"] for p in directional if p["match_horizon_clipped"]]}


def requirements_status(requirements):
    fields = ("R_min", "U_max", "B_max_per_min", "D_max_ms")
    missing = [k for k in fields if requirements.get(k) is None]
    return {"can_evaluate_numeric_targets": not missing, "missing": missing, "can_adopt": False,
            "selected_delay_ms": None, "reason": "제품 기준 또는 독립 관찰 미확정; 자동 채택하지 않음"}


def target_check(metric, delay_ms, requirements):
    status = requirements_status(requirements)
    if not status["can_evaluate_numeric_targets"]:
        return {"status": "unagreed", "violations": None}
    violations = []
    for metric_name, target_name, lower in (("correct_rate", "R_min", True), ("unmatched_per_source", "U_max", False), ("background_false_per_min", "B_max_per_min", False)):
        value = metric[metric_name]
        if value is None or (value < requirements[target_name] if lower else value > requirements[target_name]):
            violations.append(target_name)
    if delay_ms > requirements["D_max_ms"]:
        violations.append("D_max_ms")
    return {"status": "meets_numeric_targets" if not violations else "fails_numeric_targets", "violations": violations, "adopted": False}


def init(out):
    out = Path(out)
    if (out / "protocol.json").exists() or (out / "input-manifest.json").exists():
        raise FileExistsError("이미 고정된 실험은 덮어쓰지 않는다")
    spec = read(out / "spec.json")
    if spec["delays_ms"] != list(DELAYS) or spec["max_delay_ms"] != 200:
        raise ValueError("계획의 고정 지연 후보가 아니다")
    old = read(v2.DOC / "diagnostics/completion-review-01/protected-manifest.json")
    if any(protected.compare(v2.ROOT, old).values()):
        raise ValueError("기존 보호 대상 불일치")
    patterns = protected.PROTECTED_PATTERNS + (
        "docs/experiments/ble-v2/none-balance-01/**/*", "ml/runs/NONE-BAL-01-*/**/*",
        "ml/v2_none_*.py", "ml/v2_protocol.py")
    manifest = protected.build_manifest(v2.ROOT, patterns)
    manifest["purpose"] = "발행 시점 진단 전 원래/층화 코드·결과·예측 동결"
    protected.write_new(out / "input-manifest.json", manifest)
    protocol = {"experiment": spec["experiment"], "created_before_replay_kst": v2.now(),
                "spec": spec, "spec_sha256": v2.digest(out / "spec.json"),
                "requirements_at_freeze": read(out / "product-requirements.json"),
                "requirements_sha256": v2.digest(out / "product-requirements.json"),
                "input_manifest_sha256": v2.digest(out / "input-manifest.json"),
                "code_sha256": {name: v2.digest(v2.ROOT / name) for name in spec["code_files"]},
                "panels": panel_specs(), "can_adopt": False, "new_training": False}
    protected.write_new(out / "protocol.json", protocol)
    print("protocol saved", out / "protocol.json", "panels", len(protocol["panels"]), flush=True)


def verify_inputs(out, full=True):
    out = Path(out)
    p = read(out / "protocol.json")
    assert p["spec_sha256"] == v2.digest(out / "spec.json")
    assert p["requirements_sha256"] == v2.digest(out / "product-requirements.json")
    assert p["input_manifest_sha256"] == v2.digest(out / "input-manifest.json")
    assert p["code_sha256"] == {n: v2.digest(v2.ROOT / n) for n in p["spec"]["code_files"]}
    if full:
        diff = protected.compare(v2.ROOT, read(out / "input-manifest.json"))
        if any(diff.values()):
            raise ValueError(f"입력 변경: {diff}")
    return p


def panel_sources(panel):
    base, score_dir = run_paths(panel["strategy"], panel["split"])
    cfg = read(base / "config.json")
    split = v2.load_split(panel["split"])
    _, records = v2.load_records()
    for seed in cfg["seeds"]:
        result = read(base / f"seed-{seed}.json")
        sources = []
        for fold in result["folds"]:
            k = fold["fold"]
            expected = set(split["cv"]["folds"][k]["validation_sources"])
            entry = fold["per_epoch"][str(panel["epoch"])]
            assert {r["source_path"] for r in entry["per_source"]} == expected
            assert not expected & set(split["eval_sources"])
            meta = read(score_dir / f"seed-{seed}-fold-{k}-windows.json")
            with np.load(score_dir / f"seed-{seed}-fold-{k}-scores.npz") as snapshots:
                scores = snapshots[f"e{panel['epoch']}"]
                assert scores.shape == (len(meta), 5)
                start = 0
                for saved in entry["per_source"]:
                    rec = records[saved["source_path"]]
                    times = v2.decision_times(rec["rows"]).tolist()
                    n = len(times)
                    chunk = meta[start:start+n]
                    assert all(m["source_path"] == rec["source_path"] for m in chunk)
                    assert [m["timestamp_ms"] for m in chunk] == times
                    assert all(saved[key] == rec[key] for key in ("completion_ms", "direction", "session", "rows"))
                    sources.append((rec, times, scores[start:start+n].copy(), saved))
                    start += n
                assert start == len(meta)
        yield seed, sources


def mean_metrics(by_seed):
    keys = list(METRICS) + ["pending", "pending_only_sources", "pending_direction", "pending_background", "delay_ms_median", "delay_ms_p95", "delay_ms_n", "early_direction_match", "early_direction_mismatch"]
    return {key: float(np.mean([v[key] for v in by_seed.values() if v[key] is not None]))
            if any(v[key] is not None for v in by_seed.values()) else None for key in keys}


def differences(baseline, delayed):
    result = {}
    assert set(baseline) == set(delayed)
    for metric in METRICS:
        values = {s: delayed[s][metric] - baseline[s][metric] for s in baseline
                  if delayed[s][metric] is not None and baseline[s][metric] is not None}
        ds = list(values.values())
        result[metric] = {"mean": float(np.mean(ds)) if ds else None,
                          "min": min(ds) if ds else None, "max": max(ds) if ds else None,
                          "up": sum(v > 1e-12 for v in ds), "down": sum(v < -1e-12 for v in ds),
                          "equal": sum(abs(v) <= 1e-12 for v in ds), "n_pairs": len(ds), "per_seed": values}
    return result


def run(out):
    out = Path(out)
    protocol = verify_inputs(out)
    if (out / "summary.json").exists() or (out / "traces").exists():
        raise FileExistsError("기존 분석 출력은 덮어쓰지 않는다")
    report = {"created_kst": v2.now(), "protocol_sha256": v2.digest(out / "protocol.json"),
              "requirements": requirements_status(protocol["requirements_at_freeze"]), "panels": {},
              "source_observations_checked": 0, "new_training": False}
    for panel in protocol["panels"]:
        panel_dir = out / "traces" / panel["id"]
        panel_dir.mkdir(parents=True)
        raw_stats = {}
        grouped = {domain: {str(d): {} for d in DELAYS} for domain in ("common", "full")}
        for seed, sources in panel_sources(panel):
            rows = {domain: {d: [] for d in DELAYS} for domain in grouped}
            categories, flags = Counter(), Counter()
            failed = blocked = 0
            with gzip.open(panel_dir / f"seed-{seed}.jsonl.gz", "xt", encoding="utf-8", compresslevel=1) as stream:
                for rec, times, scores, saved in sources:
                    replay = trace.trace_events(times, scores)
                    diagnosis = trace.diagnose_source(rec, times, scores)
                    assert diagnosis["events"] == saved["events"]
                    assert Counter(diagnosis["counts"]) == Counter(saved["counts"])
                    assert diagnosis["delays_ms"] == saved["delays_ms"]
                    if diagnosis["category"] is not None:
                        categories[diagnosis["category"]] += 1
                        for name, value in diagnosis["flags"].items():
                            flags[name] += value
                        if diagnosis["counts"]["missed"]:
                            failed += 1
                            blocked += diagnosis["flags"]["truth_pair_blocked_locked"]
                    detail = {"record": rec, "diagnosis": diagnosis, "decisions": replay["decisions"], "replay": {}}
                    for domain in grouped:
                        detail["replay"][domain] = {}
                        for d in DELAYS:
                            item = evaluate_source(rec, times, replay["events"], d, domain == "common")
                            if domain == "common":
                                assert not item["pending"]
                            rows[domain][d].append(item)
                            detail["replay"][domain][str(d)] = item
                    # Common candidates have exactly the same visible event count for every D.
                    assert len({len(rows['common'][d][-1]['events']) for d in DELAYS}) == 1
                    stream.write(json.dumps(detail, ensure_ascii=False, allow_nan=False) + "\n")
                    report["source_observations_checked"] += 1
            assert sum(categories.values()) == failed + categories["correct"]
            raw_stats[str(seed)] = {"categories": dict(categories), "overlapping_flags": dict(flags),
                                    "failed": failed, "blocked_failed": blocked, "blocked_failed_rate": ratio(blocked, failed)}
            for domain in grouped:
                for d in DELAYS:
                    grouped[domain][str(d)][str(seed)] = aggregate_sources(rows[domain][d])
        stats = {"panel": panel, "original_full_trace": raw_stats, "delay": {}}
        for domain in grouped:
            stats["delay"][domain] = {}
            for d in DELAYS:
                per_seed = grouped[domain][str(d)]
                mean = mean_metrics(per_seed)
                stats["delay"][domain][str(d)] = {"mean": mean, "per_seed": per_seed,
                    "paired_vs_same_domain_D0": differences(grouped[domain]["0"], per_seed),
                    "numeric_targets": target_check(mean, d, protocol["requirements_at_freeze"])}
        report["panels"][panel["id"]] = stats
        verify_inputs(out, full=False)
        print("panel verified", panel["id"], "sources", sum(sum(v["categories"].values()) for v in raw_stats.values()), flush=True)
    verify_inputs(out)
    protected.write_new(out / "summary.json", report)
    for name, body in render_reports(report).items():
        with (out / name).open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(body)
    print("analysis complete", len(report["panels"]), "panels; sources", report["source_observations_checked"], flush=True)


def render_reports(report):
    trace_lines = ["# 발행·잠금 상태 진단", "", "원래 전체 클립 상태를 저장 발행과 대조했다. 원본×seed 반복 관측이며 독립 동작 수가 아니다. 플래그는 중복 가능하다.", "",
                   "| 패널 | 정검출 | 무발행 | 발행 후 정검출 없음 | 누락 중 잠금 원시쌍/누락 |", "|---|---:|---:|---:|---|"]
    delay_lines = ["# 고정 발행 지연의 개발용 민감도", "", "정답 e는 자동 센서 후보이며 실제 복귀 완료로 검증되지 않았다. 추가 학습·최종 평가·자동 후보 채택은 없다.", "",
                   "공통 비교는 원래 후보 t≤T−200을 D0에도 동일 적용한다. 기존 전체 클립 결과와 분모가 다르다. 정검출이 높아져도 모델 분류력이 향상됐다는 뜻은 아니다.", ""]
    for panel_id, p in report["panels"].items():
        raw = list(p["original_full_trace"].values())
        counts = Counter()
        for x in raw:
            counts.update(x["categories"])
        n = sum(counts.values())
        failed = sum(x["failed"] for x in raw)
        blocked = sum(x["blocked_failed"] for x in raw)
        trace_lines.append(f"| {panel_id} | {counts['correct']}/{n} | {counts['no_emit']}/{n} | {counts['emitted_without_correct']}/{n} | {blocked}/{failed} |")
        delay_lines += [f"## {panel_id} ({p['panel']['phase']})", "",
                        "| D(ms) | 공통 정검출률 | 조기 발행 클립 | 무관측 발행 | 원래 후보 없음 | 미매칭/원본 | 공통 배경/분 | 성공 지연 median/p95(ms), 평균 n | 점수 Δ 대 공통D0 | 전체 pending(방향/배경), seed 평균 |", "|---|---:|---:|---:|---:|---:|---:|---|---:|---|"]
        for d in DELAYS:
            row = p["delay"]["common"][str(d)]
            m, full = row["mean"], p["delay"]["full"][str(d)]["mean"]
            lag = f"{m['delay_ms_median']}/{m['delay_ms_p95']}, n={m['delay_ms_n']:.1f}"
            delta_score = row["paired_vs_same_domain_D0"]["score"]["mean"]
            delay_lines.append(f"| {d} | {m['correct_rate']*100:.1f}% | {m['early_clip_rate']*100:.1f}% | {m['no_observed_emit_rate']*100:.1f}% | {m['raw_no_candidate_rate']*100:.1f}% | {m['unmatched_per_source']:.3f} | {m['background_false_per_min']:.2f} | {lag} | {delta_score:+.4f} | {full['pending']:.1f} ({full['pending_direction']:.1f}/{full['pending_background']:.1f}) |")
        delay_lines.append("")
    # Explicitly report all pending metrics in JSON, without describing censored full-domain rates as safer.
    delay_lines += ["", "전체 클립 지표·미완료 예약·원본별 목록·seed 대응 차이는 summary.json과 traces/*.jsonl.gz에 있다. 전체 클립 pending이 있으면 해당 배경 발행률에 관측 끝 검열이 있다.",
                    "", "제품 요구는 미합의 항목을 그대로 남겼다. 허용 추가 지연·성공률·오발행 기준과 독립 관찰이 없으므로 최고 수치의 지연을 채택하지 않는다.", ""]
    return {"trace-summary.md": "\n".join(trace_lines) + "\n", "delay-comparison.md": "\n".join(delay_lines),
            "decision.md": "# 다음 판단\n\n제품 수치 기준/영상 관찰 미확정으로 지연 후보를 자동 채택하지 않았다. 단계 2/3은 개발용 진단이다. 영상 파일럿과 사람 주석이 필요하다. 기존 모델·e·문턱·재무장·E·기본값을 변경하지 않았다.\n"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "run", "verify"))
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    if args.command == "init":
        init(args.out)
    elif args.command == "run":
        run(args.out)
    else:
        verify_inputs(args.out)
        print("frozen inputs unchanged")
