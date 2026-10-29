"""BLE v2: 자세별 5세션(4초 클립) 데이터 준비, 분할, 창 생성, 재생 채점.

사용: ml/.venv/Scripts/python.exe ml/v2.py <명령>
  annotate  완료 후보를 세션별로 저장하고 data/annotations/ble-v2/records.json 생성
  split     분할 6개(C 1개, S-P1~P5) 저장
  verify    주석·분할 불변식 검사
  protocol  docs/experiments/ble-v2/results/protocol.json 저장(학습 전 1회)
  smoke     코드 점검용 짧은 학습(결과를 저장하지 않는다)

계획: docs/TrainingPlan.md "BLE v2 실험". 발행·채점 함수(issue_events, classify_events,
choose_training)는 v1(ml/baseline.py, 2026-10-27 삭제)의 동작을 그대로 옮긴 것이고, test_v2.py가
v1과 같던 출력의 지문으로 이를 확인한다. 3초 클립 전용 값(300행, 3000 ms 범위, 고정 세션 이름)만 바꿨다.

다른 실험이 창 생성이나 입력 채널을 바꿀 때는 fold_sets(window_fn=...)와 fit_snapshots에 넘기는
입력 채널 수로 바꾼다. 학습 데이터 증강은 fold_sets(augment_fn=...)로 학습 원본에만 사본을 더한다.
기본값은 위 계획의 조건 그대로다.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
os.environ.setdefault("TF_DETERMINISTIC_OPS", "1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT / "data/annotations/ble-v2"
SPLITS = ROOT / "data/splits"
DOC = ROOT / "docs/experiments/ble-v2"
RECORDS = ANN / "records.json"

SEED = 20261021
SEEDS = (20261021, 20261022, 20261023, 20261024, 20261025)
CLASSES = ("NONE", "UP", "DOWN", "LEFT", "RIGHT")
DIRECTIONS = CLASSES[1:]
AXES = ("accX", "accY", "accZ", "gyrX", "gyrY", "gyrZ")

SESSIONS = {
    "P1": "phone-20261025-150714",
    "P2": "phone-20261025-154609",
    "P3": "phone-20261025-155510",
    "P4": "phone-20261025-160407",
    "P5": "phone-20261025-161530",
}
POSTURES = {
    "P1": "앉은 자세",
    "P2": "누운 채 팔을 침대에 그대로 내림",
    "P3": "누운 채 팔을 하늘로 90도 올림",
    "P4": "돌아누워 팔을 꺾음",
    "P5": "돌아누워 팔을 꺾지 않음",
}
SESSION_KEYS = tuple(SESSIONS)
OFFICIAL_S = "P5"

GESTURE_ROWS = 400      # 4초
LONG_ROWS = 1000        # idle/other 10초
WINDOW = 160
STRIDE = 5
FIRST_T = (WINDOW - 1) * 10          # 첫 판정 시각 1590 ms
LAST_T = (GESTURE_ROWS - 1) * 10     # 방향 클립의 마지막 판정 시각 3990 ms
CUE_MS = 1000
POSITIVE_MS = 150
MATCH_MS = 500
N_FOLDS_C = 5
EPOCH_CANDIDATES = (1, 5, 10, 20, 30, 40, 60)
BATCH_SIZE = 16
SESSION_INFO = {"gyro_range_dps": 2000, "gesture_samples": 400, "pre_roll_cue_ms": 1000}


def dump(path, value):
    """JSON을 LF로 저장한다(Windows에서 write_text는 \\n을 \\r\\n으로 바꾼다)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.write_bytes(text.encode("utf-8"))


def digest(path):
    """줄바꿈(CRLF/LF)과 무관한 SHA-256. 저장소는 core.autocrlf=true라 체크아웃 환경마다 파일 바이트가 다르다."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def now():
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")


# ---------------------------------------------------------------- 센서·창

def expected_rows(name):
    return GESTURE_ROWS if name.startswith("raw_") else LONG_ROWS


def clip_kind(name):
    return name.split(".")[0]


def clip_index(name):
    return int(name.split(".")[1])


def read_sensor(path):
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["timestamp", *AXES]:
            raise ValueError(f"Invalid axis order: {path}")
        rows = list(reader)
    a = np.array([[float(r[k]) for k in ("timestamp", *AXES)] for r in rows], dtype=np.float64)
    if not np.isfinite(a).all() or a[0, 0] != 0 or not np.all(np.diff(a[:, 0]) == 10):
        raise ValueError(f"Nonfinite/discontinuous sensor file: {path}")
    if len(a) != expected_rows(path.name):
        raise ValueError(f"Unexpected row count {len(a)}: {path}")
    return a[:, 0], a[:, 1:]


def decision_times(rows):
    """판정 시각: 160행이 찬 시점부터 5행(50 ms)마다. 앞부분을 가짜 값으로 채우지 않는다."""
    return np.arange(WINDOW - 1, rows, STRIDE) * 10


def positive_count(e, rows=GESTURE_ROWS):
    t = decision_times(rows)
    return int(np.sum((t >= e) & (t < e + POSITIVE_MS)))


def windows(record, mean, std, root=ROOT):
    """원본 하나를 160행 창으로 자른다. t는 창의 마지막 실제 샘플 시각이다."""
    ts, raw = read_sensor(Path(root) / record["source_path"])
    return windows_from_raw(record, ts, raw, mean, std)


def windows_from_raw(record, ts, raw, mean, std):
    """windows와 같되 이미 읽은(또는 증강한) 원시 배열을 받는다. 방향 라벨 시각은 record["completion_ms"]다."""
    ends = np.arange(WINDOW - 1, len(raw), STRIDE)
    x = np.stack([raw[i - (WINDOW - 1):i + 1] for i in ends])
    y = np.zeros(len(ends), dtype=np.int64)
    e = record["completion_ms"]
    if e is not None:
        mask = (ts[ends] >= e) & (ts[ends] < e + POSITIVE_MS)
        y[mask] = CLASSES.index(record["direction"])
        categories = ["pre_cue" if t < CUE_MS else "in_progress" if t < e else "post_completion" for t in ts[ends]]
    else:
        categories = [record["kind"]] * len(ends)
    x = ((x - mean) / std).astype(np.float32)
    assert x.shape[1:] == (WINDOW, len(AXES)) and np.isfinite(x).all()
    meta = [{"source_path": record["source_path"], "timestamp_ms": int(ts[i]),
             "target": int(label), "none_group": category} for i, label, category in zip(ends, y, categories)]
    return x, y, meta


def normalization(train_records, root=ROOT):
    """정규화 통계는 넘겨받은 학습 원본의 행으로만 계산한다."""
    raw = np.concatenate([read_sensor(Path(root) / r["source_path"])[1] for r in train_records])
    return raw.mean(axis=0), np.maximum(raw.std(axis=0), 1e-6)


def choose_training(y, meta, seed=SEED):
    """양성 창 수만큼 NONE을 종류별 라운드로빈으로 고정 추출한다(v1과 같음)."""
    rng = np.random.default_rng(seed)
    positive = np.flatnonzero(y != 0).tolist()
    groups = defaultdict(lambda: defaultdict(list))
    for i in np.flatnonzero(y == 0):
        groups[meta[i]["none_group"]][meta[i]["source_path"]].append(int(i))
    for files in groups.values():
        for indices in files.values():
            rng.shuffle(indices)
    queues = {}
    for name, files in sorted(groups.items()):
        queue = []
        while any(files.values()):
            for src in sorted(files):
                if files[src]:
                    queue.append(files[src].pop())
        queues[name] = queue
    none = []
    positions = Counter()
    while len(none) < len(positive):
        changed = False
        for name, queue in queues.items():
            if positions[name] < len(queue) and len(none) < len(positive):
                none.append(queue[positions[name]])
                positions[name] += 1
                changed = True
        if not changed:
            break
    assert positive and none
    return np.array(sorted(positive + none), dtype=np.int64)


# ---------------------------------------------------------------- 발행·채점 (v1과 같은 동작)

def issue_events(times, scores):
    """파일마다 초기화. 두 번째 연속 조건 충족 시 발행하고 잠그며, 확실한 NONE 2회로 재무장한다."""
    events = []
    locked, candidate, count, none_count = False, None, 0, 0
    for t, p in zip(times, scores):
        top = int(np.argmax(p))
        if locked:
            none_count = none_count + 1 if top == 0 and p[0] >= .8 else 0
            if none_count >= 2:
                locked, candidate, count, none_count = False, None, 0, 0
            continue
        margin = np.sort(p)[-1] - np.sort(p)[-2]
        if top != 0 and p[top] >= .8 and margin >= .2:
            count = count + 1 if top == candidate else 1
            candidate = top
            if count >= 2:
                events.append({"timestamp_ms": int(t), "class_index": top, "score": float(p[top])})
                locked, candidate, count, none_count = True, None, 0, 0
        else:
            candidate, count = None, 0
    return events


def classify_events(record, events):
    """완료 시각 e는 사후 채점에만 쓴다. 발행 과정에는 쓰지 않는다."""
    e = record["completion_ms"]
    matched = False
    counts = Counter({k: 0 for k in ("correct", "missed", "wrong_direction", "duplicate", "early", "late_unmatched", "background_false")})
    delays = []
    annotated = []
    for event in events:
        event = dict(event)
        t = event["timestamp_ms"]
        if e is None:
            kind = "background_false"
        elif t < e:
            kind = "early"
        elif t > e + MATCH_MS:
            kind = "late_unmatched"
        elif event["class_index"] != CLASSES.index(record["direction"]):
            kind = "wrong_direction"
        elif matched:
            kind = "duplicate"
        else:
            kind, matched = "correct", True
            delays.append(t - e)
        counts[kind] += 1
        event["kind"] = kind
        annotated.append(event)
    if e is not None and not matched:
        counts["missed"] = 1
    return dict(counts), delays, annotated


UNMATCHED_ON_GESTURE = ("wrong_direction", "duplicate", "early", "late_unmatched")


def score_events(val_chunks, scores):
    """검증·평가 원본을 파일별 독립 replay로 채점한다. NONE 창을 줄이지 않는다."""
    totals, offset, per_source = Counter(), 0, []
    for record, _, labels, meta in val_chunks:
        n = len(labels)
        events = issue_events([m["timestamp_ms"] for m in meta], scores[offset:offset + n])
        counts, delays, annotated = classify_events(record, events)
        totals.update(counts)
        per_source.append({"source_path": record["source_path"], "counts": counts, "delays_ms": delays, "events": annotated})
        offset += n
    assert offset == len(scores)
    return dict(totals), per_source


def selection_score(per_source):
    """E 선택 점수: (정검출 − 방향 원본의 미매칭 발행) ÷ 방향 원본 수. 배경 오발행은 넣지 않는다."""
    direction = [p for p in per_source if p["source_path"].rsplit("/", 1)[-1].startswith("raw_")]
    correct = sum(p["counts"].get("correct", 0) for p in direction)
    unmatched = sum(sum(p["counts"].get(k, 0) for k in UNMATCHED_ON_GESTURE) for p in direction)
    return (correct - unmatched) / len(direction), correct, unmatched, len(direction)


# ---------------------------------------------------------------- 주석·records

def run_completion_tool(session_dir, id_start):
    out = subprocess.run(
        ["node", "tools/suggest-gesture-completions.js", "--local-dir", f"data/sessions/{session_dir}",
         "--format", "json", "--id-start", str(id_start)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
    return out.stdout


def check_session_info(key, folder):
    info = (ROOT / "data/sessions" / folder / "session_info.txt").read_text(encoding="utf-8")
    for name, expected in SESSION_INFO.items():
        found = [int(v) for v in re.findall(rf"(?:^|\s){name}=(\d+)", info, flags=re.M)]
        if found != [expected]:
            raise ValueError(f"{folder}: {name}={found}, expected {expected}")
    if f"posture={key}" not in info:
        raise ValueError(f"{folder}: posture={key} 줄이 없다")


def parse_exclusions(folder):
    excluded = []
    d = ROOT / "data/sessions" / folder / "excluded"
    note = d / "EXCLUDED.txt"
    lines = note.read_text(encoding="utf-8").splitlines() if note.exists() else []
    for f in sorted(d.glob("*.csv")) if d.exists() else []:
        reason = next((ln[len(f.name):].strip() for ln in lines if ln.startswith(f.name)), "")
        excluded.append({"source_path": f"data/sessions/{folder}/excluded/{f.name}", "sha256": digest(f), "reason": reason})
    return excluded


def annotate():
    if RECORDS.exists():
        raise FileExistsError("records.json이 이미 있다. 덮어쓰지 않는다. 바꾸려면 새 버전을 만든다")
    records, excluded, candidate_files = [], [], {}
    for n, (key, folder) in enumerate(SESSIONS.items()):
        check_session_info(key, folder)
        session_dir = ROOT / "data/sessions" / folder
        raw_json = run_completion_tool(folder, 9000000000 + n * 1000)
        cand_path = ANN / f"{folder}-candidates.json"
        cand_path.parent.mkdir(parents=True, exist_ok=True)
        cand_path.write_bytes(raw_json.replace("\r\n", "\n").encode("utf-8"))
        candidate_files[cand_path.name] = digest(cand_path)
        by_name = {a["filename"]: a for a in json.loads(raw_json)["annotations"]}
        files = sorted(session_dir.glob("*.csv"), key=lambda p: (clip_kind(p.name), clip_index(p.name)))
        direction_files = [p for p in files if p.name.startswith("raw_")]
        assert {p.name for p in direction_files} == set(by_name), f"{folder}: 후보와 파일이 다르다"
        for p in files:
            kind = clip_kind(p.name)
            ts, values = read_sensor(p)
            record = {"source_path": f"data/sessions/{folder}/{p.name}", "session": key, "posture": POSTURES[key],
                      "kind": kind, "rows": len(ts), "sha256": digest(p),
                      "peak_gyro_dps": round(float(np.abs(values[:, 3:]).max()), 1)}
            if kind.startswith("raw_"):
                a = by_name[p.name]
                e = a["completion_ms"]
                record.update(direction=a["direction"], completion_ms=e, annotation_status=a["status"],
                              annotation_flags=a["flags"], positive_windows=positive_count(e),
                              positive_truncated=positive_count(e) < 3,
                              match_horizon_clipped=bool(e + MATCH_MS > LAST_T),
                              decision="ACCEPT_SENSOR_LABEL")
            else:
                record.update(direction="NONE", completion_ms=None, decision="ACCEPT_RECORDING_LABEL")
            records.append(record)
        excluded += parse_exclusions(folder)
    assert len({r["source_path"] for r in records}) == len(records)
    assert len({r["sha256"] for r in records}) == len(records), "내용이 같은 파일이 있다"
    out = {"version": "ble-v2", "created_kst": now(), "classes": CLASSES, "axes": AXES,
           "definition": "완료 시각은 센서 기반 자동 후보(tools/suggest-gesture-completions.js)이며 영상·사용자 확인이 없다. "
                         "REVIEW 클립은 사용자가 파형을 보고 남긴 것이고 자동 완료 시각을 그대로 쓴다.",
           "sessions": {k: {"folder": f, "posture": POSTURES[k]} for k, f in SESSIONS.items()},
           "annotation_sha256": candidate_files, "records": records, "excluded_by_user": excluded}
    dump(RECORDS, out)
    print_annotation_summary(out)


def print_annotation_summary(out):
    recs = out["records"]
    print("clips:", dict(Counter(r["kind"] for r in recs)), "excluded:", len(out["excluded_by_user"]))
    for k in SESSION_KEYS:
        d = [r for r in recs if r["session"] == k and r["direction"] != "NONE"]
        print(k, "direction", len(d), dict(Counter(r["direction"] for r in d)),
              "status", dict(Counter(r["annotation_status"] for r in d)),
              "flags", dict(Counter(f for r in d for f in r["annotation_flags"].split("|") if f)))
    d = [r for r in recs if r["direction"] != "NONE"]
    print("positive windows:", dict(sorted(Counter(r["positive_windows"] for r in d).items())))
    print("completion_ms min/median/max:", min(r["completion_ms"] for r in d),
          int(np.median([r["completion_ms"] for r in d])), max(r["completion_ms"] for r in d))
    print("match horizon clipped (e > %d):" % (LAST_T - MATCH_MS), [r["source_path"].split("/", 2)[-1] for r in d if r["match_horizon_clipped"]])
    print("positive < 3 windows:", [r["source_path"].split("/", 2)[-1] for r in d if r["positive_truncated"]])


def load_records(verify_hash=True):
    data = json.loads(RECORDS.read_text(encoding="utf-8"))
    by_path = {r["source_path"]: r for r in data["records"]}
    if verify_hash:
        for r in data["records"]:
            assert digest(ROOT / r["source_path"]) == r["sha256"], r["source_path"]
        for name, sha in data["annotation_sha256"].items():
            assert digest(ANN / name) == sha, name
    return data, by_path


# ---------------------------------------------------------------- 분할

def natural(r):
    return clip_index(Path(r["source_path"]).name)


def label_of(r):
    return r["direction"] if r["direction"] != "NONE" else r["kind"]


def paths(recs):
    return sorted(r["source_path"] for r in recs)


def counts_by(recs):
    c = Counter(label_of(r) for r in recs)
    return {k: c.get(k, 0) for k in (*DIRECTIONS, "idle", "other")}


def base_split(name, description, data):
    return {"version": "ble-v2", "name": name, "description": description, "seed": SEED, "classes": CLASSES,
            "records_sha256": digest(RECORDS)}


def split_c(data):
    recs = data["records"]
    rng = np.random.default_rng(SEED)
    evaluation = []
    for s in SESSION_KEYS:
        mine = [r for r in recs if r["session"] == s]
        for d in DIRECTIONS:
            g = sorted([r for r in mine if r["direction"] == d], key=natural)
            evaluation += [g[i] for i in sorted(rng.choice(len(g), size=3, replace=False).tolist())]
        for kind in ("idle", "other"):
            g = sorted([r for r in mine if r["kind"] == kind], key=natural)
            evaluation.append(g[int(rng.integers(len(g)))])
    eval_paths = {r["source_path"] for r in evaluation}
    train = [r for r in recs if r["source_path"] not in eval_paths]
    pointer, fold_of = Counter(), {}
    for label in (*DIRECTIONS, "idle", "other"):
        for s in SESSION_KEYS:
            g = sorted([r for r in train if label_of(r) == label and r["session"] == s], key=natural)
            for j, i in enumerate(rng.permutation(len(g)).tolist()):
                fold_of[g[i]["source_path"]] = (pointer[label] + j) % N_FOLDS_C
            pointer[label] += len(g)
    folds = [{"fold": k, "validation_sources": sorted(p for p, f in fold_of.items() if f == k)} for k in range(N_FOLDS_C)]
    out = base_split("C", "세션×방향마다 3개, 세션마다 idle 1·other 1을 평가용으로 뗀 분할(방식 C)", data)
    out.update(eval_sources=paths(evaluation), train_sources=paths(train),
               cv={"unit": "clip", "n_folds": N_FOLDS_C,
                   "rule": "라벨(방향·idle·other)마다 포인터를 이어 가며 세션 순서로 라운드로빈. 각 (라벨, 세션) 안에서는 seed로 섞음",
                   "folds": folds},
               draw_order="rng=default_rng(20261021): 세션 P1~P5 순으로 [UP,DOWN,LEFT,RIGHT 각 choice(3), idle integers, other integers], 이어서 fold 배정 permutation",
               counts={"eval": counts_by(evaluation), "train": counts_by(train)})
    return "C", out


def split_s(data, held):
    recs = data["records"]
    evaluation = [r for r in recs if r["session"] == held]
    train = [r for r in recs if r["session"] != held]
    folds = []
    for k, s in enumerate(x for x in SESSION_KEYS if x != held):
        folds.append({"fold": k, "held_out_session": s,
                      "validation_sources": paths([r for r in train if r["session"] == s])})
    out = base_split(f"S-{held}", f"세션 {held}({POSTURES[held]})를 통째로 평가용으로 뗀 분할(방식 S)" +
                     ("; 공식 S" if held == OFFICIAL_S else "; 회전"), data)
    out.update(held_out_session=held, official=held == OFFICIAL_S,
               eval_sources=paths(evaluation), train_sources=paths(train),
               cv={"unit": "session", "n_folds": len(folds), "folds": folds},
               counts={"eval": counts_by(evaluation), "train": counts_by(train)})
    return f"S-{held}", out


def make_splits():
    data, _ = load_records()
    built = [split_c(data)] + [split_s(data, s) for s in SESSION_KEYS]
    for name, _ in built:
        if (SPLITS / f"v2-{name}.json").exists():
            raise FileExistsError(f"v2-{name}.json이 이미 있다. 덮어쓰지 않는다")
    for name, out in built:
        dump(SPLITS / f"v2-{name}.json", out)
        print(name, "eval", out["counts"]["eval"], "train", out["counts"]["train"])
    verify()


def load_split(name):
    return json.loads((SPLITS / f"v2-{name}.json").read_text(encoding="utf-8"))


SPLIT_NAMES = ("C", *(f"S-{s}" for s in SESSION_KEYS))


def verify():
    data, by_path = load_records()
    all_paths = set(by_path)
    for name in SPLIT_NAMES:
        sp = load_split(name)
        ev, tr = set(sp["eval_sources"]), set(sp["train_sources"])
        assert sp["records_sha256"] == digest(RECORDS)
        assert not ev & tr and ev | tr == all_paths, name
        assert len(ev) == len(sp["eval_sources"]) and len(tr) == len(sp["train_sources"])
        fold_paths = [p for f in sp["cv"]["folds"] for p in f["validation_sources"]]
        assert len(fold_paths) == len(set(fold_paths)) and set(fold_paths) == tr, f"{name}: fold가 학습용을 나누지 못했다"
        assert sp["cv"]["n_folds"] == len(sp["cv"]["folds"])
        if name == "C":
            sessions_eval = Counter((by_path[p]["session"], label_of(by_path[p])) for p in ev)
            for s in SESSION_KEYS:
                for d in DIRECTIONS:
                    assert sessions_eval[(s, d)] == 3, (s, d)
                assert sessions_eval[(s, "idle")] == 1 and sessions_eval[(s, "other")] == 1
            per_label = defaultdict(list)
            for f in sp["cv"]["folds"]:
                for label, n in Counter(label_of(by_path[p]) for p in f["validation_sources"]).items():
                    per_label[label].append(n)
            # 균형은 처음 뽑을 때만 보장한다. 수정된 분할은 다시 뽑지 않고 제외 경로만 뺐으므로 fold 크기가 달라질 수 있다
            if not sp.get("revisions"):
                assert all(max(v) - min(v) <= 1 for v in per_label.values()), "fold별 라벨 수 차이가 1을 넘는다"
        else:
            held = sp["held_out_session"]
            assert {by_path[p]["session"] for p in ev} == {held}
            assert ev == {p for p, r in by_path.items() if r["session"] == held}
            for f in sp["cv"]["folds"]:
                assert {by_path[p]["session"] for p in f["validation_sources"]} == {f["held_out_session"]}
                assert f["held_out_session"] != held
    print("verify OK:", ", ".join(SPLIT_NAMES))


# ---------------------------------------------------------------- 학습 집합·학습

def make_chunks(recs, mean, std, root=ROOT, window_fn=None):
    """원본마다 (record, x, y, meta). window_fn은 windows_from_raw와 같은 (record, ts, raw, mean, std) → (x, y, meta) 함수다."""
    window_fn = window_fn or windows_from_raw
    chunks = []
    for r in recs:
        ts, raw = read_sensor(Path(root) / r["source_path"])
        chunks.append((r, *window_fn(r, ts, raw, mean, std)))
    return chunks


def augment_chunks(recs, mean, std, root, window_fn, augment_fn):
    """학습 원본의 증강 사본 청크를 만든다.

    augment_fn(record, ts, raw)는 사본마다 (record 사본, raw 사본, valid_rows) 또는 None(만들지 않은 사본)의 목록을 돌려준다.
    record 사본의 source_path는 "<원본 경로>#<사본 이름>"이어야 한다(choose_training이 사본을 별도 원본으로 다룬다).
    raw 사본은 원본과 같은 행 수이며, valid_rows 이후 행은 원본 범위 밖이라 그 행을 포함하는 창(마지막 샘플 행 ≥ valid_rows)은 버린다.
    """
    window_fn = window_fn or windows_from_raw
    chunks, skipped, excluded = [], 0, 0
    for r in recs:
        ts, raw = read_sensor(Path(root) / r["source_path"])
        for copy in augment_fn(r, ts, raw):
            if copy is None:
                skipped += 1
                continue
            rc, raw_c, valid_rows = copy
            assert rc["source_path"].startswith(r["source_path"] + "#") and raw_c.shape == raw.shape
            if not 0 < valid_rows <= len(raw):
                raise ValueError(f"valid_rows {valid_rows}가 1~{len(raw)} 밖이다: {rc['source_path']}. 만들지 않는 사본은 None으로 돌려준다")
            x, y, meta = window_fn(rc, ts, raw_c, mean, std)
            keep = np.array([m["timestamp_ms"] <= ts[valid_rows - 1] for m in meta])
            excluded += int((~keep).sum())
            chunks.append((rc, x[keep], y[keep], [m for m, k in zip(meta, keep) if k]))
    return chunks, skipped, excluded


def build_sets(train_recs, val_recs, root=ROOT, none_seed=SEED, window_fn=None, none_fn=None, augment_fn=None):
    """원본 분할 → 학습 원본만으로 정규화 → 창 생성(학습만 증강 사본 추가) → 학습에만 NONE 추출. 검증은 전체 replay.

    window_fn은 windows_from_raw와 같은 (record, ts, raw, mean, std) → (x, y, meta) 함수다. 없으면 windows_from_raw를 쓴다.
    none_fn은 choose_training과 같은 (y, meta, seed) → 학습 창 번호 함수다. 없으면 choose_training을 쓴다.
    augment_fn은 augment_chunks 설명과 같다. 없으면 증강하지 않는다. 정규화 통계는 원본 학습 클립으로만 계산한다.
    """
    assert {r["source_path"] for r in train_recs}.isdisjoint(r["source_path"] for r in val_recs)
    mean, std = normalization(train_recs, root)
    train_chunks = make_chunks(train_recs, mean, std, root, window_fn)
    skipped = excluded = 0
    if augment_fn is not None:
        aug, skipped, excluded = augment_chunks(train_recs, mean, std, root, window_fn, augment_fn)
        train_chunks += aug
    x = np.concatenate([c[1] for c in train_chunks])
    y = np.concatenate([c[2] for c in train_chunks])
    meta = sum([c[3] for c in train_chunks], [])
    idx = (none_fn or choose_training)(y, meta, none_seed)
    val_chunks = make_chunks(val_recs, mean, std, root, window_fn)
    assert not any("#" in c[0]["source_path"] for c in val_chunks), "검증 원본은 증강하지 않는다"
    return {"x_train": x[idx], "y_train": y[idx], "train_all_counts": np.bincount(y, minlength=5).tolist(),
            "train_counts": np.bincount(y[idx], minlength=5).tolist(),
            "train_none_groups": dict(Counter(meta[i]["none_group"] for i in idx if y[i] == 0)),
            "train_aug_copies": len(train_chunks) - len(train_recs), "train_aug_skipped": skipped,
            "train_windows_excluded": excluded,
            "val": val_chunks, "mean": mean, "std": std, "train_sources": len(train_recs), "val_sources": len(val_recs)}


def fold_sets(by_path, split, k, window_fn=None, none_fn=None, augment_fn=None):
    val = set(split["cv"]["folds"][k]["validation_sources"])
    assert val <= set(split["train_sources"]) and not val & set(split["eval_sources"])
    train_recs = [by_path[p] for p in split["train_sources"] if p not in val]
    val_recs = [by_path[p] for p in split["train_sources"] if p in val]
    return build_sets(train_recs, val_recs, window_fn=window_fn, none_fn=none_fn, augment_fn=augment_fn)


_tf_ready = False
tf_threads_fixed = None


def configure_tf():
    """스레드 1개 + 연산 결정성. 같은 프로세스에서 TensorFlow가 이미 초기화됐으면 스레드 수는 못 바꾼다.

    실험 실행기는 새 프로세스에서 시작하므로 항상 고정된다. 이미 초기화된 경우(테스트 묶음 실행)는
    tf_threads_fixed=False로 남기고, 결정성 연산만 켠 채 진행한다.
    """
    global _tf_ready, tf_threads_fixed
    import tensorflow as tf
    if not _tf_ready:
        try:
            tf.config.threading.set_intra_op_parallelism_threads(1)
            tf.config.threading.set_inter_op_parallelism_threads(1)
            tf_threads_fixed = True
        except RuntimeError:
            tf_threads_fixed = False
        tf.config.experimental.enable_op_determinism()
        _tf_ready = True
    return tf


def model_params(channels=len(AXES)):
    """build_model(WINDOW)의 파라미터 수. 입력 채널이 하나 늘 때마다 첫 Conv(커널 5, 필터 16) 가중치가 80개 는다."""
    return 9493 + 80 * (channels - len(AXES))


def fit_snapshots(x_train, y_train, x_val, seed, epochs, model_fn=None):
    """max(epochs)까지 한 번 학습하고 epochs에 든 epoch가 끝날 때마다 검증 점수를 저장한다.

    입력 채널 수는 x_train에서 읽는다(기본 6축). model_fn(channels)을 주면 그 모델을 쓴다(기본 build_model).
    """
    tf = configure_tf()
    from model import build_model

    class Snapshot(tf.keras.callbacks.Callback):
        def __init__(self):
            super().__init__()
            self.scores = {}

        def on_epoch_end(self, epoch, logs=None):
            if epoch + 1 in epochs:
                self.scores[epoch + 1] = self.model(x_val, training=False).numpy()

    options = tf.data.Options()
    options.threading.private_threadpool_size = 1
    tf.keras.backend.clear_session()
    tf.keras.utils.set_random_seed(seed)
    channels = x_train.shape[2]
    if model_fn is None:
        model = build_model(WINDOW, channels=channels)
        assert model.count_params() == model_params(channels)
    else:
        model = model_fn(channels)
    # y_train이 확률 벡터(부드러운 라벨)면 categorical, 클래스 번호면 sparse 교차 엔트로피
    loss = "categorical_crossentropy" if y_train.ndim == 2 else "sparse_categorical_crossentropy"
    model.compile(optimizer=tf.keras.optimizers.Adam(.001), loss=loss)
    ds = (tf.data.Dataset.from_tensor_slices((x_train, y_train)).shuffle(len(y_train), seed=seed)
          .batch(BATCH_SIZE).with_options(options))
    snap = Snapshot()
    hist = model.fit(ds, epochs=max(epochs), verbose=0, shuffle=False, callbacks=[snap])
    return snap.scores, hist.history["loss"]


# ---------------------------------------------------------------- protocol·smoke

PROTOCOL_CONDITIONS = {
    "input": "100 Hz 6축, 160행×6, 5행(50 ms)마다 판정, t=창의 마지막 실제 샘플 시각, 첫 판정 1590 ms",
    "label": "자연 복귀 완료 e에 대해 e <= t < e+150 ms만 방향, 나머지 NONE(복귀 중 포함). idle/other 클립 전체 NONE",
    "model": "ml/model.py build_model(160) 기본값: Conv16k5-Pool2-Drop.2-Conv32k5-Pool2-Flatten-Drop.3-Dense5, 9,493 파라미터",
    "training": {"optimizer": "Adam lr=0.001", "loss": "sparse_categorical_crossentropy", "batch_size": 16,
                 "augmentation": None, "class_weight": None, "early_stopping": None,
                 "threads": "intra=1 inter=1, enable_op_determinism, oneDNN off"},
    "none_selection": "학습에만. 양성 창 수만큼 NONE을 종류(in_progress, post_completion, idle, other)별 라운드로빈으로 고정 추출. 추출 seed는 20261021 고정(학습 seed와 별개)",
    "postprocess": {"score_threshold": .8, "margin": .2, "consecutive_direction": 2, "consecutive_none_rearm": 2},
}
PROTOCOL_ORDER = [
    "1. 원본 클립을 먼저 나눈다(평가용/학습용, 학습용 안의 fold). 같은 원본의 창은 한쪽에만 둔다",
    "2. 원본마다 160행 창을 50 ms 간격으로 만든다. 파일 경계를 넘어 붙이지 않는다",
    "3. 정규화 평균·표준편차는 학습 부분 원본의 행으로만 계산한다. 교차검증은 fold마다 다시 계산한다",
    "4. NONE 추출은 학습 부분에만 한다. 검증·평가는 모든 판정 시각을 그대로 replay한다",
    "5. 검증·평가 데이터에서 계산한 값은 학습 설정에 쓰지 않는다",
]
PROTOCOL_EVENTS = {
    "decision_times": "160행이 찬 1590 ms부터 50 ms마다. 그 전 구간은 판정하지 않음",
    "emit_time": "발행 조건을 처음 만족한 판정 시각(두 번째 연속 창의 마지막 샘플 시각)",
    "initial_state": "원본마다 잠금 해제·후보 없음으로 시작. 원본 사이에 상태를 넘기지 않음",
    "completion_ms_use": "정답 라벨과 사후 채점에만 사용. 발행·재무장에는 사용하지 않음",
    "classification_order": ["배경 원본 → background_false", "t < e → early", "t > e+500 → late_unmatched",
                              "다른 방향 → wrong_direction", "이미 correct 있음 → duplicate", "그 밖 → correct", "correct 없음 → missed 1"],
    "match_horizon_clipped": f"e+500 > {LAST_T} (e > {LAST_T - MATCH_MS})인 원본은 그대로 채점하되 목록을 따로 표시",
}
PROTOCOL_SELECTION = {
    "candidates": EPOCH_CANDIDATES, "seeds": SEEDS,
    "training": "(seed, fold)마다 max(E)=60 epoch까지 한 번 학습하고 후보 epoch가 끝난 시점마다 검증 fold를 replay",
    "score": "seed마다 모든 fold 예측을 합쳐 (정검출 수 − 방향 원본의 미매칭 발행 수) ÷ 검증 방향 원본 수. 미매칭=wrong_direction+duplicate+early+late_unmatched. 배경 오발행은 점수에 넣지 않고 따로 보고",
    "rule": "5 seed 점수 평균이 가장 큰 E, 같으면 작은 E. 방식(그리고 S 회전)마다 같은 원칙으로 따로 선택",
}
PROTOCOL_REPORT = ["정검출 수/평가 방향 원본 수", "미매칭 발행: 종류별 원시 개수와 방향 원본 1개당 수", "누락: 원시 개수와 비율",
                   "배경 오발행: 원시 개수, 실제 판정 구간(클립마다 첫 판정 전 1.59초 제외), 관측 1분당 수",
                   "지연: 정검출의 완료→발행 median/p95와 표본 수", "모두 5 seed의 seed별 값과 평균·범위",
                   "C−S는 같은 seed끼리 차이를 seed별로, 평균·범위와 함께. 통계적 판정 규칙을 두지 않음",
                   "허용 구간이 잘린 원본(e>3490)과 양성 3창 미만 원본(e>3890)을 따로 표시"]


def protocol():
    out_path = DOC / "results/protocol.json"
    if out_path.exists():
        raise FileExistsError("protocol.json이 이미 있다. 학습 전 1회만 저장한다")
    verify()
    git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    out = {"experiment": "BLE-v2", "created_before_training_kst": now(),
           "records_sha256": digest(RECORDS),
           "split_sha256": {n: digest(SPLITS / f"v2-{n}.json") for n in SPLIT_NAMES},
           "official_S": f"S-{OFFICIAL_S}", "rotation_S": [f"S-{s}" for s in SESSION_KEYS if s != OFFICIAL_S],
           "fixed_conditions": PROTOCOL_CONDITIONS, "data_processing_order": PROTOCOL_ORDER,
           "events": PROTOCOL_EVENTS, "epoch_selection": PROTOCOL_SELECTION, "report": PROTOCOL_REPORT,
           "evaluation": "평가용은 각 방식의 최종 모델(5 seed)에 한 번만 적용한다. 결과를 보고 설정·주석·분할을 바꾸지 않는다",
           "code_check_note": "protocol 저장 전에 코드 점검용 짧은 학습을 했다: smoke(S-P5 학습용 안의 fold 하나, 5 epoch)와 test_v2_cal.py "
                              "(같은 fold 몇 epoch). 평가용은 열지 않았고 결과를 저장·선택에 쓰지 않았다",
           "hash_note": "SHA-256은 CRLF를 LF로 바꾼 바이트로 계산한다(저장소가 core.autocrlf=true라 체크아웃 환경마다 바이트가 다르다). "
                        "처음 만든 주석·분할·protocol(커밋 805f74a)은 이 정의 전이라 학습 전에 지우고 같은 내용으로 다시 만들었다",
           "code_sha256": {p: digest(ROOT / "ml" / p) for p in ("v2.py", "v2_cal.py", "model.py")},
           "git_head": git("rev-parse", "HEAD"), "git_status_short": git("status", "--short").splitlines()}
    dump(out_path, out)
    print("protocol saved", out_path)


def smoke():
    data, by_path = load_records()
    sp = load_split(f"S-{OFFICIAL_S}")
    t0 = time.time()
    d = fold_sets(by_path, sp, 0)
    print("fold 0 held-out session:", sp["cv"]["folds"][0]["held_out_session"],
          "train sources", d["train_sources"], "val sources", d["val_sources"])
    print("train windows (all):", d["train_all_counts"], "selected:", d["train_counts"], d["train_none_groups"])
    x_val = np.concatenate([c[1] for c in d["val"]])
    print("val windows:", len(x_val), "positives:", int(sum((c[2] != 0).sum() for c in d["val"])), "data prep s: %.1f" % (time.time() - t0))
    runs = []
    for attempt in range(2):
        t1 = time.time()
        scores, loss = fit_snapshots(d["x_train"], d["y_train"], x_val, SEED, (1, 5))
        print(f"run {attempt}: loss per epoch {[round(v, 4) for v in loss]}  {time.time() - t1:.1f}s")
        runs.append(scores)
    for e in (1, 5):
        diff = float(np.abs(runs[0][e] - runs[1][e]).max())
        print(f"E={e} 같은 seed 두 번 학습 점수 최대 차이: {diff}")
        assert diff == 0.0, "같은 seed 재현이 안 된다"
        assert np.isfinite(runs[0][e]).all() and np.allclose(runs[0][e].sum(axis=1), 1, atol=1e-4)
        totals, per_source = score_events(d["val"], runs[0][e])
        score, c, u, n = selection_score(per_source)
        print(f"E={e} 채점: {totals} 선택점수 {score:.3f} (정검출 {c}, 미매칭 {u}, 방향 원본 {n})")
    print("smoke OK (결과는 저장하지 않음)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=("annotate", "split", "verify", "protocol", "smoke"))
    cmd = p.parse_args().command
    {"annotate": annotate, "split": make_splits, "verify": verify, "protocol": protocol, "smoke": smoke}[cmd]()
