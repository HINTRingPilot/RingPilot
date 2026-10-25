"""BLE v2 보정 결과 진단: 저장된 발행 로그(seed-*.json)와 분할만 읽는다.

학습·평가를 하지 않고 기존 파일을 쓰지 않는다(출력은 새 폴더에만, 이미 있으면 거부).
기존 채점 우선순위와 선택 점수는 그대로 쓰고, 진단 항목만 더한다.

  ml/.venv/Scripts/python.exe ml/v2_diag.py [--out docs/experiments/ble-v2/diagnostics/calibration-2026-10-25]

항목: 시간×방향 교차표, 발행한 클립 비율, 성능 분리, 무발행(점수 0) 기준 비교,
같은 seed끼리의 epoch 차이, 분할 간 원본 재사용.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

import v2
import v2_cal
from v2 import CLASSES, DOC, ROOT, digest, dump, now

SPLITS = ("S-P5", "C", "S-P1", "S-P2", "S-P3", "S-P4")
KINDS = ("correct", "missed", "wrong_direction", "duplicate", "early", "late_unmatched", "background_false")
COUNT_KEYS = ("n_dir", "bg_clips", "bg_exposure_ms", "bg_clips_with_false", "bg_false", "events_total",
              "correct", "missed", "wrong_direction", "duplicate", "early", "late_unmatched",
              "early_match", "early_mismatch", "window_match", "window_mismatch", "late_match", "late_mismatch",
              "clips_emitted_any", "clips_emitted_early", "clips_emitted_window", "clips_emitted_late",
              "clips_correct", "clips_emitted_without_correct")


def derive_kind(event, completion_ms, direction):
    """발행 하나를 (시간, 방향 일치)로 도출한다. 시간 경계는 classify_events와 같다(e 전=조기, e+500 초과=늦음)."""
    if completion_ms is None:
        return "background", None
    match = event["class_index"] == CLASSES.index(direction)
    t = event["timestamp_ms"]
    timing = "early" if t < completion_ms else "late" if t > completion_ms + v2.MATCH_MS else "window"
    return timing, match


def consistent(kind, timing, match):
    """기록된 kind가 도출한 (시간, 방향 일치)와 모순되지 않는지."""
    if timing == "background":
        return kind == "background_false"
    if timing == "early":
        return kind == "early"
    if timing == "late":
        return kind == "late_unmatched"
    return kind == "wrong_direction" if not match else kind in ("correct", "duplicate")


def seed_epoch_metrics(per_source):
    """seed 하나, E 하나, 모든 fold를 합친 원본 목록에서 진단 항목을 센다."""
    m = Counter({k: 0 for k in COUNT_KEYS})      # 0건인 항목도 키가 있도록
    mismatched_kinds = 0
    for p in per_source:
        e, direction = p["completion_ms"], p["direction"]
        events = p["events"]
        if e is None:
            m["bg_clips"] += 1
            m["bg_exposure_ms"] += p["rows"] * 10 - v2.FIRST_T
            if events:
                m["bg_clips_with_false"] += 1
            m["bg_false"] += len(events)
            for ev in events:
                timing, match = derive_kind(ev, e, direction)
                mismatched_kinds += not consistent(ev["kind"], timing, match)
            continue
        m["n_dir"] += 1
        kinds_here = Counter()
        for ev in events:
            timing, match = derive_kind(ev, e, direction)
            mismatched_kinds += not consistent(ev["kind"], timing, match)
            m[f"{timing}_{'match' if match else 'mismatch'}"] += 1
            kinds_here[timing] += 1
        c = p["counts"]
        for k in ("correct", "missed", "wrong_direction", "duplicate", "early", "late_unmatched"):
            m[k] += c.get(k, 0)
        m["clips_emitted_any"] += bool(events)                 # 중복 발행이 있어도 한 클립은 한 번만 센다
        m["clips_emitted_early"] += kinds_here["early"] > 0
        m["clips_emitted_window"] += kinds_here["window"] > 0
        m["clips_emitted_late"] += kinds_here["late"] > 0
        m["clips_correct"] += c.get("correct", 0) > 0
        m["clips_emitted_without_correct"] += bool(events) and c.get("correct", 0) == 0
        m["events_total"] += len(events)
    score, correct, unmatched, n_dir = v2.selection_score(per_source)
    out = dict(m)
    out.update(score=score, unmatched=unmatched, kinds_inconsistent=mismatched_kinds)
    for key in ("n_dir", "bg_clips", "bg_exposure_ms", "clips_emitted_any", "clips_correct"):
        out.setdefault(key, 0)
    return out


def rate(a, b):
    return a / b if b else None


def stat(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {"mean": float(np.mean(values)), "min": float(min(values)), "max": float(max(values)), "per_seed": [float(v) for v in values]}


def load_run(split):
    run_id = v2_cal.default_run_id(split)
    out = v2_cal.results_dir(run_id)
    config = v2_cal.load_config(run_id)
    seed_results = v2_cal.load_seed_results(out, config)
    kind, issues = v2_cal.check_results(config, split, seed_results)
    v2_cal.raise_issues(f"{run_id}: 결과 검사 실패 ({kind})", issues)
    saved = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    return config, seed_results, saved, kind


def analyse_run(split):
    config, seed_results, saved, kind = load_run(split)
    epochs = [str(e) for e in config["epoch_candidates"]]
    per = {}
    for e in epochs:
        per[e] = {}
        for r in seed_results:
            per_source = [p for f in r["folds"] for p in f["per_epoch"][e]["per_source"]]
            per[e][r["seed"]] = seed_epoch_metrics(per_source)
    # 기존 summary와 재집계 일치(선택 E와 모든 E의 평균 점수)
    again = v2_cal.summarize_dir(seed_results, tuple(config["epoch_candidates"]))
    score_diff = max(abs(again["per_epoch"][e]["mean_score"] - saved["per_epoch"][e]["mean_score"]) for e in epochs)
    own_scores = {e: float(np.mean([per[e][s]["score"] for s in per[e]])) for e in epochs}
    own_vs_saved = max(abs(own_scores[e] - saved["per_epoch"][e]["mean_score"]) for e in epochs)
    check = {"chosen_E_saved": saved["chosen_E"], "chosen_E_recomputed": again["chosen_E"],
             "chosen_E_equal": saved["chosen_E"] == again["chosen_E"],
             "max_abs_mean_score_diff_vs_saved": float(max(score_diff, own_vs_saved)),
             "kinds_inconsistent_total": int(sum(per[e][s]["kinds_inconsistent"] for e in epochs for s in per[e])),
             "verified_as": kind}
    return config, per, saved, check


def aggregate(per_e):
    """seed별 진단 항목을 seed 평균·범위로 요약한다."""
    seeds = sorted(per_e)
    g = lambda key: [per_e[s].get(key, 0) for s in seeds]
    n = [per_e[s]["n_dir"] for s in seeds]
    exposure = [per_e[s]["bg_exposure_ms"] / 60000 for s in seeds]
    return {
        "n_direction_sources": n[0],
        "correct_rate": stat([rate(c, d) for c, d in zip(g("correct"), n)]),
        "missed_rate": stat([rate(c, d) for c, d in zip(g("missed"), n)]),
        "emitted_clip_rate": stat([rate(c, d) for c, d in zip(g("clips_emitted_any"), n)]),
        "early_clip_rate": stat([rate(c, d) for c, d in zip(g("clips_emitted_early"), n)]),
        "emitted_without_correct_clip_rate": stat([rate(c, d) for c, d in zip(g("clips_emitted_without_correct"), n)]),
        "events_per_direction_source": stat([rate(c, d) for c, d in zip(g("events_total"), n)]),
        "counts_mean": {k: float(np.mean(g(k))) for k in
                        ("correct", "missed", "wrong_direction", "duplicate", "early", "late_unmatched",
                         "early_match", "early_mismatch", "window_match", "window_mismatch", "late_match", "late_mismatch",
                         "unmatched", "bg_false")},
        "counts_total_5seeds": {k: int(sum(g(k))) for k in
                                ("early", "early_match", "early_mismatch", "window_match", "window_mismatch",
                                 "late_match", "late_mismatch", "bg_false")},
        "background_false_per_min": stat([rate(f, x) for f, x in zip(g("bg_false"), exposure)]),
        "background_clip_rate_with_false": stat([rate(c, d) for c, d in zip(g("bg_clips_with_false"), g("bg_clips"))]),
        "score": stat([per_e[s]["score"] for s in seeds]),
        "seeds_score_gt_0": int(sum(per_e[s]["score"] > 0 for s in seeds)),
        "seeds_score_lt_0": int(sum(per_e[s]["score"] < 0 for s in seeds)),
        "seeds_score_eq_0": int(sum(per_e[s]["score"] == 0 for s in seeds)),
    }


def paired(per, ea, eb):
    """같은 seed끼리 점수(ea) − 점수(eb)."""
    seeds = sorted(per[ea])
    d = [per[ea][s]["score"] - per[eb][s]["score"] for s in seeds]
    return {"a": ea, "b": eb, "mean_diff": float(np.mean(d)), "per_seed_diff": d,
            "n_up": int(sum(x > 0 for x in d)), "n_down": int(sum(x < 0 for x in d)), "n_equal": int(sum(x == 0 for x in d))}


def reuse_report():
    data, by_path = v2.load_records()
    sp = {n: v2.load_split(n) for n in v2.SPLIT_NAMES}
    validation = {n: {p for f in sp[n]["cv"]["folds"] for p in f["validation_sources"]} for n in sp}
    usage = Counter(p for n in sp for p in validation[n])
    rows = {}
    for n in sp:
        ev = set(sp[n]["eval_sources"])
        others = set().union(*[validation[m] for m in sp if m != n])
        rows[n] = {"eval_sources": len(ev), "overlap_with_own_calibration_validation": len(ev & validation[n]),
                   "overlap_with_other_splits_calibration_validation": len(ev & others),
                   "by_other_split": {m: len(ev & validation[m]) for m in sp if m != n}}
    return {"total_sources": len(by_path), "used_as_validation_in_any_calibration": len(usage),
            "never_used_as_validation": len(set(by_path) - set(usage)),
            "usage_count_histogram": {str(k): v for k, v in sorted(Counter(usage.values()).items())},
            "per_split": rows}


def load_annotations():
    """source_path -> 완료 후보 주석(main_motion_start/end_ms 포함). 주석 파일을 읽기만 한다."""
    ann = {}
    for f in sorted((ROOT / "data/annotations/ble-v2").glob("*-candidates.json")):
        for a in json.loads(f.read_text(encoding="utf-8"))["annotations"]:
            ann[a["source_path"]] = a
    return ann


def completion_gap_report(ann):
    """완료 시각 e와 센서 기반 주동작 종료 시각의 간격(ms). 완료 주석 정의에 따른 지연의 크기와 편차."""
    gap = np.array([a["completion_ms"] - a["main_motion_end_ms"] for a in ann.values()])
    q = np.percentile(gap, [25, 50, 75])
    return {"n": int(len(gap)), "min": int(gap.min()), "p25": float(q[0]), "median": float(q[1]), "p75": float(q[2]), "max": int(gap.max()),
            "n_gap_over_300ms": int((gap > 300).sum())}


def early_position(seed_results, epoch, ann):
    """조기 발행을 주동작 종료 시각 기준으로 나눈다: 동작 중(종료 전) / 종료 후~e 전. 5 seed 합계."""
    during = after = 0
    lead_after = []
    unmatched_ann = 0
    for r in seed_results:
        for f in r["folds"]:
            for p in f["per_epoch"][str(epoch)]["per_source"]:
                a = ann.get(p["source_path"])
                for ev in p["events"]:
                    if ev["kind"] != "early":
                        continue
                    if a is None:
                        unmatched_ann += 1
                        continue
                    if ev["timestamp_ms"] < a["main_motion_end_ms"]:
                        during += 1
                    else:
                        after += 1
                        lead_after.append(a["completion_ms"] - ev["timestamp_ms"])
    total = during + after
    return {"early_total_5seeds": total, "during_motion": during, "after_motion_end_before_e": after,
            "share_after_motion_end": rate(after, total),
            "lead_before_e_ms_median_after": float(np.median(lead_after)) if lead_after else None,
            "events_without_annotation": unmatched_ann}


def pct(x, nd=1):
    return "—" if x is None else f"{100 * x:.{nd}f}%"


def fmt(stat_, f="{:.3f}"):
    return "—" if not stat_ else f"{f.format(stat_['mean'])} [{f.format(stat_['min'])}, {f.format(stat_['max'])}]"


def render(report):
    L = ["# BLE v2 보정 결과 진단", "",
         f"생성: {report['created_kst']}. `ml/v2_diag.py`가 저장된 발행 로그(`results/V2-*-cal/seed-*.json`)와 분할만 읽어 만들었다. "
         "학습·평가를 하지 않았고 기존 파일을 쓰지 않았다. 채점 우선순위(배경 → 조기 → 늦음 → 방향 오류 → 중복 → 정검출)와 선택 점수는 그대로다. "
         "숫자는 5 seed 평균 [최소, 최대]이며 해석은 [README](../../README.md)에 있다.", "",
         "정의: **발행한 클립 비율** = 한 번 이상 발행한 방향 클립 수 ÷ 방향 클립 수(한 클립은 발행이 여러 번이어도 한 번만 센다). "
         "**정검출률** = 정검출한 클립 ÷ 방향 클립. **조기/허용 구간/늦음** = 발행 시각이 완료 e 전 / e~e+500 ms / e+500 ms 후. "
         "**방향 일치** = 발행한 방향이 클립의 정답 방향과 같음. 점수 = (정검출 − 방향 원본 미매칭) ÷ 방향 원본 수.", ""]
    L += ["## 1. 재집계 검사", "", "| 분할 | 기록된 선택 E | 재계산 선택 E | 모든 E 평균 점수 최대 차이 | 기록 kind와 도출 모순 | 검증 방식 |", "|---|---:|---:|---:|---:|---|"]
    for s in SPLITS:
        c = report["runs"][s]["check"]
        L.append(f"| {s} | {c['chosen_E_saved']} | {c['chosen_E_recomputed']} | {c['max_abs_mean_score_diff_vs_saved']:.1e} | {c['kinds_inconsistent_total']} | {c['verified_as']} |")
    L += ["", "## 2. 선택된 E에서의 성능과 발행", ""]
    L += ["| 분할 | 선택 E | 방향 클립 | 정검출률 | 누락률 | 발행한 클립 비율 | 조기 발행이 있는 클립 | 발행했지만 정검출 없는 클립 | 점수 | 점수>0 / <0 / =0 seed |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for s in SPLITS:
        r = report["runs"][s]
        a = r["by_epoch"][str(r["chosen_E"])]
        L.append(f"| {s} | {r['chosen_E']} | {a['n_direction_sources']} | {fmt(a['correct_rate'], '{:.3f}')} | {fmt(a['missed_rate'], '{:.3f}')} | "
                 f"{fmt(a['emitted_clip_rate'], '{:.3f}')} | {fmt(a['early_clip_rate'], '{:.3f}')} | {fmt(a['emitted_without_correct_clip_rate'], '{:.3f}')} | "
                 f"{fmt(a['score'])} | {a['seeds_score_gt_0']} / {a['seeds_score_lt_0']} / {a['seeds_score_eq_0']} |")
    L += ["", "무발행 모델의 점수는 0이다(정검출 0, 미매칭 0). 위 표의 \"점수>0\"은 5 seed 중 무발행보다 나은 seed 수다.", ""]
    L += ["## 3. 발행의 시간 × 방향 (선택된 E, 5 seed 평균 건수)", "",
          "| 분할 | 선택 E | 조기 방향 일치 | 조기 방향 불일치 | 허용 구간 일치(정검출+중복) | 허용 구간 불일치 | 늦음 일치 | 늦음 불일치 | 배경 오발행 | 배경 오발행/분 |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s in SPLITS:
        r = report["runs"][s]
        a = r["by_epoch"][str(r["chosen_E"])]
        c = a["counts_mean"]
        L.append(f"| {s} | {r['chosen_E']} | {c['early_match']:.1f} | {c['early_mismatch']:.1f} | {c['window_match']:.1f} | {c['window_mismatch']:.1f} | "
                 f"{c['late_match']:.1f} | {c['late_mismatch']:.1f} | {c['bg_false']:.1f} | {fmt(a['background_false_per_min'], '{:.2f}')} |")
    L += ["", "조기 발행 안의 방향 불일치는 기존 집계의 `wrong_direction`에 들어가지 않는다(조기 분류가 먼저). 5 seed 합계는 JSON의 `counts_total_5seeds`에 있다.", ""]
    L += ["## 4. 분할별 · epoch별 (5 seed 평균)", ""]
    for s in SPLITS:
        r = report["runs"][s]
        L += [f"### {s} (선택 E={r['chosen_E']})", "", "| E | 점수 | 정검출률 | 발행한 클립 비율 | 조기 일치 | 조기 불일치 | 허용 구간 불일치 | 늦음 | 배경 오발행/분 |", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for e in report["epochs"]:
            a = r["by_epoch"][e]
            c = a["counts_mean"]
            L.append(f"| {e} | {a['score']['mean']:.3f} | {pct(a['correct_rate']['mean'])} | {pct(a['emitted_clip_rate']['mean'])} | {c['early_match']:.1f} | "
                     f"{c['early_mismatch']:.1f} | {c['window_mismatch']:.1f} | {c['late_match'] + c['late_mismatch']:.1f} | {fmt(a['background_false_per_min'], '{:.2f}')} |")
        L.append("")
    L += ["## 5. 같은 seed끼리의 epoch 점수 차이", "", "점수(a) − 점수(b), seed 20261021~25 순. 상승 = 차이 > 0.", "",
          "| 분할 | a − b | 평균 차이 | seed별 차이 | 상승 / 하락 / 동일 |", "|---|---|---:|---|---|"]
    for s in SPLITS:
        for d in report["runs"][s]["paired"]:
            L.append(f"| {s} | E{d['a']} − E{d['b']} | {d['mean_diff']:+.4f} | " + ", ".join(f"{x:+.4f}" for x in d["per_seed_diff"]) +
                     f" | {d['n_up']} / {d['n_down']} / {d['n_equal']} |")
    g = report["completion_gap"]
    L += ["", "## 6. 조기 발행의 위치 (보조 진단)", "",
          "센서 기반 주석(`main_motion_end_ms`)과 기존 발행 로그만 읽었다. 완료 시각 e는 주동작이 끝난 뒤 안정 구간을 확인한 시점이라, "
          "e와 주동작 종료 사이에 간격이 있다. 이 간격이 조기 발행의 분류에 미치는 영향을 본다. **이 값들은 모두 센서에서 계산한 것이며 영상·사용자 확인으로 검증한 정답 시각이 아니다.**", "",
          f"e − 주동작 종료: 방향 원본 {g['n']}개, 최소 {g['min']} ms, 25% {g['p25']:.0f}, 중앙값 {g['median']:.0f}, 75% {g['p75']:.0f}, 최대 {g['max']} ms "
          f"(300 ms 초과 {g['n_gap_over_300ms']}개).", "",
          "| 분할 | E | 조기 발행(5 seed 합) | 주동작 중(종료 전) | 종료 후 ~ e 전 | 종료 후 비율 | 종료 후 발행의 e 전 median(ms) |", "|---|---:|---:|---:|---:|---:|---:|"]
    for row in report["early_position"]:
        L.append(f"| {row['split']} | {row['epoch']} | {row['early_total_5seeds']} | {row['during_motion']} | {row['after_motion_end_before_e']} | "
                 f"{pct(row['share_after_motion_end'], 0)} | {'—' if row['lead_before_e_ms_median_after'] is None else format(row['lead_before_e_ms_median_after'], '.0f')} |")
    L += ["", "## 7. 분할 간 원본 재사용", ""]
    ru = report["reuse"]
    L += [f"전체 원본 {ru['total_sources']}개 중 어느 보정에서든 검증용으로 쓰인 원본 {ru['used_as_validation_in_any_calibration']}개, 한 번도 안 쓰인 원본 {ru['never_used_as_validation']}개. "
          f"검증으로 쓰인 횟수 분포(횟수: 원본 수): {ru['usage_count_histogram']}.", "",
          "| 분할 | 평가용 원본 | 자기 보정 검증과 겹침 | 다른 분할 보정 검증과 겹침 |", "|---|---:|---:|---:|"]
    for n in v2.SPLIT_NAMES:
        x = ru["per_split"][n]
        L.append(f"| {n} | {x['eval_sources']} | {x['overlap_with_own_calibration_validation']} | {x['overlap_with_other_splits_calibration_validation']} |")
    L.append("")
    return "\n".join(L) + "\n"


def main(out_dir):
    out_dir = Path(out_dir)
    targets = [out_dir / "calibration-diagnostics.json", out_dir / "calibration-diagnostics.md"]
    for t in targets:
        if t.exists():
            raise FileExistsError(f"{t}가 이미 있다. 덮어쓰지 않는다")
    report = {"created_kst": now(), "tool": "ml/v2_diag.py", "tool_sha256": digest(ROOT / "ml/v2_diag.py"),
              "input_note": "읽은 파일: results/V2-*-cal/{config,seed-*,summary}.json, data/splits/v2-*.json, records.json. 쓴 파일: 이 폴더뿐",
              "epochs": [str(e) for e in v2.EPOCH_CANDIDATES], "runs": {}}
    for s in SPLITS:
        config, per, saved, check = analyse_run(s)
        by_epoch = {e: aggregate(per[e]) for e in report["epochs"]}
        chosen = str(saved["chosen_E"])
        pairs = [paired(per, chosen, e) for e in report["epochs"] if e != chosen]
        if not any(p["a"] == "60" and p["b"] == "1" for p in pairs):
            pairs.append(paired(per, "60", "1"))     # 모든 분할에서 E60 − E1을 같은 방향으로 보고한다
        report["runs"][s] = {"chosen_E": saved["chosen_E"], "check": check, "by_epoch": by_epoch, "paired": pairs}
    ann = load_annotations()
    report["completion_gap"] = completion_gap_report(ann)
    report["early_position"] = []
    for s in SPLITS:
        _, seed_results, saved, _ = load_run(s)
        for e in sorted({str(saved["chosen_E"]), "1", "60"}, key=int):
            report["early_position"].append({"split": s, "epoch": int(e), "chosen": str(saved["chosen_E"]) == e,
                                             **early_position(seed_results, e, ann)})
    report["reuse"] = reuse_report()
    bad =[s for s in SPLITS if not report["runs"][s]["check"]["chosen_E_equal"]
           or report["runs"][s]["check"]["max_abs_mean_score_diff_vs_saved"] > 1e-12
           or report["runs"][s]["check"]["kinds_inconsistent_total"]]
    dump(targets[0], report)
    targets[1].write_bytes(render(report).encode("utf-8"))
    print("wrote", targets[0], targets[1])
    if bad:
        raise SystemExit(f"재집계 불일치: {bad}")
    print("재집계 일치: 선택 E, 모든 E의 평균 점수, 기록 kind와 도출 분류")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(DOC / "diagnostics/calibration-2026-10-25"))
    main(p.parse_args().out)
