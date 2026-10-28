"""약한 동작 목록 점검. 학습하지 않는다."""
import json
import unittest

import numpy as np

import v2
import v2_return as vr


class WeakGestureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(vr.WEAK_GESTURES.read_text(encoding="utf-8"))
        cls.nb = {r["source_path"]: r for r in json.loads(vr.NEW_RECORDS.read_text(encoding="utf-8"))["records"]}

    def test_rule_reproduces_list(self):
        # 방향별 중앙값의 0.6배 미만을 다시 계산하면 같은 14개가 나온다
        med = {d: float(np.median([r["return_peak_dps"] for r in self.nb.values() if r["direction"] == d]))
               for d in ("UP", "DOWN", "LEFT", "RIGHT")}
        weak = {p for p, r in self.nb.items() if r["return_peak_dps"] / med[r["direction"]] < self.data["threshold"]}
        self.assertEqual(weak, {e["source_path"] for e in self.data["entries"]})
        self.assertEqual(len(weak), 14)
        self.assertEqual(vr.load_weak(), frozenset(weak))

    def test_weak_clips_stay_in_records(self):
        _, by_path = v2.load_records()
        self.assertTrue(vr.load_weak() <= set(by_path))

    def test_epoch_stats_skip_and_only(self):
        hit = {"correct": 1}
        per_source = [{"source_path": "s/raw_up.1.csv", "counts": hit, "delays_ms": [100], "events": [(2000, 1, "correct")]},
                      {"source_path": "s/raw_up.2.csv", "counts": {}, "delays_ms": [], "events": []},
                      {"source_path": "s/idle.1.csv", "counts": {"background_false": 1}, "delays_ms": [], "events": [(2000, 1, "x")]}]
        res = [{"folds": [{"per_epoch": {"20": {"new_window": {"per_source": per_source}}}}]}]
        self.assertEqual(vr.epoch_stats(res, 20, "new_window")["clean_success_rate"], 0.5)
        skipped = vr.epoch_stats(res, 20, "new_window", frozenset({"s/raw_up.2.csv"}))
        self.assertEqual(skipped["clean_success_rate"], 1.0)
        self.assertEqual(skipped["background_false_per_clip"], 1.0)   # 배경 클립은 그대로 센다
        only = vr.epoch_stats(res, 20, "new_window", only=frozenset({"s/raw_up.2.csv"}))
        self.assertEqual((only["clean_success_rate"], only["no_issue_rate"]), (0.0, 1.0))


if __name__ == "__main__":
    unittest.main()
