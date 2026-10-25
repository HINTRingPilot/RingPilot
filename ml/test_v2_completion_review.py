"""BLE v2 완료 시각 검토 도구 점검. 저장된 파일만 읽으며 학습하지 않는다.

논리 검사는 합성 자료로, 통합 검사는 실제 저장 예측·발행 로그로 한다(임시 폴더에만 쓴다).
"""
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

import v2
import v2_completion_review as cr


def synthetic_records(per_group=4, clipped=None):
    """세션 5 × 방향 4 × per_group개의 합성 방향 원본과 주석."""
    records, ann = [], {}
    for si, s in enumerate(v2.SESSION_KEYS):
        for d in v2.DIRECTIONS:
            for k in range(1, per_group + 1):
                path = f"data/sessions/phone-{si}/raw_{d.lower()}.{k}.csv"
                end = 2000 + 10 * k
                e = end + 100 + 10 * ((si * 7 + k * 3) % 9)
                records.append({"source_path": path, "session": s, "direction": d, "sha256": f"h-{path}",
                                "completion_ms": e, "match_horizon_clipped": path == clipped})
                ann[path] = {"completion_ms": e, "main_motion_start_ms": 1500, "main_motion_end_ms": end,
                             "flags": "", "status": "AUTO"}
    records.append({"source_path": "data/sessions/phone-0/idle.1.csv", "session": "P1", "direction": "NONE",
                    "sha256": "h", "completion_ms": None})
    return records, ann


def saved_manifest():
    path = cr.OUT_DIR / cr.MANIFEST_NAME
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


class Selection(unittest.TestCase):
    def test_same_seed_reproduces_identical_samples_and_tags(self):
        clipped = "data/sessions/phone-3/raw_left.2.csv"
        recs, ann = synthetic_records(clipped=clipped)
        a = cr.select_samples(recs, ann, horizon_paths=(clipped,))
        b = cr.select_samples(list(reversed(recs)), ann, horizon_paths=(clipped,))       # 입력 순서와 무관
        self.assertEqual(a, b)
        samples, groups, _ = a
        self.assertEqual([g["session"] + g["direction"] for g in groups],
                         [s + d for s in v2.SESSION_KEYS for d in v2.DIRECTIONS])
        self.assertEqual(len([s for s in samples if "base" in s["tags"]]), 20)
        self.assertEqual(len({s["source_path"] for s in samples}), len(samples))
        self.assertTrue(20 <= len(samples) <= 26)
        other = cr.select_samples(recs, ann, seed=1, horizon_paths=(clipped,))
        self.assertNotEqual([s["source_path"] for s in samples[:20]], [s["source_path"] for s in other[0][:20]])

    def test_rng_is_consumed_sequentially_in_group_order(self):
        recs, ann = synthetic_records(per_group=6)
        rng = np.random.default_rng(cr.SAMPLE_SEED)
        expected = []
        for s in v2.SESSION_KEYS:
            for d in v2.DIRECTIONS:
                g = sorted((r for r in recs if r["session"] == s and r["direction"] == d), key=lambda r: r["source_path"])
                expected.append(g[int(rng.integers(len(g)))]["source_path"])
        recs[0]["match_horizon_clipped"] = True
        samples, _, _ = cr.select_samples(recs, ann, horizon_paths=(recs[0]["source_path"],))
        self.assertEqual([s["source_path"] for s in samples if "base" in s["tags"]], expected)

    def test_large_gap_ties_break_by_source_path_and_duplicates_merge_tags(self):
        recs, ann = synthetic_records()
        by = {r["source_path"]: r for r in recs}
        for p, a in ann.items():
            a["main_motion_end_ms"] = by[p]["completion_ms"]                    # 간격 0
        tied = sorted(ann)[3:9]                                                # 동점 6개(간격 900)
        for p in tied:
            ann[p]["main_motion_end_ms"] = by[p]["completion_ms"] - 900
        by[tied[0]]["match_horizon_clipped"] = True
        samples, _, ranking = cr.select_samples(recs, ann, horizon_paths=(tied[0],))
        self.assertEqual([x["source_path"] for x in ranking], tied[:5])
        self.assertTrue(all(x["gap_ms"] == 900 for x in ranking))
        merged = next(s for s in samples if s["source_path"] == tied[0])
        self.assertIn("large_gap", merged["tags"])
        self.assertIn("clipped_horizon", merged["tags"])
        self.assertEqual(len(merged["reasons"]), len(merged["tags"]))
        self.assertEqual(len({s["source_path"] for s in samples}), len(samples))

    def test_missing_or_unclipped_horizon_sample_is_rejected(self):
        recs, ann = synthetic_records()
        with self.assertRaises(cr.Mismatch):
            cr.select_samples(recs, ann, horizon_paths=("data/sessions/phone-0/raw_up.1.csv",))
        with self.assertRaises(cr.Mismatch):
            cr.select_samples(recs, ann, horizon_paths=("nope.csv",))

    def test_real_selection_matches_saved_manifest(self):
        data = json.loads(v2.RECORDS.read_text(encoding="utf-8"))
        ann, _ = cr.load_annotations()
        samples, groups, _ = cr.select_samples(data["records"], ann)
        self.assertEqual(len(samples), 26)
        tags = [t for s in samples for t in s["tags"]]
        self.assertEqual((tags.count("base"), tags.count("large_gap"), tags.count("clipped_horizon")), (20, 5, 1))
        self.assertEqual(sum(1 for r in data["records"] if r["direction"] != "NONE"), 296)
        self.assertIn(cr.HORIZON_CLIPPED, [s["source_path"] for s in samples])
        manifest = saved_manifest()
        if manifest is not None:
            self.assertEqual(manifest["samples"], samples)


class TimeAlignment(unittest.TestCase):
    def test_last_row_of_window_is_decision_time_and_no_scores_before_1590(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "data"
            d.mkdir()
            rows = ["timestamp,accX,accY,accZ,gyrX,gyrY,gyrZ"] + \
                   [f"{10 * i},{i},{2 * i},{3 * i},{4 * i},{5 * i},{6 * i}" for i in range(400)]
            (d / "raw_up.1.csv").write_bytes(("\n".join(rows) + "\n").encode())
            rec = {"source_path": "data/raw_up.1.csv", "completion_ms": 2000, "direction": "UP"}
            x, y, meta = v2.windows(rec, np.zeros(6), np.ones(6), root=td)
        t = np.array([m["timestamp_ms"] for m in meta])
        self.assertTrue(np.array_equal(t, v2.decision_times(400)))
        self.assertEqual((int(t[0]), int(t[-1]), len(t)), (1590, 3990, 49))
        self.assertTrue((t >= v2.FIRST_T).all())
        # 창의 마지막 행(accX = 행 번호)이 판정 시각 / 10이고 첫 행은 159행 앞
        self.assertTrue(np.array_equal(x[:, -1, 0], t / 10))
        self.assertTrue(np.array_equal(x[:, 0, 0], t / 10 - 159))

    def test_clip_windows_rejects_early_or_shifted_times(self):
        good = [{"source_path": "a", "timestamp_ms": int(t), "target": 0} for t in v2.decision_times(400)]
        scores = np.full((len(good), 5), .2)
        times, sc, _ = cr.clip_windows("a", good, scores)
        self.assertEqual((int(times[0]), len(sc)), (1590, 49))
        early = [{"source_path": "a", "timestamp_ms": 1580 + 50 * i, "target": 0} for i in range(50)]   # 앞쪽 가짜 창
        with self.assertRaises(cr.Mismatch):
            cr.clip_windows("a", early, np.full((50, 5), .2))
        shifted = [{**w, "timestamp_ms": w["timestamp_ms"] + 10} for w in good]
        with self.assertRaises(cr.Mismatch):
            cr.clip_windows("a", shifted, scores)
        with self.assertRaises(cr.Mismatch):
            cr.clip_windows("missing", good, scores)

    def test_stored_windows_of_real_samples_start_at_1590(self):
        manifest = saved_manifest()
        if manifest is None:
            self.skipTest("manifest 없음")
        _, by_path = v2.load_records()
        store = cr.RunStore()
        for s in manifest["samples"][:3] + manifest["samples"][-1:]:
            split_name = cr.split_name_for(s["session"])
            fold = cr.find_fold(store.split(split_name), s["session"])
            for seed in cr.SEEDS:
                windows, e60 = store.arrays_for(split_name, seed, fold)
                times, scores, meta = cr.clip_windows(s["source_path"], windows, e60)
                self.assertEqual((int(times[0]), int(times[-1])), (1590, 3990))
            self.assertTrue(cr.check_window_alignment(by_path[s["source_path"]], meta))


def probs(top, p=.95, n=5):
    v = np.full(n, (1 - p) / (n - 1))
    v[top] = p
    return v


class Rederivation(unittest.TestCase):
    def setUp(self):
        self.times = v2.decision_times(400)
        self.record = {"source_path": "x/raw_up.1.csv", "completion_ms": 2000, "direction": "UP"}
        s = np.tile(probs(0), (len(self.times), 1))
        at = list(self.times)
        for t in (1890, 1940):                # 조기: 연속 2회 UP
            s[at.index(t)] = probs(1)
        for t in (2290, 2340):                # 구간 안: 연속 2회 DOWN(방향 불일치). 사이의 NONE이 재무장
            s[at.index(t)] = probs(2)
        self.scores = s.astype(np.float32)

    def stored(self):
        return v2.classify_events(self.record, v2.issue_events(self.times, self.scores))[2]

    def test_rederived_events_equal_stored_log(self):
        stored = self.stored()
        self.assertEqual([e["kind"] for e in stored], ["early", "wrong_direction"])
        events, diff, exact = cr.rederive_and_check(self.record, self.times, self.scores, stored)
        self.assertEqual([(e["timestamp_ms"], e["timing"], e["direction_match"]) for e in events],
                         [(1940, "early", True), (2340, "window", False)])
        self.assertEqual((diff, exact), (0.0, True))

    def test_any_difference_fails_loudly(self):
        stored = self.stored()
        for field, value in (("timestamp_ms", 1960), ("class_index", 3), ("kind", "correct")):
            bad = [dict(e) for e in stored]
            bad[0][field] = value
            with self.assertRaises(cr.Mismatch, msg=field):
                cr.rederive_and_check(self.record, self.times, self.scores, bad)
        with self.assertRaises(cr.Mismatch):
            cr.rederive_and_check(self.record, self.times, self.scores, stored[:1])
        with self.assertRaises(cr.Mismatch):
            cr.rederive_and_check(self.record, self.times, self.scores, stored + [stored[0]])
        bad = [dict(e) for e in stored]
        bad[1]["score"] += 1e-3
        with self.assertRaises(cr.Mismatch):
            cr.rederive_and_check(self.record, self.times, self.scores, bad)

    def test_timing_boundaries_match_classify_events(self):
        self.assertEqual([cr.timing_class(t, 2000) for t in (1999, 2000, 2500, 2501)], ["early", "window", "window", "late"])

    def test_real_stored_logs_are_reproduced_for_all_samples_and_seeds(self):
        manifest = saved_manifest()
        if manifest is None:
            self.skipTest("manifest 없음")
        _, by_path = v2.load_records()
        store = cr.RunStore()
        n = 0
        for s in manifest["samples"]:
            a = cr.analyse_sample(s, store, by_path)       # 다르면 Mismatch
            self.assertTrue(all(c["equal"] for c in a["rederivation"]))
            self.assertEqual(len(a["rederivation"]), len(cr.SEEDS))
            n += len(a["rederivation"])
        self.assertEqual(n, len(manifest["samples"]) * len(cr.SEEDS))


class TrainingExclusion(unittest.TestCase):
    def split(self):
        return {"name": "S-PX", "eval_sources": ["e1"], "train_sources": ["a1", "a2", "b1", "b2"],
                "cv": {"folds": [{"fold": 0, "held_out_session": "PA", "validation_sources": ["a1", "a2"]},
                                 {"fold": 1, "held_out_session": "PB", "validation_sources": ["b1", "b2"]}]}}

    def test_validation_clip_is_not_in_training(self):
        c = cr.assert_not_trained("a1", self.split(), 0)
        self.assertTrue(c["ok"] and c["in_fold_validation"] and not c["in_fold_training"])
        self.assertEqual(c["n_training_sources"], 2)

    def test_check_fails_on_clip_that_is_in_training_or_eval(self):
        sp = self.split()
        self.assertFalse(cr.training_exclusion("b1", sp, 0)["ok"])             # 다른 fold의 검증 = 이 fold의 학습
        with self.assertRaises(cr.Mismatch):
            cr.assert_not_trained("b1", sp, 0)
        with self.assertRaises(cr.Mismatch):
            cr.assert_not_trained("e1", sp, 0)                                  # 평가용
        sp["cv"]["folds"][0]["validation_sources"] = ["a2"]                     # 검증에 없는 원본
        with self.assertRaises(cr.Mismatch):
            cr.assert_not_trained("a1", sp, 0)

    def test_find_fold_requires_exactly_one(self):
        sp = self.split()
        self.assertEqual(cr.find_fold(sp, "PB"), 1)
        with self.assertRaises(cr.Mismatch):
            cr.find_fold(sp, "PZ")

    def test_real_splits_exclude_samples_and_fail_for_a_trained_clip(self):
        store = cr.RunStore()
        s5, s1 = store.split("S-P5"), store.split("S-P1")
        p1 = "data/sessions/phone-20261025-150714/raw_up.1.csv"
        p5 = "data/sessions/phone-20261025-161530/raw_up.1.csv"
        self.assertTrue(cr.training_exclusion(p1, s5, cr.find_fold(s5, "P1"))["ok"])
        self.assertTrue(cr.training_exclusion(p5, s1, cr.find_fold(s1, "P5"))["ok"])
        # P1 원본은 P2 검증 fold에서는 학습에 들어간다 → 검사가 실패해야 한다
        self.assertFalse(cr.training_exclusion(p1, s5, cr.find_fold(s5, "P2"))["ok"])
        # P5 원본은 S-P5 분할의 평가 원본이다
        self.assertFalse(cr.training_exclusion(p5, s5, 0)["ok"])


def fake_event(t, kind, timing, match):
    return {"timestamp_ms": t, "class_index": 1, "kind": kind, "timing": timing, "direction_match": match,
            "score": .9, "t_minus_e_ms": 0}


class ClipLevel(unittest.TestCase):
    def test_multiple_emissions_in_one_clip_count_once(self):
        seeds = list(cr.SEEDS)
        a = {"seeds": {s: {"events": []} for s in seeds}}
        a["seeds"][seeds[0]]["events"] = [fake_event(1900, "early", "early", True), fake_event(2100, "correct", "window", True),
                                          fake_event(2200, "duplicate", "window", True)]
        a["seeds"][seeds[1]]["events"] = [fake_event(2100, "wrong_direction", "window", False)]
        b = {"seeds": {s: {"events": []} for s in seeds}}
        c = cr.clip_level_counts([a, b])
        p = c["clip_seed_pairs_with"]
        self.assertEqual((c["n_samples"], c["n_clip_seed_pairs"]), (2, 10))
        self.assertEqual(c["events_total_not_clip_level"], 4)
        self.assertEqual((p["any"], p["multiple"], p["early"], p["correct"], p["duplicate"], p["wrong_direction"]), (2, 1, 1, 1, 1, 1))
        self.assertEqual((p["window_match"], p["window_mismatch"], p["early_match"]), (1, 1, 1))
        self.assertEqual(c["samples_with_any_emission_in_any_seed"], 1)
        self.assertEqual(c["samples_by_n_seeds_emitted"], {"0": 1, "1": 0, "2": 1, "3": 0, "4": 0, "5": 0})
        self.assertEqual(c["per_seed_clips_with"][str(seeds[0])]["any"], 1)
        self.assertEqual(c["per_seed_clips_with"][str(seeds[0])]["multiple"], 1)


class Outputs(unittest.TestCase):
    def test_ensure_new_refuses_existing(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "a.json"
            cr.ensure_new([f])
            f.write_text("x")
            with self.assertRaises(FileExistsError):
                cr.ensure_new([Path(td) / "b.json", f])

    def test_sample_and_report_refuse_overwrite_and_write_expected_files(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "samples"
            m = cr.cmd_sample(out)
            self.assertEqual(m["counts"]["samples"], 26)
            self.assertIn("추정치", m["notice"])
            with self.assertRaises(FileExistsError):
                cr.cmd_sample(out)
            before = (out / cr.MANIFEST_NAME).read_bytes()
            summary = cr.cmd_report(out)
            with self.assertRaises(FileExistsError):
                cr.cmd_report(out)
            self.assertEqual((out / cr.MANIFEST_NAME).read_bytes(), before)
            names = {p.name for p in out.iterdir()}
            self.assertEqual(len([n for n in names if n.endswith(".svg")]), 26)
            self.assertTrue({"report.html", "summary.json", "summary.md", cr.MANIFEST_NAME} <= names)
            for p in out.iterdir():
                self.assertNotIn(b"\r", p.read_bytes(), p.name)
            ig = summary["integrity"]
            self.assertEqual(ig["emission_rederivation"]["n_checks"], 26 * 5)
            self.assertEqual(ig["emission_rederivation"]["n_pass"], 26 * 5)
            self.assertEqual(ig["training_exclusion"]["n_pass"], 26 * 5)
            saved = json.loads((out / "summary.json").read_text(encoding="utf-8"))
            self.assertIn("no plotting library", saved["environment"]["plotting"])
            self.assertTrue(saved["environment"]["python"])
            c = saved["clip_level_counts"]       # 클립 단위 수는 발행 이벤트 수를 넘지 않는다
            self.assertLessEqual(c["clip_seed_pairs_with"]["any"], c["events_total_not_clip_level"])
            self.assertEqual(c["events_total_not_clip_level"], len(saved["emissions"]))

    def test_report_without_manifest_fails(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                cr.cmd_report(Path(td))

    def test_svg_is_well_formed_and_draws_no_scores_before_1590(self):
        manifest = saved_manifest()
        if manifest is None:
            self.skipTest("manifest 없음")
        _, by_path = v2.load_records()
        s = manifest["samples"][-1]
        a = cr.analyse_sample(s, cr.RunStore(), by_path)
        ts, raw = v2.read_sensor(v2.ROOT / s["source_path"])
        root = ET.fromstring(cr.render_svg(s, ts, raw, a["seeds"]))
        score_lines = [p for p in root.iter("{http://www.w3.org/2000/svg}polyline") if p.get("stroke") == "#2f4b7c"]
        self.assertEqual(len(score_lines), len(cr.SEEDS))
        for p in score_lines:
            xs_ = [float(pt.split(",")[0]) for pt in p.get("points").split()]
            self.assertGreaterEqual(min(xs_) + 0.06, cr.xs(v2.FIRST_T))   # 좌표는 소수 첫째 자리로 반올림
            self.assertEqual(len(xs_), 49)


if __name__ == "__main__":
    unittest.main()
