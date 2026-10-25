"""BLE v2 NONE 창의 실제 선택 확인(읽기 전용 분석). 모델을 학습하지 않는다.

사용: ml/.venv/Scripts/python.exe ml/v2_none_review.py [출력 폴더]
  기본 출력: docs/experiments/ble-v2/diagnostics/completion-review-01/none-selection/

각 보정 실행(S-P5, C, S-P1~P4)의 모든 cv fold에서 v2_cal.py가 쓴 학습 창 선택을 그대로 다시 만든다:
  학습 원본 = 분할의 train_sources - fold 검증 원본 -> normalization -> make_chunks -> choose_training(seed=20261021).
검증·평가 원본은 읽지도 않는다. 재현한 창 수·NONE 종류별 수는 results/V2-<split>-cal/config.json과
정확히 같아야 하며, 다르면 즉시 실패한다. 그다음 학습 방향 클립의 NONE 창을 완료 시각 e 기준 구간으로 나누어
고른 수/가능한 수를 센다. 구간은 진단 집계용이며 라벨·성공 기준을 바꾸지 않는다.

세는 규칙: 같은 원본은 여러 fold·분할의 학습 부분에 되풀이해 들어간다. 그래서 모든 합계에 무엇을 세는지
이름을 붙인다. "관측"은 (원본, fold) 쌍이며 서로 독립이 아니다. "고유 원본"은 한 분할 안에서 원본을 한 번만 센다.
이 문서는 분포를 기술할 뿐 원인을 주장하지 않는다.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

import v2

ROOT = v2.ROOT
RESULTS = v2.DOC / "results"
OUT_DIR = v2.DOC / "diagnostics/completion-review-01/none-selection"
OUT_JSON, OUT_MD = "none-selection.json", "none-selection.md"
NONE_SEED = v2.SEED                      # 20261021, 학습 seed와 무관

# e 기준 구간(ms). 라벨이 아니라 집계용이다.
PRE_NEAR_MS, PRE_MID_MS = 300, 600
PRE_BUCKETS = ("pre_0_300", "pre_300_600", "pre_earlier")
DIRECTION_BUCKETS = PRE_BUCKETS + ("post",)
BG_BUCKETS = ("idle", "other")
ALL_BUCKETS = DIRECTION_BUCKETS + BG_BUCKETS
CALIBRATION_SPLITS = ("S-P5", "C", "S-P1", "S-P2", "S-P3", "S-P4")


# ---------------------------------------------------------------- 구간 분류

def bucket_for_offset(dt):
    """e 기준 창 시각 dt = t - e(ms)의 NONE 구간. [0,150)는 양성 구간이라 NONE에 없어야 한다."""
    if dt < -PRE_MID_MS:
        return "pre_earlier"
    if dt < -PRE_NEAR_MS:
        return "pre_300_600"
    if dt < 0:
        return "pre_0_300"
    if dt >= v2.POSITIVE_MS:
        return "post"
    raise ValueError(f"양성 구간 안의 창이 NONE으로 들어왔다: dt={dt}")


def bucket_of_window(record, m):
    e = record["completion_ms"]
    if e is None:
        assert record["kind"] in BG_BUCKETS and m["none_group"] == record["kind"]
        return record["kind"]
    return bucket_for_offset(m["timestamp_ms"] - e)


def clip_row(record, meta, selected):
    """학습 클립 하나의 NONE 창을 구간별로 센다. meta는 이 클립의 창 목록, selected는 같은 길이의 선택 여부."""
    assert len(meta) == len(selected)
    available, picked = Counter(), Counter()
    for m, flag in zip(meta, selected):
        if m["target"] != 0:
            continue
        bucket = bucket_of_window(record, m)
        available[bucket] += 1
        picked[bucket] += int(bool(flag))
    is_direction = record["completion_ms"] is not None
    names = DIRECTION_BUCKETS if is_direction else BG_BUCKETS
    return {"source_path": record["source_path"], "session": record["session"], "direction": record["direction"],
            "kind": "direction" if is_direction else record["kind"], "completion_ms": record["completion_ms"],
            "available": {b: available[b] for b in names}, "selected": {b: picked[b] for b in names}}


def assert_training_only(train_paths, validation, evaluation):
    """학습 목록에 검증·평가 원본이 없고 중복도 없는지 확인한다."""
    train = list(train_paths)
    if len(train) != len(set(train)):
        raise AssertionError("학습 목록에 중복 원본이 있다")
    if set(train) & set(validation):
        raise AssertionError("검증 원본이 학습 목록에 들어왔다")
    if set(train) & set(evaluation):
        raise AssertionError("평가 원본이 학습 목록에 들어왔다")


# ---------------------------------------------------------------- fold 재현

def reproduce_fold(by_path, split, k, root=ROOT):
    """fold k의 학습 부분만 재구성해 NONE 선택을 다시 만든다. v2.fold_sets와 같은 순서(검증 창은 만들지 않는다)."""
    val = set(split["cv"]["folds"][k]["validation_sources"])
    evaluation = set(split["eval_sources"])
    train_paths = [p for p in split["train_sources"] if p not in val]
    assert_training_only(train_paths, val, evaluation)
    train_recs = [by_path[p] for p in train_paths]
    mean, std = v2.normalization(train_recs, root)
    chunks = v2.make_chunks(train_recs, mean, std, root)
    y = np.concatenate([c[2] for c in chunks])
    meta = sum([c[3] for c in chunks], [])
    idx = v2.choose_training(y, meta, NONE_SEED)
    chosen = np.zeros(len(y), dtype=bool)
    chosen[idx] = True
    assert all(meta[i]["source_path"] in set(train_paths) for i in idx), "선택 창이 학습 원본 밖에서 나왔다"
    rows, offset, keys = [], 0, defaultdict(set)
    for record, _, labels, cm in chunks:
        n = len(labels)
        flags = chosen[offset:offset + n].tolist()
        rows.append(clip_row(record, cm, flags))
        for m, flag in zip(cm, flags):
            if flag and m["target"] == 0:
                keys[bucket_of_window(record, m)].add((m["source_path"], m["timestamp_ms"]))
        offset += n
    assert offset == len(y)
    group_available = Counter(m["none_group"] for m, t in zip(meta, y) if t == 0)
    group_selected = Counter(meta[i]["none_group"] for i in idx if y[i] == 0)
    return {"split": split["name"], "fold": k, "train_paths": train_paths, "validation_sources": len(val),
            "windows_all": np.bincount(y, minlength=5).tolist(), "windows_selected": np.bincount(y[idx], minlength=5).tolist(),
            "none_groups_selected": dict(group_selected), "none_groups_available": dict(group_available),
            "rows": rows, "selected_keys": keys}


def check_against_config(fold, config):
    """저장된 config.json의 fold 값과 정확히 일치해야 한다."""
    saved = config["folds"][fold["fold"]]
    pairs = (("train_windows_all", saved["train_windows_all"], fold["windows_all"]),
             ("train_windows_selected", saved["train_windows_selected"], fold["windows_selected"]),
             ("train_none_groups", dict(saved["train_none_groups"]), dict(fold["none_groups_selected"])),
             ("train_sources", saved["train_sources"], len(fold["train_paths"])),
             ("validation_sources", saved["validation_sources"], fold["validation_sources"]))
    for name, expected, got in pairs:
        if expected != got:
            raise AssertionError(f"{fold['split']} fold {fold['fold']}: {name} 불일치 config={expected} 재현={got}")
    return True


def check_bucket_sums(fold):
    """구간 합이 NONE 종류별 전체 수와 같고, 고른 수가 가능한 수를 넘지 않는지 확인한다."""
    total_a, total_s = Counter(), Counter()
    for row in fold["rows"]:
        for b in row["available"]:
            assert row["selected"][b] <= row["available"][b]
            total_a[b] += row["available"][b]
            total_s[b] += row["selected"][b]
    ga, gs = fold["none_groups_available"], fold["none_groups_selected"]
    assert sum(total_a[b] for b in PRE_BUCKETS) == ga.get("in_progress", 0) + ga.get("pre_cue", 0)
    assert sum(total_s[b] for b in PRE_BUCKETS) == gs.get("in_progress", 0) + gs.get("pre_cue", 0)
    assert total_a["post"] == ga.get("post_completion", 0) and total_s["post"] == gs.get("post_completion", 0)
    for b in BG_BUCKETS:
        assert total_a[b] == ga.get(b, 0) and total_s[b] == gs.get(b, 0)
    return True


# ---------------------------------------------------------------- 집계

def tally(rows):
    """행들의 구간별 가능/선택 창 수를 합친다. 행이 (원본, fold) 관측이면 합계도 관측의 합이다."""
    out = {b: {"available": 0, "selected": 0} for b in ALL_BUCKETS}
    for r in rows:
        for b in r["available"]:
            out[b]["available"] += r["available"][b]
            out[b]["selected"] += r["selected"][b]
    for v in out.values():
        v["ratio"] = None if v["available"] == 0 else v["selected"] / v["available"]
    return out


def _share(x, y):
    return None if y == 0 else x / y


def in_progress_share(t):
    """진행 중(복귀 중) NONE 안에서 마지막 300/600 ms 구간의 비중: 가능한 창 vs 고른 창."""
    a = sum(t[b]["available"] for b in PRE_BUCKETS)
    s = sum(t[b]["selected"] for b in PRE_BUCKETS)
    a300, s300 = t["pre_0_300"]["available"], t["pre_0_300"]["selected"]
    a600, s600 = a300 + t["pre_300_600"]["available"], s300 + t["pre_300_600"]["selected"]
    return {"in_progress_available": a, "in_progress_selected": s,
            "last300_available": a300, "last300_selected": s300, "last600_available": a600, "last600_selected": s600,
            "share_available_last300": _share(a300, a), "share_selected_last300": _share(s300, s),
            "share_available_last600": _share(a600, a), "share_selected_last600": _share(s600, s)}


def clip_coverage(rows):
    """진행 중 NONE이 몇 개 클립에서 나왔는지(관측 단위: 한 fold 안의 학습 클립)."""
    d = [r for r in rows if r["kind"] == "direction"]
    picks = [sum(r["selected"][b] for b in PRE_BUCKETS) for r in d]
    return {"direction_clips": len(d), "clips_with_in_progress_available": sum(sum(r["available"][b] for b in PRE_BUCKETS) > 0 for r in d),
            "clips_with_in_progress_pick": sum(v > 0 for v in picks), "max_in_progress_picks_per_clip": max(picks),
            "clips_with_pick_in_0_300": sum(r["selected"]["pre_0_300"] > 0 for r in d),
            "in_progress_picks_per_clip_histogram": histogram(picks, 3)}


def group_rows(rows, key):
    groups = defaultdict(list)
    for r in rows:
        groups[r[key]].append(r)
    return groups


def histogram(values, cap=8):
    c = Counter(min(v, cap) for v in values)
    return {(f"{cap}+" if k == cap else str(k)): c.get(k, 0) for k in range(cap + 1)}


def per_clip_across_folds(folds):
    """한 분할 안에서 원본을 한 번만 센다. 같은 원본이 여러 fold의 학습 부분에 있어도 1개다."""
    per_clip = {}
    for f in folds:
        for r in f["rows"]:
            if r["kind"] != "direction":
                continue
            c = per_clip.setdefault(r["source_path"], {
                "session": r["session"], "direction": r["direction"], "completion_ms": r["completion_ms"],
                "available_0_300": r["available"]["pre_0_300"], "available_in_progress": sum(r["available"][b] for b in PRE_BUCKETS),
                "folds": [], "selected_0_300": [], "selected_in_progress": []})
            assert c["available_0_300"] == r["available"]["pre_0_300"]
            c["folds"].append(f["fold"])
            c["selected_0_300"].append(r["selected"]["pre_0_300"])
            c["selected_in_progress"].append(sum(r["selected"][b] for b in PRE_BUCKETS))
    return per_clip


def unique_clip_summary(per_clip):
    clips = list(per_clip.values())
    never = [c for c in clips if all(v == 0 for v in c["selected_0_300"])]
    some = [c for c in clips if any(v == 0 for v in c["selected_0_300"])]
    never_ip = [c for c in clips if all(v == 0 for v in c["selected_in_progress"])]
    count = lambda cs, key: dict(sorted(Counter(c[key] for c in cs).items()))
    return {
        "unique_direction_clips": len(clips),
        "clips_with_zero_available_in_0_300": sum(c["available_0_300"] == 0 for c in clips),
        "clips_zero_picks_in_every_training_fold": len(never),
        "clips_zero_picks_in_every_training_fold_with_available": sum(c["available_0_300"] > 0 for c in never),
        "clips_zero_picks_in_at_least_one_training_fold": len(some),
        "clips_zero_picks_in_at_least_one_training_fold_with_available": sum(c["available_0_300"] > 0 for c in some),
        "unique_clips_by_session": count(clips, "session"),
        "zero_every_fold_by_session": count(never, "session"),
        "zero_every_fold_by_direction": count(never, "direction"),
        "zero_every_fold_with_available_by_session": count([c for c in never if c["available_0_300"] > 0], "session"),
        "available_0_300_per_clip_histogram": histogram([c["available_0_300"] for c in clips]),
        "clips_zero_in_progress_picks_in_every_training_fold": len(never_ip),
        "zero_in_progress_every_fold_by_session": count(never_ip, "session"),
        "clips_with_in_progress_pick_in_some_fold_by_session": count([c for c in clips if any(v > 0 for v in c["selected_in_progress"])], "session"),
    }


def unique_window_counts(folds):
    """구간별 고유 창 수: 학습에 한 번이라도 들어간 원본의 가능한 창, 어느 fold에서든 한 번이라도 고른 창."""
    seen = {}
    union = defaultdict(set)
    for f in folds:
        for r in f["rows"]:
            seen[r["source_path"]] = r
        for b, s in f["selected_keys"].items():
            union[b] |= s
    t = tally(seen.values())
    return ({b: t[b]["available"] for b in ALL_BUCKETS}, {b: len(union[b]) for b in ALL_BUCKETS})


def split_view(folds):
    all_rows = [r for f in folds for r in f["rows"]]
    direction_rows = [r for r in all_rows if r["kind"] == "direction"]
    obs = tally(all_rows)
    zero_obs = [r for r in direction_rows if r["selected"]["pre_0_300"] == 0]
    per_clip = per_clip_across_folds(folds)
    uni_available, uni_selected = unique_window_counts(folds)
    view = {
        "fold_observations": {
            "meaning": "(원본, fold) 관측의 합. 같은 원본·창이 여러 fold에 되풀이되므로 독립 표본 수가 아니다",
            "n_fold_observations_direction_clips": len(direction_rows),
            "tally": obs, "in_progress_share": in_progress_share(obs),
            "by_session": {s: {"tally": tally(rs), "in_progress_share": in_progress_share(tally(rs))}
                           for s, rs in sorted(group_rows(all_rows, "session").items())},
            "by_direction": {d: {"tally": tally(rs), "in_progress_share": in_progress_share(tally(rs))}
                             for d, rs in sorted(group_rows(direction_rows, "direction").items())},
            "zero_picks_in_0_300": {
                "meaning": "(원본, fold) 관측 중 [-300,0)에서 고른 창이 0개인 관측 수",
                "observations": len(zero_obs), "of_observations": len(direction_rows),
                "observations_with_available": sum(r["available"]["pre_0_300"] > 0 for r in zero_obs),
                "by_session": dict(sorted(Counter(r["session"] for r in zero_obs).items())),
                "by_direction": dict(sorted(Counter(r["direction"] for r in zero_obs).items())),
                "available_0_300_per_observation_histogram": histogram([r["available"]["pre_0_300"] for r in direction_rows]),
                "selected_0_300_per_observation_histogram": histogram([r["selected"]["pre_0_300"] for r in direction_rows])},
        },
        "unique_clips": {
            "meaning": "분할 안에서 원본을 한 번만 센 뷰(학습에 한 번이라도 들어간 원본). 가능 창은 원본당 한 번, "
                       "고른 창은 어느 fold에서든 한 번이라도 고른 고유 창",
            **unique_clip_summary(per_clip),
            "windows_available_unique": uni_available, "windows_selected_in_any_fold_unique": uni_selected},
    }
    return view, per_clip


def merge_clip_table(per_clip_by_split):
    """고유 원본별 표: 가능 창은 원본당 하나, 분할별로 학습 fold와 그 fold에서 고른 [-300,0) 창 수."""
    clips = {}
    for split, pc in per_clip_by_split.items():
        for p, c in pc.items():
            row = clips.setdefault(p, {"session": c["session"], "direction": c["direction"], "completion_ms": c["completion_ms"],
                                       "available_0_300": c["available_0_300"], "by_split": {}})
            assert row["available_0_300"] == c["available_0_300"]
            row["by_split"][split] = {"training_folds": c["folds"], "selected_0_300_per_fold": c["selected_0_300"]}
    return dict(sorted(clips.items()))


# ---------------------------------------------------------------- 전체 실행

def load_config(name):
    return json.loads((RESULTS / f"V2-{name}-cal/config.json").read_text(encoding="utf-8"))


def build_report(splits=CALIBRATION_SPLITS, root=ROOT, fold_limit=None):
    """고정 입력에서 결정적으로 계산한다(시각 정보 없음)."""
    data, by_path = v2.load_records()
    split_out, per_clip_by_split, fold_log = {}, {}, []
    for name in splits:
        split = v2.load_split(name)
        config = load_config(name)
        if config["split"] != name or config["split_sha256"] != v2.digest(v2.SPLITS / f"v2-{name}.json"):
            raise AssertionError(f"{name}: config의 분할 해시가 다르다")
        if config["n_folds"] != split["cv"]["n_folds"] or config["records_sha256"] != v2.digest(v2.RECORDS):
            raise AssertionError(f"{name}: config의 fold 수 또는 records 해시가 다르다")
        folds = []
        for k in range(split["cv"]["n_folds"] if fold_limit is None else min(fold_limit, split["cv"]["n_folds"])):
            f = reproduce_fold(by_path, split, k, root)
            check_against_config(f, config)
            check_bucket_sums(f)
            folds.append(f)
            t = tally(f["rows"])
            fold_log.append({"split": name, "fold": k, "config_match": True,
                             "held_out_session": split["cv"]["folds"][k].get("held_out_session"),
                             "train_sources": len(f["train_paths"]), "validation_sources": f["validation_sources"],
                             "windows_all": f["windows_all"], "windows_selected": f["windows_selected"],
                             "none_groups_selected": f["none_groups_selected"], "none_groups_available": f["none_groups_available"],
                             "tally": t, "in_progress_share": in_progress_share(t),
                             "in_progress_clip_coverage": clip_coverage(f["rows"]),
                             "zero_picks_in_0_300": sum(r["selected"]["pre_0_300"] == 0 for r in f["rows"] if r["kind"] == "direction"),
                             "direction_clips": sum(r["kind"] == "direction" for r in f["rows"])})
        view, per_clip = split_view(folds)
        split_out[name] = view
        per_clip_by_split[name] = per_clip
    clips = merge_clip_table(per_clip_by_split)
    return {
        "version": "none-selection-v1",
        "purpose": "실제 학습 fold에서 choose_training()이 고른 NONE 창의 시간 구간별 분포(기술 통계). 모델 학습 없음",
        "none_selection_seed": NONE_SEED,
        "selector": "NONE 종류(idle, in_progress, other, post_completion, pre_cue; 이름순)를 한 개씩 돌아가며 뽑고, 종류 안에서는 원본 파일을 "
                    "이름순으로 돌아가며 각 파일의 창을 seed로 섞은 순서대로 한 개씩 뽑는다. 양성 창 수에 닿으면 멈춘다. "
                    "pre_cue는 첫 판정 1590 ms가 큐 1000 ms보다 늦어 창이 없다",
        "buckets": {"pre_0_300": "e 기준 [-300,0) ms", "pre_300_600": "[-600,-300) ms", "pre_earlier": "-600 ms보다 이른 NONE(진행 중)",
                    "post": "t >= e+150 (e~e+150는 양성)", "idle": "idle 클립 전체", "other": "other 클립 전체"},
        "counting_rule": "같은 원본이 여러 fold·분할의 학습 부분에 되풀이된다. fold_observations 합계는 (원본, fold) 관측의 합이며 독립 표본이 아니다. "
                         "unique_clips 뷰는 분할 안에서 원본을 한 번만 센다. 서로 다른 분할의 값은 합하지 않는다",
        "inputs": {"records_sha256": v2.digest(v2.RECORDS), "code_sha256": {"v2.py": v2.digest(ROOT / "ml/v2.py")},
                   "split_sha256": {n: v2.digest(v2.SPLITS / f"v2-{n}.json") for n in splits},
                   "config_sha256": {n: v2.digest(RESULTS / f"V2-{n}-cal/config.json") for n in splits}},
        "config_match": {"folds_checked": len(fold_log), "all_match": all(f["config_match"] for f in fold_log),
                         "checked_fields": ["train_windows_all", "train_windows_selected", "train_none_groups", "train_sources", "validation_sources"]},
        "folds": fold_log, "splits": split_out,
        "distinct_direction_clips_in_any_training": len(clips),
        "available_0_300_distinct_clip_histogram": histogram([c["available_0_300"] for c in clips.values()]),
        "clips": clips,
    }


# ---------------------------------------------------------------- 보고서 문서

BUCKET_NAME = {"pre_0_300": "[-300,0) ms", "pre_300_600": "[-600,-300) ms", "pre_earlier": "< -600 ms (진행 중)",
               "post": "완료 후 t>=e+150", "idle": "idle 클립", "other": "other 클립"}


def pct(x, digits=1):
    return "-" if x is None else f"{100 * x:.{digits}f}%"


def compact(hist):
    """0이 아닌 칸만 '창 수: 개수' 형태로 보여 준다."""
    return ", ".join(f"{k}: {v}" for k, v in hist.items() if v) or "-"


def tally_table(t):
    lines = ["| 구간 | 가능한 창 | 고른 창 | 선택 비율 |", "|---|---:|---:|---:|"]
    for b in ALL_BUCKETS:
        v = t[b]
        lines.append(f"| {BUCKET_NAME[b]} | {v['available']} | {v['selected']} | {pct(v['ratio'])} |")
    return lines


def render_markdown(report):
    L = []
    add = L.append
    folds = report["folds"]
    cov = [f["in_progress_clip_coverage"] for f in folds]
    add("# NONE 창의 실제 선택 확인 (학습 부분만, 기술 통계)")
    add("")
    add(f"> 생성: {report.get('created_kst', '-')} / 도구: `ml/v2_none_review.py` / 모델 학습 없음. "
        "이 문서는 `choose_training()`이 실제로 고른 NONE 창의 시간 분포를 센 것이며 원인을 주장하지 않는다. "
        "구간은 진단 집계용이고 라벨·성공 기준·선택 규칙을 바꾸지 않는다.")
    add("")
    add("## 1. 무엇을 세었나")
    add("")
    add(f"- 대상: 보정 실행 6개(S-P5, C, S-P1, S-P2, S-P3, S-P4)의 모든 cv fold({len(folds)}개). 학습 부분(분할 학습 원본 - fold 검증 원본)만 사용했다. "
        "검증·평가 원본은 읽지 않았고 학습 목록에 없음을 확인했다.")
    add("- 재현: `normalization` -> `make_chunks` -> `choose_training(seed=20261021)`. NONE 선택 seed는 고정이라 학습 seed와 무관하다.")
    cm = report["config_match"]
    add("- config 대조: `results/V2-<split>-cal/config.json`의 `train_windows_all`, `train_windows_selected`, `train_none_groups`, `train_sources`, "
        f"`validation_sources`와 {cm['folds_checked']}개 fold 모두 정확히 일치했다(일치 여부: {cm['all_match']}). 하나라도 다르면 실행이 중단된다.")
    add("- 구간(방향 클립의 NONE 창, 창 시각 t의 e 기준 위치): `[-300,0)`, `[-600,-300)`, `-600보다 이른 진행 중`, `완료 후(t>=e+150)`. "
        "`[e,e+150)`는 양성이라 NONE에 없다. idle·other 클립은 따로 센다.")
    add("- **세는 규칙**: 같은 원본은 여러 fold와 여러 분할의 학습 부분에 되풀이해 들어간다. "
        "아래 `관측`은 (원본, fold) 쌍의 합이며 독립 표본 수가 아니다. `고유 원본`은 한 분할 안에서 원본을 한 번만 센다. 서로 다른 분할의 값은 합하지 않는다.")
    add("")
    add("## 2. 선택기가 실제로 하는 일")
    add("")
    add("`choose_training()`은 양성 창 수만큼 NONE을 뽑는다. NONE 종류(idle, in_progress, other, post_completion, pre_cue; 이름순)를 한 개씩 돌아가며, "
        "종류 안에서는 `source_path` 이름순으로 파일을 한 바퀴씩 돌며 각 파일의 창을 seed로 섞은 순서대로 한 개씩 뽑는다. "
        "pre_cue 창은 첫 판정 시각(1590 ms)이 큐(1000 ms)보다 늦어 존재하지 않는다.")
    add("")
    add(f"- {len(folds)}개 fold에서 진행 중(in_progress) 선택은 fold당 {min(f['in_progress_share']['in_progress_selected'] for f in folds)}~"
        f"{max(f['in_progress_share']['in_progress_selected'] for f in folds)}개이고, 진행 중 창이 있는 학습 방향 클립은 fold당 "
        f"{min(c['clips_with_in_progress_available'] for c in cov)}~{max(c['clips_with_in_progress_available'] for c in cov)}개다. "
        f"한 클립에서 뽑힌 진행 중 창은 많아야 {max(c['max_in_progress_picks_per_clip'] for c in cov)}개였다.")
    add("- 선택 수가 클립 수보다 적으면 한 바퀴(클립당 1개)를 다 돌기 전에 개수가 차므로 이름순에서 뒤쪽인 클립에서는 진행 중 창이 뽑히지 않는다. "
        f"fold당 진행 중 창이 뽑힌 클립은 {min(c['clips_with_in_progress_pick'] for c in cov)}~{max(c['clips_with_in_progress_pick'] for c in cov)}개이고, "
        f"그중 `[-300,0)`에서 뽑힌 클립은 {min(c['clips_with_pick_in_0_300'] for c in cov)}~{max(c['clips_with_pick_in_0_300'] for c in cov)}개다.")
    add("")
    add("진행 중 창이 한 번이라도 뽑힌 고유 원본 / 그 분할의 고유 원본 (세션별, 분할 안에서 원본을 한 번씩 센 값):")
    add("")
    sessions = v2.SESSION_KEYS
    add("| 분할 | " + " | ".join(sessions) + " |")
    add("|---|" + "---:|" * len(sessions))
    for name, sv in report["splits"].items():
        u = sv["unique_clips"]
        add(f"| {name} | " + " | ".join(f"{u['clips_with_in_progress_pick_in_some_fold_by_session'].get(s, 0)}/{u['unique_clips_by_session'].get(s, 0)}"
                                         for s in sessions) + " |")
    add("")
    add("## 3. 진행 중 NONE 선택의 위치: 마지막 300/600 ms 비중")
    add("")
    add("진행 중(복귀 중) NONE 창 중 e 직전 300 ms 또는 600 ms에 있는 창의 비중을 `가능한 창`(진행 중 안에서 균등하게 뽑았을 때의 기대 비중)과 "
        "`고른 창`으로 비교한다. (원본, fold) 관측의 합이며 괄호는 fold별 값의 최소~최대다.")
    add("")
    add("| 분할 | 진행 중 가능 | 진행 중 고른 | 마지막 300 ms 가능 비중 | 마지막 300 ms 고른 비중 | 마지막 600 ms 가능 비중 | 마지막 600 ms 고른 비중 |")
    add("|---|---:|---:|---|---|---|---|")
    for name, sv in report["splits"].items():
        s = sv["fold_observations"]["in_progress_share"]
        fs = [f["in_progress_share"] for f in folds if f["split"] == name]
        rng = lambda key: f"{pct(min(x[key] for x in fs))}~{pct(max(x[key] for x in fs))}"
        add(f"| {name} | {s['in_progress_available']} | {s['in_progress_selected']} | {pct(s['share_available_last300'])} ({rng('share_available_last300')}) | "
            f"{pct(s['share_selected_last300'])} ({rng('share_selected_last300')}) | {pct(s['share_available_last600'])} ({rng('share_available_last600')}) | "
            f"{pct(s['share_selected_last600'])} ({rng('share_selected_last600')}) |")
    add("")
    add("## 4. 분할별 구간 표")
    add("")
    for name, sv in report["splits"].items():
        fo = sv["fold_observations"]
        add(f"### {name} - (원본, fold) 관측 {fo['n_fold_observations_direction_clips']}개의 합 (독립 아님)")
        add("")
        L.extend(tally_table(fo["tally"]))
        add("")
        uc = sv["unique_clips"]
        add(f"고유 원본 뷰({uc['unique_direction_clips']}개 방향 원본): 가능한 창(원본당 1회)과 어느 fold에서든 한 번이라도 고른 고유 창")
        add("")
        add("| 구간 | 고유 가능 창 | 한 번이라도 고른 고유 창 |")
        add("|---|---:|---:|")
        for b in ALL_BUCKETS:
            add(f"| {BUCKET_NAME[b]} | {uc['windows_available_unique'][b]} | {uc['windows_selected_in_any_fold_unique'][b]} |")
        add("")
    add("## 5. 세션별·방향별 (관측 합계, 고른/가능)")
    add("")
    for name, sv in report["splits"].items():
        fo = sv["fold_observations"]
        add(f"### {name}")
        add("")
        add("| 세션 | " + " | ".join(BUCKET_NAME[b] for b in ALL_BUCKETS) + " |")
        add("|---|" + "---:|" * len(ALL_BUCKETS))
        for s, v in fo["by_session"].items():
            add(f"| {s} | " + " | ".join(f"{v['tally'][b]['selected']}/{v['tally'][b]['available']}" for b in ALL_BUCKETS) + " |")
        add("")
        add("| 방향 | " + " | ".join(BUCKET_NAME[b] for b in DIRECTION_BUCKETS) + " |")
        add("|---|" + "---:|" * len(DIRECTION_BUCKETS))
        for d, v in fo["by_direction"].items():
            add(f"| {d} | " + " | ".join(f"{v['tally'][b]['selected']}/{v['tally'][b]['available']}" for b in DIRECTION_BUCKETS) + " |")
        add("")
    add("## 6. 클립별 `[-300,0)` 선택: 하나도 고르지 않은 클립")
    add("")
    add("관측 뷰는 (원본, fold) 관측을 센 것이고, 고유 원본 뷰는 분할 안에서 원본을 한 번씩만 센 것이다. 분할 사이에서 합산하지 않는다.")
    add("")
    add("| 분할 | 관측 중 0개 선택 | 관측 수 | 고유 원본 | 모든 학습 fold에서 0개 선택 | 한 fold 이상에서 0개 선택 | 모든 fold 0개 중 가능 창 없음 |")
    add("|---|---:|---:|---:|---:|---:|---:|")
    for name, sv in report["splits"].items():
        z, u = sv["fold_observations"]["zero_picks_in_0_300"], sv["unique_clips"]
        no_avail = u["clips_zero_picks_in_every_training_fold"] - u["clips_zero_picks_in_every_training_fold_with_available"]
        add(f"| {name} | {z['observations']} | {z['of_observations']} | {u['unique_direction_clips']} | {u['clips_zero_picks_in_every_training_fold']} | "
            f"{u['clips_zero_picks_in_at_least_one_training_fold']} | {no_avail} |")
    add("")
    add("### 세션 분포: 모든 학습 fold에서 `[-300,0)`을 0개 고른 고유 원본 / 그 분할의 고유 원본")
    add("")
    add("| 분할 | " + " | ".join(sessions) + " |")
    add("|---|" + "---:|" * len(sessions))
    for name, sv in report["splits"].items():
        u = sv["unique_clips"]
        add(f"| {name} | " + " | ".join(f"{u['zero_every_fold_by_session'].get(s, 0)}/{u['unique_clips_by_session'].get(s, 0)}" for s in sessions) + " |")
    add("")
    add("### 세션 분포: (원본, fold) 관측 중 `[-300,0)`을 0개 고른 관측 수")
    add("")
    add("| 분할 | " + " | ".join(sessions) + " |")
    add("|---|" + "---:|" * len(sessions))
    for name, sv in report["splits"].items():
        z = sv["fold_observations"]["zero_picks_in_0_300"]
        add(f"| {name} | " + " | ".join(str(z["by_session"].get(s, 0)) for s in sessions) + " |")
    add("")
    add("### 클립당 `[-300,0)` 가능한 창 수와 고른 창 수의 분포")
    add("")
    add(f"방향 원본 {report['distinct_direction_clips_in_any_training']}개(어느 분할의 학습에든 들어간 고유 원본)의 가능 창 수 분포: "
        f"{compact(report['available_0_300_distinct_clip_histogram'])} (창 수: 클립 수). "
        "창 간격이 50 ms라 `[-300,0)`에는 최대 6개가 들어간다. 관측당 분포는 아래 표.")
    add("")
    add("| 분할 | 관측당 가능 창 수 분포 | 관측당 고른 창 수 분포 |")
    add("|---|---|---|")
    for name, sv in report["splits"].items():
        z = sv["fold_observations"]["zero_picks_in_0_300"]
        add(f"| {name} | {compact(z['available_0_300_per_observation_histogram'])} | {compact(z['selected_0_300_per_observation_histogram'])} |")
    add("")
    add("## 7. fold별 요약")
    add("")
    add("| 분할 | fold | 학습 원본 | 양성 창 | 진행 중 고른 | 마지막 300 ms 가능/고른 | 마지막 600 ms 가능/고른 | 진행 중 창이 뽑힌 클립 | `[-300,0)` 0개 클립 / 방향 클립 |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for f in folds:
        s, c = f["in_progress_share"], f["in_progress_clip_coverage"]
        add(f"| {f['split']} | {f['fold']} | {f['train_sources']} | {sum(f['windows_all'][1:])} | {s['in_progress_selected']} | "
            f"{s['last300_available']}/{s['last300_selected']} | {s['last600_available']}/{s['last600_selected']} | "
            f"{c['clips_with_in_progress_pick']} | {f['zero_picks_in_0_300']} / {f['direction_clips']} |")
    add("")
    add("## 8. 해석 한계")
    add("")
    add("- 이 문서는 학습 창 선택 분포의 기술이다. 이 분포가 조기 발행이나 다른 성능 현상의 원인이라는 근거를 제공하지 않는다.")
    add("- 구간(300/600 ms)은 이 진단을 위한 집계 경계이며 라벨·성공 기준과 무관하다.")
    add("- 같은 원본은 여러 fold와 분할에서 되풀이해 관측된다. 관측 합계를 독립 표본 수로 읽으면 안 된다.")
    add("- 완료 시각 e는 센서 기반 자동 후보이며 영상·사용자 확인이 없다. 구간은 그 e 기준이다.")
    return "\n".join(L) + "\n"


def write_outputs(report, out_dir=OUT_DIR):
    """기존 출력은 덮어쓰지 않는다. 둘 중 하나라도 있으면 아무것도 쓰지 않고 실패한다."""
    out_dir = Path(out_dir)
    targets = [out_dir / OUT_JSON, out_dir / OUT_MD]
    for t in targets:
        if t.exists():
            raise FileExistsError(f"{t.name}이 이미 있다. 덮어쓰지 않는다")
    out_dir.mkdir(parents=True, exist_ok=True)
    report = dict(report, created_kst=v2.now())
    text = json.dumps(report, ensure_ascii=False, indent=1, allow_nan=False) + "\n"
    with open(targets[0], "xb") as f:
        f.write(text.encode("utf-8"))
    with open(targets[1], "xb") as f:
        f.write(render_markdown(report).encode("utf-8"))
    return targets


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    out_dir = Path(argv[0]) if argv else OUT_DIR
    for name in (OUT_JSON, OUT_MD):
        if (out_dir / name).exists():
            raise FileExistsError(f"{out_dir / name}이 이미 있다. 덮어쓰지 않는다")
    report = build_report()
    for t in write_outputs(report, out_dir):
        print("saved", t)
    print("config match:", report["config_match"])


if __name__ == "__main__":
    main()
