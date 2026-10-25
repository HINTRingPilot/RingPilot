"""BLE v2 진단 도구 점검. 저장된 발행 로그만 읽으며 학습하지 않는다."""
import tempfile
import unittest
from pathlib import Path

import v2
import v2_cal
import v2_diag


def src(name, e, direction, events, counts):
    return {"source_path": f"data/sessions/x/{name}", "completion_ms": e, "direction": direction, "rows": 400 if e else 1000,
            "events": events, "counts": counts, "delays_ms": []}


def ev(t, cls, kind):
    return {"timestamp_ms": t, "class_index": cls, "kind": kind, "score": .9}


class TimingDirection(unittest.TestCase):
    def test_emission_rate_is_not_inflated_by_duplicate_emissions(self):
        # 한 클립에 발행 3회(조기 1, 정검출 1, 중복 1)여도 발행한 클립은 1개
        p = src("raw_up.1.csv", 2000, "UP", [ev(1900, 1, "early"), ev(2100, 1, "correct"), ev(2200, 1, "duplicate")],
                {"early": 1, "correct": 1, "duplicate": 1})
        q = src("raw_up.2.csv", 2000, "UP", [], {"missed": 1})
        m = v2_diag.seed_epoch_metrics([p, q])
        self.assertEqual((m["n_dir"], m["clips_emitted_any"], m["events_total"]), (2, 1, 3))
        self.assertEqual(v2_diag.rate(m["clips_emitted_any"], m["n_dir"]), .5)
        self.assertEqual((m["clips_correct"], m["clips_emitted_early"], m["clips_emitted_without_correct"]), (1, 1, 0))

    def test_early_wrong_direction_is_caught_although_scoring_counts_it_as_early(self):
        # 조기 발행인데 방향이 다르다(DOWN=2, 정답 UP=1). 기존 채점은 early로만 센다
        p = src("raw_up.1.csv", 2000, "UP", [ev(1900, 2, "early")], {"early": 1, "missed": 1})
        m = v2_diag.seed_epoch_metrics([p])
        self.assertEqual((m["early_mismatch"], m["early_match"], m["wrong_direction"]), (1, 0, 0))
        self.assertEqual(m["kinds_inconsistent"], 0)

    def test_window_late_and_background_buckets(self):
        events = [ev(2000, 2, "wrong_direction"), ev(2500, 1, "correct"), ev(2501, 1, "late_unmatched"), ev(2600, 2, "late_unmatched")]
        p = src("raw_up.1.csv", 2000, "UP", events, {"wrong_direction": 1, "correct": 1, "late_unmatched": 2})
        bg = src("idle.1.csv", None, "NONE", [ev(3000, 1, "background_false")], {"background_false": 1})
        m = v2_diag.seed_epoch_metrics([p, bg])
        self.assertEqual((m["window_mismatch"], m["window_match"], m["late_match"], m["late_mismatch"]), (1, 1, 1, 1))
        self.assertEqual((m["bg_false"], m["bg_clips_with_false"], m["bg_exposure_ms"]), (1, 1, 10000 - 1590))
        self.assertEqual(m["kinds_inconsistent"], 0)

    def test_inconsistent_recorded_kind_is_flagged(self):
        p = src("raw_up.1.csv", 2000, "UP", [ev(1900, 1, "correct")], {"correct": 1})     # 조기인데 correct로 기록
        self.assertEqual(v2_diag.seed_epoch_metrics([p])["kinds_inconsistent"], 1)

    def test_no_emission_scores_zero(self):
        p = [src(f"raw_up.{i}.csv", 2000, "UP", [], {"missed": 1}) for i in range(3)]
        m = v2_diag.seed_epoch_metrics(p)
        self.assertEqual((m["score"], m["unmatched"], m["clips_emitted_any"]), (0.0, 0, 0))

    def test_paired_difference_counts_up_down_equal(self):
        per = {"1": {1: {"score": .1}, 2: {"score": .2}, 3: {"score": .3}},
               "5": {1: {"score": .0}, 2: {"score": .3}, 3: {"score": .3}}}
        d = v2_diag.paired(per, "1", "5")
        self.assertEqual((d["n_up"], d["n_down"], d["n_equal"]), (1, 1, 1))
        self.assertAlmostEqual(d["mean_diff"], (.1 - .1 + 0) / 3)


class EarlyPosition(unittest.TestCase):
    def test_early_events_are_split_by_motion_end(self):
        ann = {"data/sessions/x/raw_up.1.csv": {"completion_ms": 2000, "main_motion_end_ms": 1800}}
        events = [ev(1700, 1, "early"), ev(1850, 1, "early"), ev(1950, 2, "early"), ev(2100, 1, "correct")]
        p = src("raw_up.1.csv", 2000, "UP", events, {"early": 3, "correct": 1})
        result = {"folds": [{"per_epoch": {"5": {"per_source": [p]}}}]}
        r = v2_diag.early_position([result], 5, ann)
        self.assertEqual((r["early_total_5seeds"], r["during_motion"], r["after_motion_end_before_e"]), (3, 1, 2))
        self.assertEqual(r["lead_before_e_ms_median_after"], 100.0)      # 2000-1850=150, 2000-1950=50
        self.assertAlmostEqual(r["share_after_motion_end"], 2 / 3)

    def test_completion_gap_report(self):
        ann = {str(i): {"completion_ms": 2000, "main_motion_end_ms": 2000 - g} for i, g in enumerate((10, 100, 200, 400, 800))}
        g = v2_diag.completion_gap_report(ann)
        self.assertEqual((g["n"], g["min"], g["max"], g["median"], g["n_gap_over_300ms"]), (5, 10, 800, 200.0, 2))

    def test_real_annotations_cover_every_direction_clip(self):
        if not v2.RECORDS.exists():
            self.skipTest("주석이 아직 없다")
        ann = v2_diag.load_annotations()
        data, by_path = v2.load_records()
        direction = {p for p, r in by_path.items() if r["direction"] != "NONE"}
        self.assertEqual(set(ann), direction)
        self.assertTrue(all(ann[p]["completion_ms"] == by_path[p]["completion_ms"] for p in direction))


class SavedResults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (v2_cal.results_dir("V2-S-P5-cal") / "summary.json").exists():
            raise unittest.SkipTest("과거 결과가 없다")

    def test_reaggregation_equals_saved_summary_for_all_splits(self):
        for s in v2_diag.SPLITS:
            _, per, saved, check = v2_diag.analyse_run(s)
            self.assertTrue(check["chosen_E_equal"], s)
            self.assertEqual(check["max_abs_mean_score_diff_vs_saved"], 0.0, s)
            self.assertEqual(check["kinds_inconsistent_total"], 0, s)

    def test_decomposition_matches_recorded_counts(self):
        for s in v2_diag.SPLITS:
            _, per, saved, _ = v2_diag.analyse_run(s)
            for e, by_seed in per.items():
                for seed, m in by_seed.items():
                    key = (s, e, seed)
                    self.assertEqual(m.get("early_match", 0) + m.get("early_mismatch", 0), m["early"], key)
                    self.assertEqual(m.get("window_mismatch", 0), m["wrong_direction"], key)
                    self.assertEqual(m.get("window_match", 0), m["correct"] + m["duplicate"], key)
                    self.assertEqual(m.get("late_match", 0) + m.get("late_mismatch", 0), m["late_unmatched"], key)
                    self.assertEqual(m["unmatched"], m["early"] + m["wrong_direction"] + m["duplicate"] + m["late_unmatched"], key)
                    self.assertLessEqual(m["clips_emitted_any"], m["n_dir"], key)
                    self.assertLessEqual(m["clips_emitted_any"], m["events_total"], key)

    def test_reuse_report(self):
        r = v2_diag.reuse_report()
        self.assertEqual(r["total_sources"], 336)
        self.assertTrue(all(x["overlap_with_own_calibration_validation"] == 0 for x in r["per_split"].values()))
        self.assertTrue(all(x["overlap_with_other_splits_calibration_validation"] == x["eval_sources"] for x in r["per_split"].values()))
        self.assertEqual(r["never_used_as_validation"], 0)

    def test_refuses_to_overwrite_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "calibration-diagnostics.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                v2_diag.main(tmp)


if __name__ == "__main__":
    unittest.main()
