"""발행 진단 통합: 공통 기준·관측 끝·무발행·요구 미합의 보호."""
import unittest

import v2_event_timing as timing


def record(background=False):
    return {"source_path": "data/sessions/x/idle.1.csv" if background else "data/sessions/x/raw_up.1.csv",
            "completion_ms": None if background else 3800, "direction": "NONE" if background else "UP", "rows": 400, "session": "P1"}


class AggregateTests(unittest.TestCase):
    def test_common_zero_and_delayed_use_identical_candidate_domain(self):
        rec = record()
        times = list(range(1590, 3991, 50))
        base = [{"timestamp_ms": 3790, "class_index": 1, "score": .9}, {"timestamp_ms": 3840, "class_index": 1, "score": .9}]
        a = timing.evaluate_source(rec, times, base, 0, True)
        b = timing.evaluate_source(rec, times, base, 200, True)
        self.assertEqual((len(a["events"]), len(b["events"])), (1, 1))
        self.assertEqual((len(a["excluded"]), len(b["excluded"])), (1, 1))
        self.assertEqual(a["exposure_ms"], 2210)
        self.assertEqual(a["exposure_ms"], b["exposure_ms"])
        self.assertEqual(a["counts"]["early"], 1)
        self.assertEqual(b["counts"]["correct"], 1)

    def test_full_pending_is_reported_and_not_counted_as_observed_safe(self):
        rec = record(True)
        times = list(range(1590, 3991, 50))
        base = [{"timestamp_ms": 3940, "class_index": 1, "score": .9}]
        row = timing.evaluate_source(rec, times, base, 200, False)
        m = timing.aggregate_sources([row])
        self.assertEqual(m["pending"], 1)
        self.assertEqual(m["pending_only_sources"], 1)
        self.assertEqual(m["background_false"], 0)
        self.assertTrue(m["background_rate_has_censoring"])

    def test_no_raw_candidates_stay_missing_under_any_delay(self):
        rec = record()
        times = list(range(1590, 3991, 50))
        for delay in (0, 50, 100, 150, 200):
            row = timing.evaluate_source(rec, times, [], delay, True)
            m = timing.aggregate_sources([row])
            self.assertEqual(m["raw_no_candidate_rate"], 1)
            self.assertEqual(m["correct_rate"], 0)

    def test_unagreed_requirements_do_not_choose_a_policy(self):
        result = timing.requirements_status({"status": "unagreed", "R_min": None, "U_max": None, "B_max_per_min": None, "D_max_ms": None})
        self.assertFalse(result["can_adopt"])
        self.assertEqual(result["selected_delay_ms"], None)

    def test_all_planned_panels_present_without_duplicates(self):
        panels = timing.panel_specs()
        self.assertEqual(len(panels), 25)
        self.assertEqual(len({p["id"] for p in panels}), 25)
        self.assertEqual([p["id"] for p in panels[:2]], ["legacy-S-P5-E60", "legacy-C-E60"])
        self.assertIn("legacy-S-P3-E5", {p["id"] for p in panels})


if __name__ == "__main__":
    unittest.main()
