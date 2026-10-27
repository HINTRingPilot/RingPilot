"""Audit the fixed rotation+speed training data without importing TensorFlow or fitting models.

Run: ml/.venv/Scripts/python.exe tools/check-rotwarp-preflight.py --out <new-directory>
Writes an input/code manifest, per-copy measurements, and a nine-fold comparison.
Existing output directories are refused. Model and augmentation code are not changed.
"""

import argparse
from collections import Counter
import copy
import gc
import json
from pathlib import Path
import platform
import sys
import time
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml"))
import v2
import v2_return as vr


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def distribution(values):
    if not values:
        return None
    a = np.asarray(values, dtype=np.float64)
    return {"n": len(values), "min": float(a.min()), "median": float(np.median(a)),
            "p90": float(np.percentile(a, 90)), "max": float(a.max())}


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def inspect_copies(by_path):
    aug = vr.CONDITIONS["newtcnrotwarp"]["aug"]
    candidates = [a for f in sorted(vr.CANDIDATES.glob("*-candidates.json"))
                  for a in json.loads(f.read_text(encoding="utf-8"))["annotations"]]
    paths = [a["source_path"] for a in candidates]
    require(len(paths) == len(set(paths)), "Duplicate motion-start annotations")
    starts = vr.motion_starts()
    warp = vr.rotate_warp_augmenter(aug, starts=starts)
    rotate = vr.rotate_augmenter(vr.CONDITIONS["newtcnrot"]["aug"])
    measurements = []
    for path, record in sorted(by_path.items()):
        ts, raw = v2.read_sensor(ROOT / path)
        b = np.median(raw[:vr.PRECUE_SAMPLES, 3:6], axis=0)
        before = Counter(warp.stats)
        wc = warp(record, ts, raw)
        rc = rotate(record, ts, raw)
        reasons = Counter()
        for c, ((rw, xw, n), (rr, xr, nr)) in enumerate(zip(wc, rc), 1):
            rng = vr.clip_rng(path, c)
            vr.random_rotation(rng, aug["rot_y_deg"], aug["tilt_deg"])
            s = float(np.exp(rng.uniform(np.log(aug["scale_min"]), np.log(aug["scale_max"]))))
            require(aug["scale_min"] <= s <= aug["scale_max"], path)
            np.testing.assert_array_equal(xw[:90], xr[:90])
            np.testing.assert_array_equal(np.median(xw[:90, 3:6], axis=0),
                                          np.median(xr[:90, 3:6], axis=0))
            require(np.isfinite(xw).all(), f"Nonfinite copy: {rw['source_path']}")
            e = record["completion_ms"]
            shifted = None if e is None else aug["anchor_ms"] + s * (e - aug["anchor_ms"])
            jump = None
            if e is None:
                reason = "background"
            elif starts[path] < 900:
                reason = "early_start"
            else:
                src = aug["anchor_ms"] + (ts[90:] - aug["anchor_ms"]) / s
                src = src[src <= ts[-1]]
                interpolated = np.stack([np.interp(src, ts, xr[:, j]) for j in range(6)], axis=1)
                jump = float(np.max(np.abs(interpolated[0, 3:6] - b)) * abs(1 / s - 1))
                grid = v2.decision_times(len(raw))
                kept = grid[grid <= ts[90 + len(src) - 1]]
                lost = (int(np.sum((kept >= shifted) & (kept < shifted + v2.POSITIVE_MS)))
                        != int(np.sum((grid >= e) & (grid < e + v2.POSITIVE_MS))))
                reason = "positive_loss" if lost else "jump" if jump > aug["max_jump_dps"] else "warp"
                if reason == "warp":
                    expected_n = min(len(raw), int(np.floor((aug["anchor_ms"] +
                                     s * (ts[-1] - aug["anchor_ms"])) / vr.SAMPLE_MS)) + 1)
                    require(n == expected_n == 90 + len(src), f"Valid-row boundary: {rw['source_path']}")
                    interpolated[:, 3:6] = (interpolated[:, 3:6] - b) / s + b
                    np.testing.assert_allclose(xw[90:n], interpolated, rtol=0, atol=1e-12)
                    require(rw == {**rr, "completion_ms": shifted}, f"Changed record fields: {path}")
            if reason != "warp":
                require((rw, n) == (rr, nr), f"Fallback record mismatch: {path}")
                np.testing.assert_array_equal(xw, xr)
            times = v2.decision_times(len(raw))
            original_positive = 0 if e is None else int(np.sum((times >= e) & (times < e + v2.POSITIVE_MS)))
            retained = times[times <= ts[n - 1]]
            ec = rw["completion_ms"]
            copied_positive = 0 if ec is None else int(np.sum((retained >= ec) & (retained < ec + v2.POSITIVE_MS)))
            require(copied_positive == original_positive, f"Positive windows lost: {rw['source_path']}")
            reasons[reason] += 1
            measurements.append({"source_path": path, "copy_path": rw["source_path"], "reason": reason,
                                 "scale_drawn": s, "jump_dps": jump, "valid_rows": int(n),
                                 "last_valid_ms": float(ts[n - 1]), "original_positive": original_positive,
                                 "retained_positive": copied_positive,
                                 "excluded_windows": int(np.sum(times > ts[n - 1])),
                                 "motion_start_ms": starts.get(path),
                                 "transformed_start_ms": None if reason != "warp" else
                                 aug["anchor_ms"] + s * (starts[path] - aug["anchor_ms"]),
                                 "completion_ms": ec})
        require(reasons == Counter(warp.stats) - before, f"Reason accounting: {path}")
    require(len(measurements) == len(by_path) * aug["copies"], "Wrong copy count")
    return measurements, dict(warp.stats)


def inspect_fold(label, by_path, nb, split, k, copies):
    chosen = {}
    choose = v2.choose_training

    def capture(y, meta, seed=v2.SEED):
        idx = choose(y, meta, seed)
        require(len(set(idx.tolist())) == len(idx), "Duplicate selected windows")
        for i in idx:
            m = meta[int(i)]
            if label == "newtcnrotwarp" and "#" in m["source_path"]:
                require(m["timestamp_ms"] <= copies[m["source_path"]]["last_valid_ms"],
                        f"Invalid selected window: {m}")
        chosen["selected_count"] = len(idx)
        chosen["positive_by_copy"] = Counter(meta[int(i)]["source_path"] for i in idx if y[i] != 0)
        return idx

    with patch.object(v2, "choose_training", side_effect=capture):
        d, _ = vr.prepare_fold(label, by_path, nb, split, k)
    train_paths = set(split["train_sources"]) - set(split["cv"]["folds"][k]["validation_sources"])
    expected = [v for v in copies.values() if v["source_path"] in train_paths]
    require(d["train_aug_copies"] == len(expected) == 2 * len(train_paths), "Fold copy count")
    require(d["train_aug_skipped"] == 0, "An augmentation copy was omitted")
    if label == "newtcnrotwarp":
        require(d["train_aug_stats"] == dict(Counter(v["reason"] for v in expected)), "Fold reason counts")
        require(d["train_windows_excluded"] == sum(v["excluded_windows"] for v in expected), "Excluded-window counts")
    else:
        require(d["train_windows_excluded"] == 0, "Rotation excluded windows")
    for v in expected:
        require(chosen["positive_by_copy"][v["copy_path"]] == v["original_positive"], "Fold lost positives")
    val_paths = [c[0]["source_path"] for c in d["val"]]
    require(set(val_paths) == set(split["cv"]["folds"][k]["validation_sources"]), "Changed validation sources")
    require(all("#" not in p for p in val_paths), "Augmented validation source")
    require(np.isfinite(d["x_train"]).all(), "Nonfinite training array")
    require(chosen["selected_count"] == len(d["y_train"]), "Selected-array length mismatch")
    counts = d["train_counts"]
    return d, {"class_counts": dict(zip(v2.CLASSES, counts)), "positive": sum(counts[1:]),
               "none": counts[0], "none_groups": d["train_none_groups"],
               "updates_per_epoch": (len(d["y_train"]) + v2.BATCH_SIZE - 1) // v2.BATCH_SIZE,
               "copies": d["train_aug_copies"], "reasons": d["train_aug_stats"],
               "excluded_windows": d["train_windows_excluded"]}


def forbidden_fit(*args, **kwargs):
    raise AssertionError("Training/model creation is forbidden in this preflight")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), f"Output directory already exists: {args.out}")
    started = time.perf_counter()
    _, by_path, nb = vr.load()
    files = [Path(__file__), ROOT / "ml/v2.py", ROOT / "ml/v2_return.py", ROOT / "ml/model.py",
             ROOT / "ml/test_v2_rotwarp.py", ROOT / "ml/test_v2_rotate.py", v2.RECORDS, vr.NEW_RECORDS,
             ROOT / "docs/superpowers/plans/2026-10-27-v2-augmentation.md",
             *vr.CANDIDATES.glob("*-candidates.json"),
             *(v2.SPLITS / f"v2-{s}.json" for s in vr.SPLITS),
             *(ROOT / p for p in by_path)]
    manifest = {p.relative_to(ROOT).as_posix(): v2.digest(p) for p in files}
    mapped = vr.relabel(by_path, nb, "newtcnrotwarp")
    measurements, reasons = inspect_copies(mapped)
    copy_index = {v["copy_path"]: v for v in measurements}
    folds = []
    with patch.object(v2, "fit_snapshots", side_effect=forbidden_fit), patch.object(vr, "tcn", side_effect=forbidden_fit):
        for name in vr.SPLITS:
            split = v2.load_split(name)
            require(split["records_sha256"] == manifest[v2.RECORDS.relative_to(ROOT).as_posix()], "Changed split records")
            for k in range(split["cv"]["n_folds"]):
                base, b = inspect_fold("newtcnrot", by_path, nb, split, k, copy_index)
                warp, w = inspect_fold("newtcnrotwarp", by_path, nb, split, k, copy_index)
                np.testing.assert_array_equal(base["mean"], warp["mean"])
                np.testing.assert_array_equal(base["std"], warp["std"])
                require(len(base["val"]) == len(warp["val"]), "Validation chunk count")
                for cb, cw in zip(base["val"], warp["val"]):
                    require(cb[0] == cw[0] and cb[3] == cw[3], "Validation record/meta mismatch")
                    np.testing.assert_array_equal(cb[1][:, :, :6], cw[1][:, :, :6])
                    np.testing.assert_array_equal(cb[2], cw[2])
                    require(np.isfinite(cw[1]).all(), "Nonfinite validation array")
                same = {key: b[key] == w[key] for key in ("class_counts", "none_groups", "updates_per_epoch", "copies")}
                folds.append({"split": name, "fold": k, "baseline": b, "rotation_speed": w,
                              "equal": same, "checks_passed": True})
                print(f"{name} fold {k}: positive {b['positive']} -> {w['positive']}; "
                      f"NONE {b['none']} -> {w['none']}; updates {b['updates_per_epoch']} -> {w['updates_per_epoch']}; "
                      f"excluded {w['excluded_windows']}; warp {w['reasons'].get('warp', 0)}", flush=True)
                del base, warp
                gc.collect()
    require(len(folds) == 9, "Not all nine folds were checked")
    require("tensorflow" not in sys.modules, "TensorFlow was unexpectedly imported")
    require(manifest == {p.relative_to(ROOT).as_posix(): v2.digest(p) for p in files}, "Inputs changed during audit")
    applied = [v for v in measurements if v["reason"] == "warp"]
    all_equal = all(all(f["equal"].values()) for f in folds)
    report = {"created_kst": v2.now(), "status": "passed", "training_executed": False,
              "tensorflow_imported": False, "environment": {"python": platform.python_version(),
              "numpy": np.__version__, "os": platform.platform(), "venv": sys.prefix},
              "baseline_condition": copy.deepcopy(vr.CONDITIONS["newtcnrot"]),
              "candidate_condition": copy.deepcopy(vr.CONDITIONS["newtcnrotwarp"]),
              "batch_size": v2.BATCH_SIZE, "original_clips": len(by_path), "copies": len(measurements),
              "copy_reasons": reasons, "applied_scale": distribution([v["scale_drawn"] for v in applied]),
              "applied_scale_below_one": sum(v["scale_drawn"] < 1 for v in applied),
              "applied_jump_dps": distribution([v["jump_dps"] for v in applied]),
              "rejected_jump_dps": distribution([v["jump_dps"] for v in measurements if v["reason"] == "jump"]),
              "transformed_start_ms": distribution([v["transformed_start_ms"] for v in applied]),
              "retained_positive_windows_in_speed_copies": sum(v["retained_positive"] for v in applied),
              "positive_windows_lost": 0, "all_fold_counts_and_updates_equal": all_equal,
              "folds": folds, "input_sha256": manifest,
              "known_limitations": ["The general guard against lost positive windows is still absent; this audit checks the current data and fixed augmentation draws.",
                  "The existing rotation-amount unit test does not implement the planned corresponding-motion-interval check.",
                  "Validation angle channels may change through training-only angle normalization; raw six-axis windows, labels and metadata were checked for equality.",
                  "This is a data-preparation check, not a performance comparison or device validation."],
              "seconds": round(time.perf_counter() - started, 3)}
    args.out.mkdir(parents=True, exist_ok=False)
    write_json(args.out / "copies.json", measurements)
    write_json(args.out / "report.json", report)
    lines = ["# 회전 + 속도 증강: 9개 fold 학습 전 확인", "", f"작성: {report['created_kst']}", "",
             "학습·모델 생성·TensorFlow 불러오기 없이 실제 데이터 준비 경로를 점검했다.", "",
             "| 분할 | fold | 양성(회전 → 회전+속도) | NONE | 업데이트/epoch | 제외 창 | 속도 사본 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for f in folds:
        b, w = f["baseline"], f["rotation_speed"]
        lines.append(f"| {f['split']} | {f['fold']} | {b['positive']} → {w['positive']} | {b['none']} → {w['none']} | "
                     f"{b['updates_per_epoch']} → {w['updates_per_epoch']} | {w['excluded_windows']} | {w['reasons']['warp']} |")
    lines += ["", f"전체 고유 원본 {len(by_path)}개, 사본 {len(measurements)}개. 처리 결과: `{json.dumps(reasons, ensure_ascii=False)}`.",
              "", "9개 fold는 같은 원본·사본의 반복 사용이므로 위 표를 독립 표본 수로 합산하지 않는다.",
              "", "사본별 90행·영점 보존, 회전만 남는 사본의 완전 동일성, 실제 시각 보간, 경계 점프, 유효 행 수, 양성 창 보존을 확인했다. "
              "각 fold의 실제 선택 경로에서 범위 밖 창 혼입이 없고 검증 원본·6축 입력·라벨·메타데이터와 원본 정규화 통계가 같음을 확인했다. "
              "회전각 채널은 각 조건의 학습 창 통계로 정규화하므로 검증에서도 달라질 수 있다.",
              "", "현재 코드의 일반적인 양성 창 소실 방지 조건과 대응 동작 구간 적분 테스트는 아직 보완되지 않았다. "
              "현재 데이터·고정 난수의 양성 창 소실은 0이며, 이 점검은 미래 데이터의 무결성을 보장하지 않는다.",
              "", "재현 명령(새 출력 폴더 필요):", "", "```powershell",
              "& ml/.venv/Scripts/python.exe tools/check-rotwarp-preflight.py --out <새 출력 폴더>", "```", "",
              "환경·조건·입력/코드 SHA-256·fold별 수치는 report.json, 사본별 측정값은 copies.json에 있다.",
              "독립 최종 성능 평가·실기기 검증·10회 학습은 수행하지 않았다.", ""]
    (args.out / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "copy_reasons", "applied_scale", "applied_jump_dps",
                     "all_fold_counts_and_updates_equal", "seconds")}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
