"""BLE v2 완료 시각 검토 (작업 B): 표본 고정, 파형·점수·발행 그림, 집계.

저장된 센서 CSV, 예측 배열(npz), 발행 로그(seed-*.json), 분할만 읽는다. 학습·추론을 하지 않고
기존 파일을 쓰지 않는다(출력은 새 폴더에만, 이미 있으면 거부).

  ml/.venv/Scripts/python.exe ml/v2_completion_review.py sample [--out DIR]
  ml/.venv/Scripts/python.exe ml/v2_completion_review.py report  [--out DIR]

  sample  표본 규칙·rng·해시를 sample-manifest.json에 먼저 저장한다(그림은 그리지 않는다).
  report  manifest를 읽어 표본마다 SVG를 그리고 report.html, summary.json, summary.md를 쓴다.

계획: docs/superpowers/plans/2026-10-25-v2-completion-validation.md 작업 B.
주의: 완료 시각 e와 main_motion_end_ms는 같은 자동 센서 도구(tools/suggest-gesture-completions.js)에서
나왔다. 발행 시점이 e와 어떻게 놓이는지는 이 도구의 결과를 읽는 것이지 실제 자연 복귀 완료의 독립
증거가 아니다. 표본의 비율은 성능 추정치가 아니다.
"""

import argparse
import html
import json
import platform
import sys
from collections import Counter
from pathlib import Path

import numpy as np

import v2
from v2 import AXES, CLASSES, DIRECTIONS, DOC, ROOT, SESSION_KEYS, digest, dump, now

OUT_DIR = DOC / "diagnostics/completion-review-01/samples"
MANIFEST_NAME = "sample-manifest.json"
SAMPLE_SEED = 20261025
EPOCH = 60                                    # 진단용 고정 시점(기존 선택 E를 대체하지 않는다)
SEEDS = v2.SEEDS
N_LARGE_GAP = 5
HORIZON_CLIPPED = "data/sessions/phone-20261025-160407/raw_left.16.csv"
MANIFEST_VERSION = "completion-review-01/sample-manifest-v1"
SUMMARY_VERSION = "completion-review-01/summary-v1"
SCORE_TOL = 1e-6

NOTICE_PROPORTION = ("이 표본의 비율은 전체 성능이나 대표성의 추정치가 아니다. 이상 사례 점검과 파형 확인을 위한 "
                     "고정 목록이다(기본 20개는 세션×방향 추첨, 나머지는 이상 사례 점검용).")
NOTICE_E = ("완료 시각 e와 main_motion_end_ms는 같은 자동 센서 도구에서 나왔고 실제 자연 복귀 완료의 독립 정답이 "
            "아니다. 발행 시점과 e의 관계(조기/구간/늦음)는 어떤 발행도 실제 복귀 완료를 증명하지 않는다.")


class Mismatch(Exception):
    """저장된 기록과 재도출 결과가 다르거나 학습 제외 검사가 실패했을 때."""


# ---------------------------------------------------------------- 표본 선택

def completion_gap(ann):
    """e − main_motion_end_ms (ms). 두 값 모두 같은 자동 도구의 결과."""
    return ann["completion_ms"] - ann["main_motion_end_ms"]


def select_samples(records, ann, seed=SAMPLE_SEED, horizon_paths=(HORIZON_CLIPPED,)):
    """방향 원본에서 표본 목록을 만든다. 순수 함수(파일을 읽지 않는다).

    records: records.json의 records(방향 != NONE만 쓴다), ann: source_path -> 후보 주석.
    반환: (samples, groups, large_gap_ranking). samples는 선택 순서(기본 20개 → 추가)이며 tags/reasons를 가진다.
    """
    direction_recs = [r for r in records if r["direction"] != "NONE"]
    by_path = {r["source_path"]: r for r in direction_recs}
    rng = np.random.default_rng(seed)
    groups, base = [], []
    for s in SESSION_KEYS:                       # 그룹 순서: P1..P5 × UP, DOWN, LEFT, RIGHT
        for d in DIRECTIONS:
            g = sorted((r for r in direction_recs if r["session"] == s and r["direction"] == d),
                       key=lambda r: r["source_path"])
            i = int(rng.integers(len(g)))        # 그룹 순서대로 연속 사용
            groups.append({"session": s, "direction": d, "n_clips": len(g), "drawn_index": i,
                           "source_path": g[i]["source_path"]})
            base.append(g[i]["source_path"])
    ranked = sorted(direction_recs, key=lambda r: (-completion_gap(ann[r["source_path"]]), r["source_path"]))
    large = [r["source_path"] for r in ranked[:N_LARGE_GAP]]
    ranking = [{"rank": k + 1, "source_path": p, "gap_ms": completion_gap(ann[p])} for k, p in enumerate(large)]
    for p in horizon_paths:
        if p not in by_path:
            raise Mismatch(f"끝부분 잘림 원본이 방향 원본에 없다: {p}")
        if not by_path[p].get("match_horizon_clipped"):
            raise Mismatch(f"match_horizon_clipped가 아닌 원본이다: {p}")
    order, tags, reasons = [], {}, {}
    for kind, plist in (("base", base), ("large_gap", large), ("clipped_horizon", list(horizon_paths))):
        for k, p in enumerate(plist):
            if p not in tags:
                order.append(p)
                tags[p], reasons[p] = [], []
            tags[p].append(kind)
            if kind == "base":
                gi = groups[k]
                reasons[p].append(f"base: {gi['session']}×{gi['direction']} 그룹({gi['n_clips']}개)에서 인덱스 {gi['drawn_index']}")
            elif kind == "large_gap":
                reasons[p].append(f"large_gap: e−main_motion_end_ms {completion_gap(ann[p])} ms (상위 {k + 1}위)")
            else:
                reasons[p].append("clipped_horizon: e+500 ms가 클립 끝(3990 ms)을 넘는 원본(match_horizon_clipped)")
    samples = []
    for n, p in enumerate(order, 1):
        r, a = by_path[p], ann[p]
        samples.append({
            "sample_id": f"S{n:02d}", "source_path": p, "session": r["session"], "direction": r["direction"],
            "record_sha256": r["sha256"], "completion_ms": r["completion_ms"],
            "main_motion_start_ms": a["main_motion_start_ms"], "main_motion_end_ms": a["main_motion_end_ms"],
            "gap_ms": completion_gap(a), "flags": a["flags"], "status": a["status"],
            "match_horizon_clipped": bool(r.get("match_horizon_clipped")),
            "tags": tags[p], "reasons": reasons[p],
            "extra_for_anomaly_check": "base" not in tags[p]})
    return samples, groups, ranking


def load_annotations():
    """source_path -> 후보 주석(읽기 전용)과 후보 파일 해시."""
    ann, hashes = {}, {}
    for f in sorted(v2.ANN.glob("*-candidates.json")):
        hashes[f.name] = digest(f)
        for a in json.loads(f.read_text(encoding="utf-8"))["annotations"]:
            ann[a["source_path"]] = a
    return ann, hashes


def check_annotation_consistency(records, ann):
    """records.json의 e와 후보 주석의 e가 같은지(주석은 한 도구의 결과)."""
    for r in records:
        if r["direction"] == "NONE":
            continue
        a = ann.get(r["source_path"])
        if a is None or a["completion_ms"] != r["completion_ms"]:
            raise Mismatch(f"records와 후보 주석의 completion_ms가 다르다: {r['source_path']}")


def build_manifest(data=None):
    if data is None:
        data = json.loads(v2.RECORDS.read_text(encoding="utf-8"))
    ann, cand_hashes = load_annotations()
    check_annotation_consistency(data["records"], ann)
    samples, groups, ranking = select_samples(data["records"], ann)
    n_dir = sum(1 for r in data["records"] if r["direction"] != "NONE")
    return {
        "version": MANIFEST_VERSION, "created_kst": now(),
        "purpose": "완료 시각 e 근처의 파형·점수·발행을 눈으로 확인할 표본 목록(그림을 그리기 전에 저장)",
        "notice": NOTICE_PROPORTION, "notice_e": NOTICE_E,
        "rules": {
            "universe": f"records.json의 방향 원본 {n_dir}개(direction != NONE)",
            "base": "세션 P1..P5 × 방향 UP,DOWN,LEFT,RIGHT(이 순서)마다 1개; 그룹은 source_path 문자열 오름차순 정렬",
            "large_gap": f"e − main_motion_end_ms가 큰 상위 {N_LARGE_GAP}개(동점은 source_path 오름차순)",
            "clipped_horizon": [HORIZON_CLIPPED],
            "dedup": "기본 → large_gap → clipped_horizon 순으로 추가하고 중복은 한 번만 두며 tags에 이유를 모두 적는다",
            "diagnostic_condition": f"E={EPOCH}, seeds={list(SEEDS)}; P1~P4 원본은 V2-S-P5-cal, P5 원본은 V2-S-P1-cal의 해당 세션 검증 fold"},
        "rng": {"generator": "numpy.random.default_rng", "bit_generator": "PCG64", "seed": SAMPLE_SEED,
                "call": "rng.integers(len(group)), 그룹 순서(P1UP,P1DOWN,P1LEFT,P1RIGHT,P2UP,...)대로 연속 20회",
                "numpy": np.__version__},
        "groups": groups, "large_gap_ranking": ranking,
        "hashes": {"records_json": {"path": "data/annotations/ble-v2/records.json", "sha256": digest(v2.RECORDS)},
                   "candidate_json": cand_hashes,
                   "sha256_definition": "CRLF를 LF로 바꾼 뒤 SHA-256(v2.digest)"},
        "counts": {"samples": len(samples), "base": sum("base" in s["tags"] for s in samples),
                   "extra_only": sum(s["extra_for_anomaly_check"] for s in samples),
                   "tag_counts": dict(Counter(t for s in samples for t in s["tags"]))},
        "samples": samples}


def ensure_new(paths):
    exist = [str(p) for p in paths if Path(p).exists()]
    if exist:
        raise FileExistsError("이미 있는 출력은 덮어쓰지 않는다: " + ", ".join(exist))


def write_text(path, text):
    """LF로 저장한다(Windows에서 write_text는 \\n을 \\r\\n으로 바꾼다)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def cmd_sample(out=OUT_DIR):
    out = Path(out)
    ensure_new([out / MANIFEST_NAME])
    manifest = build_manifest()
    dump(out / MANIFEST_NAME, manifest)
    print(f"manifest 저장: {out / MANIFEST_NAME} (표본 {manifest['counts']['samples']}개, 태그 {manifest['counts']['tag_counts']})")
    return manifest


# ---------------------------------------------------------------- 저장된 예측·발행 로드와 무결성 검사

def split_name_for(session):
    """P1~P4 원본은 S-P5 보정, P5 원본은 S-P1 보정의 저장 예측을 쓴다."""
    return "S-P1" if session == "P5" else "S-P5"


def run_id_for(split_name):
    return f"V2-{split_name}-cal"


def find_fold(split, session):
    """held_out_session이 session인 CV fold 번호(정확히 하나여야 한다)."""
    ks = [f["fold"] for f in split["cv"]["folds"] if f.get("held_out_session") == session]
    if len(ks) != 1:
        raise Mismatch(f"{split['name']}: held_out_session={session}인 fold가 {len(ks)}개다")
    return ks[0]


def training_exclusion(source_path, split, fold_index):
    """원본이 해당 fold의 학습 부분(train_sources − 검증 원본)에 있는지 확인한다."""
    folds = {f["fold"]: f for f in split["cv"]["folds"]}
    validation = set(folds[fold_index]["validation_sources"])
    training = set(split["train_sources"]) - validation
    in_eval = source_path in set(split["eval_sources"])
    ok = source_path in validation and source_path not in training and not in_eval
    return {"split": split["name"], "fold": fold_index, "in_fold_validation": source_path in validation,
            "in_fold_training": source_path in training, "in_eval_sources": in_eval,
            "n_training_sources": len(training), "ok": ok}


def assert_not_trained(source_path, split, fold_index):
    c = training_exclusion(source_path, split, fold_index)
    if not c["ok"]:
        raise Mismatch(f"학습 제외 검사 실패: {source_path} {c}")
    return c


def timing_class(t, e):
    """classify_events와 같은 경계: e 전=early, e+500 초과=late, 그 사이=window."""
    return "early" if t < e else "late" if t > e + v2.MATCH_MS else "window"


def rederive_and_check(record, times, scores, stored_events):
    """저장된 점수에서 issue_events로 발행을 다시 만들어 저장된 로그와 정확히 비교한다.

    비교: 시각·클래스·kind(classify_events)가 정확히 같아야 하고 점수는 SCORE_TOL 이내여야 한다.
    seed 평균 같은 새 점수로 발행을 만들지 않는다. 다르면 Mismatch.
    """
    derived = v2.issue_events(times, scores)
    _, _, annotated = v2.classify_events(record, derived)
    got = [(ev["timestamp_ms"], ev["class_index"], ev["kind"]) for ev in annotated]
    want = [(ev["timestamp_ms"], ev["class_index"], ev["kind"]) for ev in stored_events]
    if got != want:
        raise Mismatch(f"발행 재도출이 저장 로그와 다르다: {record['source_path']}\n재도출={got}\n저장={want}")
    diffs = [abs(a["score"] - b["score"]) for a, b in zip(annotated, stored_events)]
    max_diff = max(diffs) if diffs else 0.0
    if max_diff > SCORE_TOL:
        raise Mismatch(f"발행 점수 차이 {max_diff} > {SCORE_TOL}: {record['source_path']}")
    e = record["completion_ms"]
    events = []
    for ev in annotated:
        match = ev["class_index"] == CLASSES.index(record["direction"])
        events.append({**ev, "timing": timing_class(ev["timestamp_ms"], e), "direction_match": bool(match),
                       "t_minus_e_ms": ev["timestamp_ms"] - e})
    return events, float(max_diff), bool(all(d == 0 for d in diffs))


def clip_windows(source_path, windows, scores_e):
    """저장된 창 목록에서 원본 하나의 행을 골라 (시각, 점수, 행 번호)를 돌려준다.

    판정 시각은 창의 마지막 실제 샘플 시각이어야 한다: 첫 시각 1590 ms, 50 ms 간격, 마지막 3990 ms.
    0~1580 ms 구간에는 창이 없으므로 점수도 없다(채우지 않는다).
    """
    idx = [i for i, w in enumerate(windows) if w["source_path"] == source_path]
    if not idx or idx != list(range(idx[0], idx[0] + len(idx))):
        raise Mismatch(f"창 행이 연속이 아니거나 없다: {source_path}")
    times = np.array([windows[i]["timestamp_ms"] for i in idx])
    if not np.array_equal(times, v2.decision_times(v2.GESTURE_ROWS)):
        raise Mismatch(f"저장된 판정 시각이 decision_times와 다르다: {source_path}")
    if int(times[0]) != v2.FIRST_T or int(times[-1]) != v2.LAST_T:
        raise Mismatch(f"판정 시각 범위가 {v2.FIRST_T}~{v2.LAST_T}가 아니다: {source_path}")
    scores = np.asarray(scores_e)[idx]
    if scores.shape != (len(idx), len(CLASSES)) or not np.isfinite(scores).all():
        raise Mismatch(f"점수 배열 모양/값 이상: {source_path}")
    return times, scores, [windows[i] for i in idx]


def check_targets(record, clip_meta):
    """저장된 창의 target이 [e, e+150) 양성 규칙과 같은지."""
    e, cls = record["completion_ms"], CLASSES.index(record["direction"])
    expected = [cls if e <= w["timestamp_ms"] < e + v2.POSITIVE_MS else 0 for w in clip_meta]
    return expected == [w["target"] for w in clip_meta]


def check_window_alignment(record, clip_meta):
    """v2.windows가 만든 창의 시각·마지막 행이 저장 목록 및 원시 센서 행과 같은지(정규화 없이)."""
    ts, raw = v2.read_sensor(ROOT / record["source_path"])
    x, _, meta = v2.windows(record, np.zeros(len(AXES)), np.ones(len(AXES)))
    if [m["timestamp_ms"] for m in meta] != [w["timestamp_ms"] for w in clip_meta]:
        raise Mismatch(f"재구성한 창 시각이 저장 목록과 다르다: {record['source_path']}")
    rows = np.round(np.array([m["timestamp_ms"] for m in meta]) / 10).astype(int)
    if not np.allclose(x[:, -1, :], raw[rows]):
        raise Mismatch(f"창의 마지막 행이 판정 시각의 원시 행과 다르다: {record['source_path']}")
    return True


class RunStore:
    """분할·seed별 결과와 fold별 저장 예측을 한 번만 읽어 둔다."""

    def __init__(self):
        self.splits, self.results, self.arrays = {}, {}, {}

    def split(self, name):
        if name not in self.splits:
            s = v2.load_split(name)
            if s.get("records_sha256") != digest(v2.RECORDS):
                raise Mismatch(f"{name}: 분할의 records_sha256이 현재 records.json과 다르다")
            self.splits[name] = s
        return self.splits[name]

    def result(self, split_name, seed):
        key = (split_name, seed)
        if key not in self.results:
            path = DOC / "results" / run_id_for(split_name) / f"seed-{seed}.json"
            r = json.loads(path.read_text(encoding="utf-8"))
            if r["seed"] != seed or r["split"] != split_name:
                raise Mismatch(f"{path}: seed/split 불일치")
            self.results[key] = r
        return self.results[key]

    def arrays_for(self, split_name, seed, fold):
        key = (split_name, seed, fold)
        if key not in self.arrays:
            base = ROOT / "ml/runs" / run_id_for(split_name) / f"seed-{seed}-fold-{fold}"
            windows = json.loads(Path(f"{base}-windows.json").read_text(encoding="utf-8"))
            with np.load(f"{base}-scores.npz") as z:
                self.arrays[key] = (windows, z[f"e{EPOCH}"])
            if len(self.arrays[key][0]) != len(self.arrays[key][1]):
                raise Mismatch(f"창 수와 점수 행 수가 다르다: {base}")
        return self.arrays[key]


def stored_events_for(result, fold, held_out, source_path):
    f = [f for f in result["folds"] if f["fold"] == fold]
    if len(f) != 1 or f[0]["held_out_session"] != held_out:
        raise Mismatch(f"결과 fold {fold}의 held_out_session이 {held_out}이 아니다")
    ps = [p for p in f[0]["per_epoch"][str(EPOCH)]["per_source"] if p["source_path"] == source_path]
    if len(ps) != 1:
        raise Mismatch(f"저장된 발행 로그에 원본이 {len(ps)}번 있다: {source_path}")
    return ps[0]["events"]


def analyse_sample(sample, store, by_path):
    """표본 하나의 5 seed 점수·발행·검사 결과."""
    record = by_path[sample["source_path"]]
    if record["sha256"] != sample["record_sha256"] or record["completion_ms"] != sample["completion_ms"]:
        raise Mismatch(f"manifest와 records.json이 다르다: {sample['source_path']}")
    session = sample["session"]
    split_name = split_name_for(session)
    split = store.split(split_name)
    fold = find_fold(split, session)
    seeds, checks_re, checks_tr = {}, [], []
    alignment = None
    for seed in SEEDS:
        result = store.result(split_name, seed)
        windows, e_scores = store.arrays_for(split_name, seed, fold)
        times, scores, clip_meta = clip_windows(sample["source_path"], windows, e_scores)
        if not check_targets(record, clip_meta):
            raise Mismatch(f"저장된 target이 양성 규칙과 다르다: {sample['source_path']}")
        if alignment is None:
            alignment = check_window_alignment(record, clip_meta)
        stored = stored_events_for(result, fold, session, sample["source_path"])
        events, max_diff, bit_equal = rederive_and_check(record, times, scores, stored)
        tr = assert_not_trained(sample["source_path"], split, fold)
        seeds[seed] = {"times": times, "scores": scores, "events": events}
        checks_re.append({"sample_id": sample["sample_id"], "seed": seed, "split": split_name, "fold": fold,
                          "n_stored_events": len(stored), "n_rederived_events": len(events),
                          "equal": True, "max_abs_score_diff": max_diff, "score_bit_equal": bit_equal})
        checks_tr.append({"sample_id": sample["sample_id"], "seed": seed, "run": run_id_for(split_name), **tr})
    return {"sample": sample, "record": record, "split": split_name, "fold": fold, "seeds": seeds,
            "window_alignment_ok": bool(alignment), "rederivation": checks_re, "training_exclusion": checks_tr}


# ---------------------------------------------------------------- 클립 단위 집계

def clip_level_counts(analyses):
    """클립(표본)과 (클립, seed) 쌍 단위 집계. 한 클립에서 여러 번 발행해도 한 번만 센다.

    analyses: [{"seeds": {seed: {"events": [{kind, timing, direction_match, ...}]}}}]
    """
    seeds = sorted({s for a in analyses for s in a["seeds"]})
    pair_keys = ("any", "multiple", "early", "early_match", "early_mismatch", "window_match", "window_mismatch",
                 "late_match", "late_mismatch", "correct", "duplicate", "wrong_direction", "late_unmatched")
    pairs = Counter({k: 0 for k in pair_keys})
    per_seed = {s: Counter({k: 0 for k in pair_keys}) for s in seeds}
    by_n = Counter({n: 0 for n in range(len(seeds) + 1)})
    samples_any, events_total = 0, 0
    for a in analyses:
        n_emitted = 0
        for s in seeds:
            ev = a["seeds"][s]["events"]
            events_total += len(ev)
            flags = set()
            if ev:
                flags.add("any")
                n_emitted += 1
            if len(ev) >= 2:
                flags.add("multiple")
            for x in ev:
                flags.add(x["kind"])
                flags.add(f"{x['timing']}_{'match' if x['direction_match'] else 'mismatch'}")
                if x["timing"] == "early":
                    flags.add("early")
            for k in flags & set(pair_keys):
                pairs[k] += 1
                per_seed[s][k] += 1
        by_n[n_emitted] += 1
        samples_any += n_emitted > 0
    return {"n_samples": len(analyses), "n_seeds": len(seeds), "n_clip_seed_pairs": len(analyses) * len(seeds),
            "samples_with_any_emission_in_any_seed": samples_any,
            "samples_by_n_seeds_emitted": {str(n): by_n[n] for n in sorted(by_n)},
            "clip_seed_pairs_with": dict(pairs), "events_total_not_clip_level": events_total,
            "per_seed_clips_with": {str(s): dict(c) for s, c in per_seed.items()}}


# ---------------------------------------------------------------- SVG (손으로 쓴 SVG; 그래프 라이브러리 없음)

KIND_COLOR = {"early": "#E69F00", "correct": "#009E73", "duplicate": "#56B4E9",
              "wrong_direction": "#D55E00", "late_unmatched": "#CC79A7"}
KIND_LABEL = {"early": "early(e 전)", "correct": "correct", "duplicate": "duplicate",
              "wrong_direction": "wrong_direction(구간 안·방향 다름)", "late_unmatched": "late(e+500 초과)"}
AXIS_COLOR = ("#0072B2", "#D55E00", "#009E73")
FONT = "'Malgun Gothic','Noto Sans KR',Arial,sans-serif"
W, LM, RM = 1100, 84, 22
PW = W - LM - RM
XMAX = 4000.0
GAP = 14


def xs(ms):
    return LM + ms / XMAX * PW


def nice_ticks(lo, hi, n=4):
    if hi - lo < 1e-9:
        hi, lo = hi + 1, lo - 1
    raw = (hi - lo) / n
    mag = 10 ** np.floor(np.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    first = np.ceil(lo / step) * step
    return [float(v) for v in np.arange(first, hi + step * .001, step)]


def fnum(v):
    v = 0.0 if abs(v) < 1e-9 else float(v)         # "-0" 표시 방지
    return f"{v:.1f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:.0f}"


def esc(s):
    return html.escape(str(s), quote=True)


def polyline(points, color, width=1.0, opacity=1.0, dash=None):
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}" '
            f'stroke-opacity="{opacity}" stroke-linejoin="round"{d}/>')


def svg_text(x, y, s, size=10, anchor="start", fill="#333", weight="normal"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" fill="{fill}" '
            f'font-weight="{weight}" font-family="{FONT}">{esc(s)}</text>')


def render_svg(sample, ts, raw, seeds):
    """표본 하나의 그림(문자열). ts/raw는 센서 원본, seeds는 {seed: {times, scores, events}}."""
    e, start, end = sample["completion_ms"], sample["main_motion_start_ms"], sample["main_motion_end_ms"]
    true_col = CLASSES.index(sample["direction"])
    heights = {"acc": 112, "gyro": 112, "mag": 72, "score": 150}
    strip_row = 17
    top = 98                                     # 제목·표지선 이름 영역
    y_acc = top
    y_gyro = y_acc + heights["acc"] + GAP
    y_mag = y_gyro + heights["gyro"] + GAP
    y_score = y_mag + heights["mag"] + GAP
    y_strip = y_score + heights["score"] + 4
    strip_h = strip_row * len(SEEDS) + 8
    y_axis = y_strip + strip_h
    total_h = y_axis + 78
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {total_h}" width="{W}" height="{total_h}" '
           f'role="img" aria-label="{esc(sample["sample_id"] + " " + sample["source_path"])}">',
           f'<title>{esc(sample["sample_id"])} {esc(sample["source_path"])} (E={EPOCH}, 5 seed)</title>',
           '<defs><pattern id="nodata" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
           '<line x1="0" y1="0" x2="0" y2="7" stroke="#bbb" stroke-width="2"/></pattern></defs>',
           f'<rect width="{W}" height="{total_h}" fill="#fff"/>']
    flags = f", flags={sample['flags']}" if sample["flags"] else ""
    out.append(svg_text(LM, 18, f"{sample['sample_id']}  {sample['session']} · {sample['direction']} · {Path(sample['source_path']).name}"
                        f"   (tags: {', '.join(sample['tags'])})", 14, weight="bold"))
    out.append(svg_text(LM, 35, f"e={e} ms, main_motion_start={start}, main_motion_end={end}, e−end={sample['gap_ms']} ms, "
                        f"status={sample['status']}{flags}", 11))
    out.append(svg_text(LM, 50, "e와 main_motion_end는 같은 자동 센서 도구의 결과이며 실제 복귀 완료의 독립 정답이 아니다. "
                        "발행은 실제 복귀 완료를 증명하지 않는다.", 10, fill="#a33"))

    def panel_frame(y, h, title):
        out.append(f'<rect x="{LM}" y="{y}" width="{PW}" height="{h}" fill="#fafafa" stroke="#999" stroke-width="0.8"/>')
        out.append(f'<text transform="translate(13 {y + h / 2:.1f}) rotate(-90)" font-size="10" text-anchor="middle" '
                   f'fill="#333" font-weight="bold" font-family="{FONT}">{esc(title)}</text>')

    def shade(y, h):
        out.append(f'<rect x="{xs(e):.1f}" y="{y}" width="{xs(min(e + v2.MATCH_MS, XMAX)) - xs(e):.1f}" height="{h}" '
                   f'fill="#009E73" fill-opacity="0.13"/>')
        out.append(f'<rect x="{xs(e):.1f}" y="{y}" width="{xs(e + v2.POSITIVE_MS) - xs(e):.1f}" height="{h}" '
                   f'fill="#E69F00" fill-opacity="0.38"/>')

    def grid_and_marks(y, h):
        for ms in range(0, 4001, 500):
            out.append(f'<line x1="{xs(ms):.1f}" y1="{y}" x2="{xs(ms):.1f}" y2="{y + h}" stroke="#e2e2e2" stroke-width="0.6"/>')

    def markers(y, h):
        for ms, color, dash, width in ((v2.CUE_MS, "#777", "2 3", 1.2), (start, "#0072B2", "5 3", 1.2),
                                       (end, "#0072B2", "1 0", 1.2), (e, "#000", "1 0", 1.8)):
            d = f' stroke-dasharray="{dash}"' if dash != "1 0" else ""
            out.append(f'<line x1="{xs(ms):.1f}" y1="{y}" x2="{xs(ms):.1f}" y2="{y + h}" stroke="{color}" stroke-width="{width}"{d}/>')

    def y_axis_ticks(y, h, lo, hi, unit=""):
        for v in nice_ticks(lo, hi):
            yy = y + h - (v - lo) / (hi - lo) * h
            if y - 1 <= yy <= y + h + 1:
                out.append(f'<line x1="{LM - 3}" y1="{yy:.1f}" x2="{LM}" y2="{yy:.1f}" stroke="#666" stroke-width="0.8"/>')
                out.append(f'<line x1="{LM}" y1="{yy:.1f}" x2="{LM + PW}" y2="{yy:.1f}" stroke="#ececec" stroke-width="0.5"/>')
                out.append(svg_text(LM - 5, yy + 3, fnum(v), 9, "end", "#555"))

    def draw_series(y, h, cols, labels, lo_hi=None, unit=""):
        vals = np.concatenate([raw[:, c] for c in cols])
        lo, hi = (float(vals.min()), float(vals.max())) if lo_hi is None else lo_hi
        pad = (hi - lo) * .06 or 1.0
        lo, hi = lo - pad, hi + pad
        grid_and_marks(y, h)
        shade(y, h)
        y_axis_ticks(y, h, lo, hi, unit)
        for c, color in zip(cols, AXIS_COLOR):
            pts = [(xs(t), y + h - (v - lo) / (hi - lo) * h) for t, v in zip(ts, raw[:, c])]
            out.append(polyline(pts, color, 1.0, .95))
        for k, (lab, color) in enumerate(zip(labels, AXIS_COLOR)):
            out.append(f'<line x1="{LM + 8 + k * 62}" y1="{y + 10}" x2="{LM + 24 + k * 62}" y2="{y + 10}" stroke="{color}" stroke-width="2"/>')
            out.append(svg_text(LM + 28 + k * 62, y + 13, lab, 10))
        markers(y, h)

    panel_frame(y_acc, heights["acc"], "가속도")
    draw_series(y_acc, heights["acc"], (0, 1, 2), AXES[:3])
    panel_frame(y_gyro, heights["gyro"], "자이로(dps)")
    draw_series(y_gyro, heights["gyro"], (3, 4, 5), AXES[3:])
    # 자이로 크기
    mag = np.sqrt((raw[:, 3:] ** 2).sum(axis=1))
    panel_frame(y_mag, heights["mag"], "자이로 크기")
    grid_and_marks(y_mag, heights["mag"])
    shade(y_mag, heights["mag"])
    hi = float(mag.max()) * 1.08 or 1.0
    y_axis_ticks(y_mag, heights["mag"], 0.0, hi)
    out.append(polyline([(xs(t), y_mag + heights["mag"] - m / hi * heights["mag"]) for t, m in zip(ts, mag)], "#444", 1.0))
    out.append(svg_text(LM + 8, y_mag + 13, "√(gyrX²+gyrY²+gyrZ²)", 10))
    markers(y_mag, heights["mag"])
    # 점수
    hs = heights["score"]
    panel_frame(y_score, hs, f"정답({sample['direction']}) 점수")
    grid_and_marks(y_score, hs)
    out.append(f'<rect x="{xs(0):.1f}" y="{y_score}" width="{xs(v2.FIRST_T) - xs(0):.1f}" height="{hs}" fill="url(#nodata)" fill-opacity="0.8"/>')
    out.append(svg_text((xs(0) + xs(v2.FIRST_T)) / 2, y_score + hs / 2 + 4, "점수 없음 (0~1580 ms)", 10, "middle", "#555"))
    shade(y_score, hs)
    for v in (0, .2, .4, .6, .8, 1.0):
        yy = y_score + hs - v * hs
        out.append(f'<line x1="{LM - 3}" y1="{yy:.1f}" x2="{LM}" y2="{yy:.1f}" stroke="#666" stroke-width="0.8"/>')
        out.append(svg_text(LM - 5, yy + 3, fnum(v), 9, "end", "#555"))
    times = next(iter(seeds.values()))["times"]
    stack = np.stack([seeds[s]["scores"][:, true_col] for s in SEEDS])
    lo_b, hi_b = stack.min(axis=0), stack.max(axis=0)
    top_pts = [(xs(t), y_score + hs - float(v) * hs) for t, v in zip(times, hi_b)]
    bot_pts = [(xs(t), y_score + hs - float(v) * hs) for t, v in zip(times, lo_b)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in top_pts + bot_pts[::-1])
    out.append(f'<polygon points="{poly}" fill="#4c78a8" fill-opacity="0.18" stroke="none"/>')
    for s in SEEDS:
        pts = [(xs(t), y_score + hs - float(v) * hs) for t, v in zip(seeds[s]["times"], seeds[s]["scores"][:, true_col])]
        out.append(polyline(pts, "#2f4b7c", 0.9, .6))
    y08 = y_score + hs - .8 * hs
    out.append(f'<line x1="{LM}" y1="{y08:.1f}" x2="{LM + PW}" y2="{y08:.1f}" stroke="#c00" stroke-width="1" stroke-dasharray="6 3"/>')
    out.append(svg_text(LM + PW - 3, y08 - 3, "문턱 0.8", 9, "end", "#c00"))
    out.append(svg_text(LM + 8, y_score + 13, "seed별 정답 방향 점수(가는 선) + 최소~최대 띠. 평균은 만들지 않음", 10))
    markers(y_score, hs)
    # 발행 줄
    out.append(f'<rect x="{LM}" y="{y_strip}" width="{PW}" height="{strip_h}" fill="#fff" stroke="#999" stroke-width="0.8"/>')
    out.append(f'<text transform="translate(13 {y_strip + strip_h / 2:.1f}) rotate(-90)" font-size="10" text-anchor="middle" '
               f'fill="#333" font-weight="bold" font-family="{FONT}">발행</text>')
    for k, s in enumerate(SEEDS):
        cy = y_strip + 4 + strip_row * k + strip_row / 2
        if k % 2 == 0:
            out.append(f'<rect x="{LM}" y="{cy - strip_row / 2:.1f}" width="{PW}" height="{strip_row}" fill="#f3f3f3"/>')
        out.append(svg_text(LM - 6, cy + 3, f"seed {str(s)[-2:]}", 9, "end", "#555"))
        evs = seeds[s]["events"]
        if not evs:
            out.append(svg_text(xs(v2.FIRST_T + 20), cy + 3, "발행 없음", 9, "start", "#888"))
        for ev in evs:
            x, color = xs(ev["timestamp_ms"]), KIND_COLOR[ev["kind"]]
            out.append(f'<line x1="{x:.1f}" y1="{y_score}" x2="{x:.1f}" y2="{cy:.1f}" stroke="{color}" stroke-width="0.8" '
                       f'stroke-opacity="0.55" stroke-dasharray="2 2"/>')
            if ev["direction_match"]:
                out.append(f'<circle cx="{x:.1f}" cy="{cy:.1f}" r="5" fill="{color}" stroke="#222" stroke-width="0.8">'
                           f'<title>seed {s}: {ev["timestamp_ms"]} ms {ev["kind"]} {CLASSES[ev["class_index"]]} (일치)</title></circle>')
            else:
                out.append(f'<rect x="{x - 4.5:.1f}" y="{cy - 4.5:.1f}" width="9" height="9" fill="{color}" stroke="#000" stroke-width="2" '
                           f'transform="rotate(45 {x:.1f} {cy:.1f})"><title>seed {s}: {ev["timestamp_ms"]} ms {ev["kind"]} '
                           f'{CLASSES[ev["class_index"]]} (불일치)</title></rect>')
                out.append(svg_text(x + 8, cy + 3, CLASSES[ev["class_index"]][0], 9, "start", "#000", "bold"))
    # x축
    out.append(f'<line x1="{LM}" y1="{y_axis}" x2="{LM + PW}" y2="{y_axis}" stroke="#444" stroke-width="1"/>')
    for ms in range(0, 4001, 500):
        out.append(f'<line x1="{xs(ms):.1f}" y1="{y_axis}" x2="{xs(ms):.1f}" y2="{y_axis + 4}" stroke="#444" stroke-width="1"/>')
        out.append(svg_text(xs(ms), y_axis + 15, str(ms), 10, "middle", "#333"))
    out.append(svg_text(LM + PW / 2, y_axis + 29, "시간 (ms, 센서 클립 시계; 점수의 시각 = 창의 마지막 실제 샘플)", 10, "middle"))
    # 표지선 이름(상단)
    for row, (ms, label, color) in enumerate(((v2.CUE_MS, f"신호 {v2.CUE_MS}", "#777"), (start, f"동작 시작 {start}", "#0072B2"),
                                                (end, f"동작 종료 {end}", "#0072B2"), (e, f"e {e}", "#000"))):
        ly = 62 + row * 9
        out.append(f'<line x1="{xs(ms):.1f}" y1="{ly - 3}" x2="{xs(ms):.1f}" y2="{y_acc}" stroke="{color}" stroke-width="0.8" stroke-opacity="0.7"/>')
        out.append(svg_text(xs(ms) + 3, ly, label, 9, "start", color if color != "#777" else "#555", "bold" if ms == e else "normal"))
    # 범례(두 줄)
    lx, ly = LM, y_axis + 44
    out.append(f'<rect x="{lx}" y="{ly - 8}" width="14" height="9" fill="#E69F00" fill-opacity="0.38"/>')
    out.append(svg_text(lx + 18, ly, "양성 [e, e+150)", 9))
    out.append(f'<rect x="{lx + 120}" y="{ly - 8}" width="14" height="9" fill="#009E73" fill-opacity="0.13" stroke="#999" stroke-width="0.4"/>')
    out.append(svg_text(lx + 138, ly, "성공 허용 [e, e+500]", 9))
    cx = lx + 280
    for kind in ("early", "correct", "duplicate", "wrong_direction", "late_unmatched"):
        out.append(f'<circle cx="{cx + 5}" cy="{ly - 3.5}" r="4.5" fill="{KIND_COLOR[kind]}" stroke="#222" stroke-width="0.8"/>')
        out.append(svg_text(cx + 13, ly, KIND_LABEL[kind], 9))
        cx += 24 + sum(9.2 if ord(ch) > 255 else 5.0 for ch in KIND_LABEL[kind])
    ly += 15
    out.append(f'<rect x="{lx + 1}" y="{ly - 8}" width="8" height="8" fill="#bbb" stroke="#000" stroke-width="1.6" transform="rotate(45 {lx + 5} {ly - 4})"/>')
    out.append(svg_text(lx + 16, ly, "검은 테두리 마름모 = 발행 방향이 정답 방향과 다름(글자 = 발행한 방향 U/D/L/R); 원 = 방향 일치. 색은 시간 구간·방향에 따른 kind.", 9))
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- 보고서·요약 작성

def emission_rows(analyses):
    rows = []
    for a in analyses:
        s = a["sample"]
        for seed in SEEDS:
            for ev in a["seeds"][seed]["events"]:
                rows.append({"sample_id": s["sample_id"], "seed": seed, "timestamp_ms": ev["timestamp_ms"],
                             "class": CLASSES[ev["class_index"]], "score": round(ev["score"], 4),
                             "timing": ev["timing"], "direction_match": ev["direction_match"],
                             "kind": ev["kind"], "t_minus_e_ms": ev["t_minus_e_ms"]})
    return rows


def sample_rows(analyses):
    rows = []
    for a in analyses:
        s = a["sample"]
        emitted = [sd for sd in SEEDS if a["seeds"][sd]["events"]]
        rows.append({
            "sample_id": s["sample_id"], "session": s["session"], "direction": s["direction"],
            "source_path": s["source_path"], "tags": s["tags"], "completion_ms": s["completion_ms"],
            "main_motion_end_ms": s["main_motion_end_ms"], "gap_ms": s["gap_ms"],
            "status": s["status"], "flags": s["flags"], "run": run_id_for(a["split"]), "fold": a["fold"],
            "n_seeds_emitted": len(emitted),
            "per_seed": {str(sd): [{"timestamp_ms": ev["timestamp_ms"], "class": CLASSES[ev["class_index"]],
                                    "timing": ev["timing"], "direction_match": ev["direction_match"], "kind": ev["kind"]}
                                   for ev in a["seeds"][sd]["events"]] for sd in SEEDS}})
    return rows


def md_cell(s):
    return str(s).replace("|", "\\|")


def seed_cell(items):
    if not items:
        return "—"
    return "; ".join(f"{x['timestamp_ms']} {x['timing']}/{'일치' if x['direction_match'] else '불일치'}({x['class']})" for x in items)


def render_markdown(summary):
    c = summary["clip_level_counts"]
    pw = c["clip_seed_pairs_with"]
    L = ["# 완료 시각 검토 01 — 표본 파형·점수·발행 요약", "",
         f"작성: {summary['created_kst']} · 표본 {len(summary['samples'])}개 · E={EPOCH}, seed {len(SEEDS)}개 고정 진단 조건", "",
         "> " + NOTICE_E, ">", "> " + NOTICE_PROPORTION, "",
         "## 조건", "",
         f"- P1~P4 원본: `V2-S-P5-cal`에서 그 세션이 검증인 fold의 저장 예측. P5 원본: `V2-S-P1-cal`에서 P5가 검증인 fold.",
         f"- seed {', '.join(str(s) for s in SEEDS)}; 발행은 저장된 점수에서 `v2.issue_events`로 다시 만들었고 저장 로그와 비교했다. "
         "seed 평균 점수로 새 발행을 만들지 않았다.",
         "- 점수는 1590 ms(첫 완전한 창의 마지막 샘플)부터 있다. 0~1580 ms는 그리지 않고 채우지 않았다.",
         f"- 그림: {summary['environment']['plotting']}; Python {summary['environment']['python']}, NumPy {summary['environment']['numpy']}.", "",
         "## 표본별 요약", "",
         "| 번호 | 세션 | 방향 | 원본 | 태그 | e | 동작 종료 | e−종료 | 상태/플래그 | 발행한 seed 수 | seed별 발행(시각 구간/방향) |",
         "|---|---|---|---|---|---:|---:|---:|---|---:|---|"]
    for r in summary["samples"]:
        per = "<br>".join(f"{str(sd)[-2:]}: {md_cell(seed_cell(r['per_seed'][str(sd)]))}" for sd in SEEDS)
        L.append(f"| {r['sample_id']} | {r['session']} | {r['direction']} | `{Path(r['source_path']).name}` | {', '.join(r['tags'])} | "
                 f"{r['completion_ms']} | {r['main_motion_end_ms']} | {r['gap_ms']} | {r['status']}{(' / ' + r['flags']) if r['flags'] else ''} | "
                 f"{r['n_seeds_emitted']}/{len(SEEDS)} | {per} |")
    L += ["", "구간: early = e 전, window = [e, e+500], late = e+500 초과. 방향: 발행 클래스가 정답 방향과 같으면 일치.", "",
          "## 클립 단위 집계", "",
          "한 클립에서 여러 번 발행해도 한 번만 센다. 표본은 고정 목록이며 아래 수는 성능 추정치가 아니다.", "",
          f"- 표본 {c['n_samples']}개 중 5 seed 가운데 하나라도 발행한 표본: {c['samples_with_any_emission_in_any_seed']}개",
          "- 발행한 seed 수별 표본 수: " + ", ".join(f"{k}개 seed → {v}개 표본" for k, v in c["samples_by_n_seeds_emitted"].items()),
          f"- (표본, seed) 쌍 {c['n_clip_seed_pairs']}개 중: 발행 ≥1 {pw['any']}, 발행 ≥2 {pw['multiple']}, "
          f"조기 발행 포함 {pw['early']} (방향 일치 {pw['early_match']}, 불일치 {pw['early_mismatch']}), "
          f"구간 안 일치 {pw['window_match']}, 구간 안 불일치 {pw['window_mismatch']}, "
          f"늦음 일치 {pw['late_match']}, 늦음 불일치 {pw['late_mismatch']}",
          f"- kind별 쌍 수: correct {pw['correct']}, duplicate {pw['duplicate']}, wrong_direction {pw['wrong_direction']}, "
          f"early {pw['early']}, late_unmatched {pw['late_unmatched']}",
          f"- 발행 이벤트 총수(클립 단위 아님): {c['events_total_not_clip_level']}", "",
          "seed별 (표본 수 기준):", "",
          "| seed | 발행 ≥1 | 조기 | 정답(correct) | 방향 불일치 구간 안 | 중복 | 늦음 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for sd in SEEDS:
        p = c["per_seed_clips_with"][str(sd)]
        L.append(f"| {sd} | {p['any']} | {p['early']} | {p['correct']} | {p['wrong_direction']} | {p['duplicate']} | {p['late_unmatched']} |")
    L += ["", "그룹별(표본 수 기준):", "", "| 그룹 | 표본 수 | 발행 ≥1 인 표본 | 5 seed 모두 발행한 표본 |", "|---|---:|---:|---:|"]
    for g in summary["group_counts"]:
        L.append(f"| {g['group']} | {g['n_samples']} | {g['samples_any']} | {g['samples_all_seeds']} |")
    L += ["", "## 발행 목록", "",
          "| 표본 | seed | 시각(ms) | t−e(ms) | 구간 | 발행 방향 | 방향 | kind | 점수 |", "|---|---|---:|---:|---|---|---|---|---:|"]
    for x in summary["emissions"]:
        L.append(f"| {x['sample_id']} | {x['seed']} | {x['timestamp_ms']} | {x['t_minus_e_ms']} | {x['timing']} | {x['class']} | "
                 f"{'일치' if x['direction_match'] else '불일치'} | {x['kind']} | {x['score']:.3f} |")
    ig = summary["integrity"]
    re_, tr = ig["emission_rederivation"], ig["training_exclusion"]
    L += ["", "## 무결성 검사", "",
          f"- 발행 재도출: {re_['n_pass']}/{re_['n_checks']} (표본×seed) 일치. 시각·클래스·kind 정확히 같음, 점수 최대 차이 {re_['max_abs_score_diff']:.2e}, "
          f"점수까지 비트 단위로 같은 검사 {re_['n_score_bit_equal']}건.",
          f"- 학습 제외: {tr['n_pass']}/{tr['n_checks']} (표본×seed). 각 표본은 해당 fold의 검증 원본이며 학습 부분(train_sources − 검증 원본)과 "
          "평가용(eval_sources)에 없다. 목록은 summary.json의 `integrity.training_exclusion.checks`.",
          f"- 창 정렬: 판정 시각이 `decision_times`(1590~3990 ms, 50 ms 간격)와 같고 `v2.windows`의 마지막 행이 해당 시각의 원시 행과 같음 "
          f"({ig['window_alignment']['n_pass']}/{ig['window_alignment']['n_checks']} 표본).",
          f"- 저장 target이 [e, e+150) 양성 규칙과 같음: {ig['targets_match_positive_rule']['n_pass']}/{ig['targets_match_positive_rule']['n_checks']} (표본×seed).",
          "", "## 한계", ""]
    L += [f"- {x}" for x in summary["limitations"]]
    return "\n".join(L) + "\n"


def render_html(summary, svgs):
    md_rows = []
    for r in summary["samples"]:
        per = "<br>".join(f"{str(sd)[-2:]}: {esc(seed_cell(r['per_seed'][str(sd)]))}" for sd in SEEDS)
        md_rows.append(f"<tr><td>{r['sample_id']}</td><td>{r['session']}</td><td>{r['direction']}</td>"
                       f"<td>{esc(Path(r['source_path']).name)}</td><td>{esc(', '.join(r['tags']))}</td>"
                       f"<td>{r['completion_ms']}</td><td>{r['main_motion_end_ms']}</td><td>{r['gap_ms']}</td>"
                       f"<td>{r['n_seeds_emitted']}/{len(SEEDS)}</td><td>{per}</td></tr>")
    parts = ['<!doctype html>', '<html lang="ko"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<title>완료 시각 검토 01 표본 보고서</title>',
             f'<style>body{{font-family:{FONT};margin:16px;color:#222;max-width:1180px}}table{{border-collapse:collapse;font-size:12px}}'
             'td,th{border:1px solid #bbb;padding:3px 6px;vertical-align:top}th{background:#eee}svg{max-width:100%;height:auto;border:1px solid #ddd}'
             '.note{background:#fff4e5;border:1px solid #e0b060;padding:8px;margin:8px 0}h2{margin-top:28px}</style>',
             '</head><body>', '<h1>완료 시각 검토 01 — 표본 파형·점수·발행</h1>',
             f'<p>작성 {esc(summary["created_kst"])} · 표본 {len(summary["samples"])}개 · E={EPOCH}, seed {len(SEEDS)}개 고정 진단 조건 · '
             f'{esc(summary["environment"]["plotting"])}</p>',
             f'<div class="note">{esc(NOTICE_E)}<br>{esc(NOTICE_PROPORTION)}</div>',
             '<p>각 그림: 위에서부터 가속도, 자이로, 자이로 크기, 정답 방향 점수(seed별 가는 선과 최소~최대 띠, 문턱 0.8), 발행 줄(seed별). '
             '점수는 1590 ms부터만 있고 그 앞은 빗금 영역으로 비워 둔다. 발행은 저장된 점수에서 다시 만들어 저장 로그와 같음을 확인했다.</p>',
             '<table><tr><th>번호</th><th>세션</th><th>방향</th><th>원본</th><th>태그</th><th>e</th><th>동작 종료</th><th>e−종료</th>'
             '<th>발행 seed 수</th><th>seed별 발행(시각 구간/방향)</th></tr>', *md_rows, '</table>']
    for r, svg in zip(summary["samples"], svgs):
        parts.append(f'<h2 id="{r["sample_id"]}">{r["sample_id"]} {r["session"]} {r["direction"]} {esc(Path(r["source_path"]).name)}</h2>')
        parts.append(svg)
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"


LIMITATIONS = [
    "표본은 고정 목록(세션×방향 추첨 20개 + 이상 사례 점검용 추가)이며 비율은 전체 성능이나 대표성의 추정치가 아니다.",
    "e와 main_motion_end_ms는 같은 자동 센서 도구의 결과다. 발행이 e 앞/뒤에 놓인 것은 실제 복귀 완료 여부를 증명하지 않는다.",
    "E=60과 5 seed는 진단용 고정 조건이며 기존 선택 E를 대체하지 않는다. 원본은 fold마다 한 번씩만 검증으로 쓰이므로 seed 5개는 같은 원본의 반복 관측이다.",
    "저장된 예측과 발행 로그를 읽기만 했다. 학습·추론·후처리 변경은 하지 않았다.",
    "그림 도구: 그래프 라이브러리 없이 손으로 쓴 SVG. 파형 축 범위는 표본마다 자동이며 표본 간 크기 비교용이 아니다.",
]


def group_counts(analyses):
    def count(name, subset):
        n_any = sum(1 for a in subset if any(a["seeds"][s]["events"] for s in SEEDS))
        n_all = sum(1 for a in subset if all(a["seeds"][s]["events"] for s in SEEDS))
        return {"group": name, "n_samples": len(subset), "samples_any": n_any, "samples_all_seeds": n_all}
    rows = [count("전체", analyses)]
    for tag in ("base", "large_gap", "clipped_horizon"):
        rows.append(count(f"태그 {tag}", [a for a in analyses if tag in a["sample"]["tags"]]))
    rows.append(count("추가 표본만(base 아님)", [a for a in analyses if a["sample"]["extra_for_anomaly_check"]]))
    return rows


def environment():
    return {"plotting": "no plotting library; hand-written SVG", "python": platform.python_version(),
            "numpy": np.__version__, "platform": platform.platform()}


def cmd_report(out=OUT_DIR):
    out = Path(out)
    manifest_path = out / MANIFEST_NAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"먼저 sample 명령으로 {manifest_path}를 만든다")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # manifest가 현재 입력과 같은 규칙에서 나온 것인지 확인한다(그림은 manifest의 목록만 쓴다).
    data, by_path = v2.load_records()
    if manifest["hashes"]["records_json"]["sha256"] != digest(v2.RECORDS):
        raise Mismatch("records.json 해시가 manifest와 다르다")
    ann, cand_hashes = load_annotations()
    if manifest["hashes"]["candidate_json"] != cand_hashes:
        raise Mismatch("후보 JSON 해시가 manifest와 다르다")
    check_annotation_consistency(data["records"], ann)
    again, _, _ = select_samples(data["records"], ann, manifest["rng"]["seed"])
    if again != manifest["samples"]:
        raise Mismatch("같은 seed로 다시 고른 표본이 manifest와 다르다")
    samples = manifest["samples"]
    for s in samples:
        a = ann[s["source_path"]]
        if (a["main_motion_start_ms"], a["main_motion_end_ms"], a["completion_ms"]) != \
                (s["main_motion_start_ms"], s["main_motion_end_ms"], s["completion_ms"]):
            raise Mismatch(f"주석 값이 manifest와 다르다: {s['source_path']}")
    store = RunStore()
    analyses = [analyse_sample(s, store, by_path) for s in samples]
    svgs, names = [], []
    for a in analyses:
        s = a["sample"]
        ts, raw = v2.read_sensor(ROOT / s["source_path"])
        svgs.append(render_svg(s, ts, raw, a["seeds"]))
        names.append(f"{s['sample_id']}-{s['session']}-{s['direction']}-{Path(s['source_path']).stem}.svg")
    re_checks = [c for a in analyses for c in a["rederivation"]]
    tr_checks = [c for a in analyses for c in a["training_exclusion"]]
    summary = {
        "version": SUMMARY_VERSION, "created_kst": now(),
        "manifest": {"path": MANIFEST_NAME, "sha256": digest(manifest_path)},
        "condition": {"epoch": EPOCH, "seeds": list(SEEDS),
                      "rule": "P1~P4 원본: V2-S-P5-cal의 해당 세션 검증 fold, P5 원본: V2-S-P1-cal의 P5 검증 fold",
                      "post_processing": "v2.issue_events 고정(문턱 .8, 마진 .2, 연속 2회, NONE 2회 재무장)"},
        "environment": environment(),
        "notice": NOTICE_E, "notice_proportion": NOTICE_PROPORTION,
        "samples": sample_rows(analyses), "emissions": emission_rows(analyses),
        "clip_level_counts": clip_level_counts(analyses), "group_counts": group_counts(analyses),
        "integrity": {
            "emission_rederivation": {
                "n_checks": len(re_checks), "n_pass": sum(c["equal"] for c in re_checks),
                "max_abs_score_diff": max(c["max_abs_score_diff"] for c in re_checks),
                "n_score_bit_equal": sum(c["score_bit_equal"] for c in re_checks), "checks": re_checks},
            "training_exclusion": {"n_checks": len(tr_checks), "n_pass": sum(c["ok"] for c in tr_checks), "checks": tr_checks},
            "window_alignment": {"n_checks": len(analyses), "n_pass": sum(a["window_alignment_ok"] for a in analyses),
                                 "first_decision_ms": v2.FIRST_T, "last_decision_ms": v2.LAST_T, "stride_ms": v2.STRIDE * 10},
            "targets_match_positive_rule": {"n_checks": len(re_checks), "n_pass": len(re_checks)}},
        "limitations": LIMITATIONS,
        "files": {"svg": names, "report": "report.html", "summary_md": "summary.md"}}
    targets = [out / n for n in names] + [out / n for n in ("report.html", "summary.json", "summary.md")]
    ensure_new(targets)
    for n, svg in zip(names, svgs):
        write_text(out / n, svg)
    write_text(out / "report.html", render_html(summary, svgs))
    write_text(out / "summary.md", render_markdown(summary))
    dump(out / "summary.json", summary)
    print(f"report 저장: {out} (그림 {len(names)}개)")
    return summary


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("sample", "report"))
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()
    {"sample": cmd_sample, "report": cmd_report}[args.command](Path(args.out))


if __name__ == "__main__":
    main()
