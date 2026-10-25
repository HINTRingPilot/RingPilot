"""고정 protocol의 NONE 배분 실험을 기존 기준선과 같은 seed끼리 비교한다."""
import argparse
from pathlib import Path

import numpy as np

import v2
import v2_cal
import v2_none_cal as cal
import v2_protected_manifest as protected

EPS = 1e-12


def classify_change(delta):
    keys = ("score", "correct_rate", "early_clip_rate", "unmatched_per_source")
    if all(abs(delta[k]) <= EPS for k in keys):
        return "관측값 동일"
    if delta["score"] > EPS and delta["correct_rate"] >= -EPS and delta["early_clip_rate"] <= EPS and delta["unmatched_per_source"] <= EPS:
        return "개발용 개선 관찰"
    if delta["score"] < -EPS and delta["correct_rate"] <= EPS and delta["early_clip_rate"] >= -EPS and delta["unmatched_per_source"] >= -EPS:
        return "개발용 악화 관찰"
    return "지표 간 교환관계"


def paired_metrics(old, new):
    if set(old) != set(new) or not old:
        raise ValueError("같은 seed 목록이 필요하다")
    seeds = sorted(old)
    keys = set(old[seeds[0]])
    if any(set(old[s]) != keys or set(new[s]) != keys for s in seeds):
        raise ValueError("비교 지표 목록이 다르다")
    out = {}
    for key in sorted(keys):
        diffs = [new[s][key] - old[s][key] for s in seeds]
        out[key] = {"mean": float(np.mean(diffs)), "min": float(min(diffs)), "max": float(max(diffs)),
                    "up": sum(x > EPS for x in diffs), "down": sum(x < -EPS for x in diffs),
                    "equal": sum(abs(x) <= EPS for x in diffs),
                    "per_seed": {str(s): float(d) for s, d in zip(seeds, diffs)}}
    return out


def source_metrics(rows):
    directional = [p for p in rows if p["completion_ms"] is not None]
    background = [p for p in rows if p["completion_ms"] is None]
    n = len(directional)
    if not n:
        raise ValueError("방향 원본 없는 집계")
    correct = sum(p["counts"].get("correct", 0) for p in directional)
    unmatched = sum(sum(p["counts"].get(k, 0) for k in ("early", "wrong_direction", "duplicate", "late_unmatched")) for p in directional)
    early = sum(any(ev["kind"] == "early" for ev in p["events"]) for p in directional)
    exposure = sum(p["rows"] * .01 - v2.FIRST_T / 1000 for p in background)
    if not exposure:
        raise ValueError("배경 관측 구간 없는 집계")
    return {"score": (correct - unmatched) / n, "correct_rate": correct / n,
            "early_clip_rate": early / n, "unmatched_per_source": unmatched / n,
            "no_emit_rate": sum(not p["events"] for p in directional) / n,
            "background_false_per_min": sum(len(p["events"]) for p in background) * 60 / exposure}


def seed_metrics(results, epoch, session=None):
    out = {}
    for r in results:
        rows = [p for f in r["folds"] for p in f["per_epoch"][str(epoch)]["per_source"]
                if session is None or p["session"] == session]
        out[r["seed"]] = source_metrics(rows)
    return out


def make_pair(old_results, new_results, old_e, new_e, session=None):
    old, new = seed_metrics(old_results, old_e, session), seed_metrics(new_results, new_e, session)
    paired = paired_metrics(old, new)
    means = lambda values: {k: float(np.mean([m[k] for m in values.values()])) for k in next(iter(values.values()))}
    return {"baseline_E": int(old_e), "balanced_E": int(new_e),
            "baseline_mean": means(old), "balanced_mean": means(new),
            "baseline_per_seed": {str(s): m for s, m in old.items()},
            "balanced_per_seed": {str(s): m for s, m in new.items()},
            "paired": paired, "description": classify_change({k: p["mean"] for k, p in paired.items()})}


def compare(protocol_path):
    p = cal.read(protocol_path)
    report = {"created_kst": v2.now(), "protocol_sha256": v2.digest(protocol_path),
              "data_role": "development_diagnostic", "rule": p["spec"]["comparison"], "splits": {}}
    for split_name in p["spec"]["execution_order"]:
        cal.verify_run(protocol_path, split_name)
        _, cfg, out, _ = cal.load_state(protocol_path, split_name)
        new = v2_cal.load_seed_results(out, cfg)
        new_summary = cal.read(out / "summary.json")
        old_dir = v2.DOC / "results" / f"V2-{split_name}-cal"
        old_cfg = cal.read(old_dir / "config.json")
        old = v2_cal.load_seed_results(old_dir, old_cfg)
        old_summary = cal.read(old_dir / "summary.json")
        _, issues = v2_cal.check_results(old_cfg, split_name, old)
        v2_cal.raise_issues("기준선 결과 불일치", issues)
        old_e, new_e = old_summary["chosen_E"], new_summary["chosen_E"]
        primary = make_pair(old, new, old_e, new_e)
        sessions = sorted({item["session"] for f in old[0]["folds"] for item in f["per_epoch"][str(old_e)]["per_source"]})
        report["splits"][split_name] = {
            "selected_E": primary,
            "common_E": {str(e): make_pair(old, new, e, e) for e in cfg["epoch_candidates"]},
            "per_session_at_selected_E": {s: make_pair(old, new, old_e, new_e, s) for s in sessions},
            "selection_balance": {str(f["fold"]): f["kind_session_counts"] for f in cfg["folds"]},
        }
    return report


def render(report):
    lines = ["# NONE 세션·클립 배분 비교", "", f"작성: {report['created_kst']}", "",
             "기존 336개 원본 안의 개발용 보정 비교다. 독립 최종 평가·실사용 성능이 아니다. 원래 기준선과 같은 학습·발행·채점 경로를 쓰고 NONE의 종류 안 배분만 바꿨다.", "",
             "## 각 전략의 선택 E 비교", "",
             "같은 E 선택 원칙을 각각 적용한 뒤 같은 seed끼리 비교했다. Δ는 새 배분 − 기준선이다. seed 방향 개수는 기술 통계이며 유의성·동등성 판정이 아니다.", "",
             "| 분할 | E 기존→새 | 정검출률 기존→새 | 점수 Δ | 조기 발행 클립 비율 Δ(pp) | 점수 상승/하락/동일 seed | 기술 판단 |",
             "|---|---|---|---:|---:|---|---|"]
    for name, row in report["splits"].items():
        t = row["selected_E"]
        a, b, delta = t["baseline_mean"], t["balanced_mean"], t["paired"]
        score = delta["score"]
        lines.append(f"| {name} | {t['baseline_E']}→{t['balanced_E']} | {a['correct_rate']*100:.1f}%→{b['correct_rate']*100:.1f}% | {score['mean']:+.4f} | {delta['early_clip_rate']['mean']*100:+.1f} | {score['up']}/{score['down']}/{score['equal']} | {t['description']} |")
    for name, row in report["splits"].items():
        lines += ["", f"## {name}: 같은 E의 대응 비교", "",
                  "| E | 점수 Δ | 정검출률 Δ(pp) | 조기 발행 클립 Δ(pp) | 미매칭/원본 Δ | 배경/분 Δ | 점수 상승/하락/동일 |",
                  "|---|---:|---:|---:|---:|---:|---|"]
        for e, t in row["common_E"].items():
            d = t["paired"]
            z = d["score"]
            lines.append(f"| {e} | {z['mean']:+.4f} | {d['correct_rate']['mean']*100:+.1f} | {d['early_clip_rate']['mean']*100:+.1f} | {d['unmatched_per_source']['mean']:+.4f} | {d['background_false_per_min']['mean']:+.2f} | {z['up']}/{z['down']}/{z['equal']} |")
    lines += ["", "## 해석 한계", "",
              "- 같은 클립이 seed/fold/분할에 반복되므로 독립 표본 수로 합산하지 않는다.",
              "- 배경 오발행은 선택 점수에 포함하지 않고 별도 보고한다.",
              "- 세션별 결과와 모든 seed의 원시 지표·대응 차이는 comparison.json에 있다.",
              "- 모델·정답 시각·양성 폭·NONE 총수와 종류별 수·후처리·선택 점수는 유지했다.",
              "- 기본 선택기를 자동 교체하지 않는다. 영상 관찰과 독립 평가 자료 수집은 별도 작업이다.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    args = parser.parse_args()
    json_path, md_path = args.protocol.parent / "comparison.json", args.protocol.parent / "comparison.md"
    if json_path.exists() or md_path.exists():
        raise FileExistsError("비교 결과는 덮어쓰지 않는다")
    result = compare(args.protocol)
    protected.write_new(json_path, result)
    with md_path.open("x", encoding="utf-8", newline="\n") as f:
        f.write(render(result))
    print("comparison saved:", md_path)
