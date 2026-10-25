"""BLE v2 데이터·창·채점 점검. 학습하지 않는다. 합성 데이터와 저장된 주석·분할만 읽는다."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

import baseline
import v2


def write_clip(path, rows, gap=10, header=None, start=0):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header or ["timestamp", *v2.AXES])
        for i in range(rows):
            w.writerow([start + i * gap] + [i * (a + 1) * .01 for a in range(6)])


class PositiveCountTests(unittest.TestCase):
    def test_matches_v1_where_both_cover_all_windows(self):
        for e in range(1000, 2860):
            self.assertEqual(v2.positive_count(e), baseline.positive_count(e), e)

    def test_warmup_does_not_invent_positives(self):
        self.assertEqual(v2.positive_count(1420), 0)
        self.assertEqual(v2.positive_count(1480), 1)
        self.assertEqual(v2.positive_count(1590), 3)

    def test_clip_end_truncates_positives(self):
        self.assertEqual(v2.positive_count(3890), 3)   # 3890, 3940, 3990
        self.assertEqual(v2.positive_count(3891), 2)
        self.assertEqual(v2.positive_count(3940), 2)
        self.assertEqual(v2.positive_count(3941), 1)
        self.assertEqual(v2.positive_count(3991), 0)

    def test_decision_grid(self):
        t = v2.decision_times(v2.GESTURE_ROWS)
        self.assertEqual((t[0], t[-1], len(t)), (1590, 3990, 49))
        t = v2.decision_times(v2.LONG_ROWS)
        self.assertEqual((t[0], t[-1], len(t)), (1590, 9990, 169))


class ReadSensorTests(unittest.TestCase):
    def test_strict_checks(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            write_clip(d / "raw_up.1.csv", 400)
            ts, values = v2.read_sensor(d / "raw_up.1.csv")
            self.assertEqual((len(ts), values.shape), (400, (400, 6)))
            write_clip(d / "raw_up.2.csv", 399)
            write_clip(d / "raw_up.3.csv", 400, gap=11)
            write_clip(d / "raw_up.4.csv", 400, start=10)
            write_clip(d / "raw_up.5.csv", 400, header=["t", *v2.AXES])
            write_clip(d / "idle.1.csv", 400)
            for name in ("raw_up.2.csv", "raw_up.3.csv", "raw_up.4.csv", "raw_up.5.csv", "idle.1.csv"):
                with self.assertRaises(ValueError, msg=name):
                    v2.read_sensor(d / name)
            write_clip(d / "other.1.csv", 1000)
            self.assertEqual(len(v2.read_sensor(d / "other.1.csv")[0]), 1000)


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_clip(self.root / "raw_up.1.csv", 400)
        write_clip(self.root / "idle.1.csv", 1000)

    def tearDown(self):
        self.tmp.cleanup()

    def test_direction_windows_and_labels(self):
        rec = {"source_path": "raw_up.1.csv", "kind": "raw_up", "direction": "UP", "completion_ms": 2000}
        x, y, meta = v2.windows(rec, np.zeros(6), np.ones(6), root=self.root)
        self.assertEqual(x.shape, (49, 160, 6))
        self.assertEqual((meta[0]["timestamp_ms"], meta[-1]["timestamp_ms"]), (1590, 3990))
        self.assertEqual([m["timestamp_ms"] for m, label in zip(meta, y) if label], [2040, 2090, 2140])
        self.assertTrue(set(y.tolist()) <= {0, 1})
        _, raw = v2.read_sensor(self.root / "raw_up.1.csv")
        for i in (0, 10, 48):   # 창의 마지막 행이 판정 시각의 실제 샘플이고 미래 값이 없다
            self.assertTrue(np.allclose(x[i][-1], raw[159 + i * 5]))
            self.assertTrue(np.allclose(x[i][0], raw[i * 5]))
        groups = {m["none_group"] for m, label in zip(meta, y) if label == 0}
        self.assertEqual(groups, {"in_progress", "post_completion"})

    def test_background_windows_are_all_none(self):
        rec = {"source_path": "idle.1.csv", "kind": "idle", "direction": "NONE", "completion_ms": None}
        x, y, meta = v2.windows(rec, np.zeros(6), np.ones(6), root=self.root)
        self.assertEqual((x.shape, int(y.sum()), meta[-1]["timestamp_ms"]), ((169, 160, 6), 0, 9990))
        self.assertEqual({m["none_group"] for m in meta}, {"idle"})

    def test_normalization_uses_only_given_training_files(self):
        write_clip(self.root / "raw_up.2.csv", 400)
        recs = [{"source_path": "raw_up.1.csv"}]
        mean, std = v2.normalization(recs, root=self.root)
        _, raw = v2.read_sensor(self.root / "raw_up.1.csv")
        self.assertTrue(np.allclose(mean, raw.mean(axis=0)) and np.allclose(std, raw.std(axis=0)))
        # 다른(검증) 파일 내용을 바꿔도 통계는 변하지 않는다
        write_clip(self.root / "raw_up.2.csv", 400, gap=10)
        self.assertTrue(np.allclose(v2.normalization(recs, root=self.root)[0], mean))


class EventTests(unittest.TestCase):
    def test_same_as_v1_on_random_scores(self):
        rng = np.random.default_rng(7)
        for trial in range(300):
            n = int(rng.integers(5, 60))
            scores = rng.dirichlet(np.full(5, rng.choice([.15, .4, 1.0])), size=n)
            times = list(range(1590, 1590 + 50 * n, 50))
            self.assertEqual(v2.issue_events(times, scores), baseline.issue_events(times, scores))
            e = int(rng.choice([None, 1900, 2400, 3000]) or 0) or None
            record = {"completion_ms": e, "direction": "NONE" if e is None else "LEFT"}
            events = v2.issue_events(times, scores)
            self.assertEqual(v2.classify_events(record, events), baseline.classify_events(record, events))

    def test_choose_training_same_as_v1(self):
        rng = np.random.default_rng(3)
        y = np.array([1, 2, 3, 4, 1, 2] + [0] * 60)
        meta = [{"none_group": ["idle", "other", "in_progress", "post_completion"][i % 4], "source_path": f"f{i % 5}"}
                for i in range(len(y))]
        a, b = v2.choose_training(y, meta), baseline.choose_training(y, meta)
        np.testing.assert_array_equal(a, b)
        self.assertEqual(np.bincount(y[a], minlength=5).tolist(), [6, 2, 2, 1, 1])

    def test_issue_does_not_use_completion_time(self):
        scores = np.array([[0, .9, .04, .03, .03]] * 4)
        times = [1590, 1640, 1690, 1740]
        self.assertEqual(v2.issue_events(times, scores), v2.issue_events(times, scores.copy()))
        # issue_events의 인자에 e가 없다는 것이 계약이다
        self.assertEqual(v2.issue_events.__code__.co_varnames[:2], ("times", "scores"))

    def test_classification_order_and_clipped_horizon(self):
        r = {"completion_ms": 2000, "direction": "UP"}
        events = [{"timestamp_ms": t, "class_index": c} for t, c in [(1999, 1), (2000, 2), (2100, 1), (2200, 1), (2501, 1)]]
        counts, delays, _ = v2.classify_events(r, events)
        self.assertEqual([counts[k] for k in ("early", "wrong_direction", "correct", "duplicate", "late_unmatched", "missed")], [1, 1, 1, 1, 1, 0])
        self.assertEqual(delays, [100])
        clipped = {"completion_ms": 3600, "direction": "DOWN"}   # e+500 = 4100 > 3990
        c, d, _ = v2.classify_events(clipped, [{"timestamp_ms": 3990, "class_index": 2}])
        self.assertEqual((c["correct"], d), (1, [390]))
        c, _, _ = v2.classify_events(clipped, [])
        self.assertEqual(c["missed"], 1)

    def test_selection_score_excludes_background(self):
        def src(name, **counts):
            return {"source_path": f"data/sessions/x/{name}", "counts": counts}
        per = [src("raw_up.1.csv", correct=1), src("raw_up.2.csv", missed=1, early=1, wrong_direction=1),
               src("raw_up.3.csv", correct=1, duplicate=1), src("idle.1.csv", background_false=7)]
        score, correct, unmatched, n = v2.selection_score(per)
        self.assertEqual((correct, unmatched, n), (2, 3, 3))
        self.assertAlmostEqual(score, (2 - 3) / 3)


class SavedDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not v2.RECORDS.exists():
            raise unittest.SkipTest("records.json이 아직 없다")
        cls.data, cls.by_path = v2.load_records()

    def test_records_match_files_and_counts(self):
        recs = self.data["records"]
        self.assertEqual(Counter(r["kind"] for r in recs), Counter({"raw_up": 71, "raw_down": 76, "raw_left": 74, "raw_right": 75, "idle": 15, "other": 25}))
        for r in recs:
            if r["direction"] != "NONE":
                self.assertEqual(r["positive_windows"], v2.positive_count(r["completion_ms"]))
                self.assertEqual(r["match_horizon_clipped"], r["completion_ms"] + 500 > 3990)
        for x in self.data["excluded_by_user"]:
            self.assertNotIn(x["source_path"], self.by_path)
            self.assertEqual(len(x["reason"]) > 0, True)

    def test_splits_verify(self):
        v2.verify()

    def test_c_split_is_reproducible(self):
        name, rebuilt = v2.split_c(self.data)
        self.assertEqual(json.loads(json.dumps(rebuilt)), v2.load_split(name))   # JSON 왕복으로 튜플·리스트 차이 제거

    def test_fold_has_no_leakage(self):
        sp = v2.load_split("S-P5")
        recs = self.by_path
        ev = set(sp["eval_sources"])
        for k, fold in enumerate(sp["cv"]["folds"]):
            val = set(fold["validation_sources"])
            train = [recs[p] for p in sp["train_sources"] if p not in val]
            self.assertFalse(ev & {r["source_path"] for r in train})
            self.assertFalse(val & {r["source_path"] for r in train})
            self.assertEqual({r["session"] for r in train} & {fold["held_out_session"]}, set())
        d = v2.fold_sets(recs, sp, 0)
        train_recs = [recs[p] for p in sp["train_sources"] if p not in set(sp["cv"]["folds"][0]["validation_sources"])]
        mean, std = v2.normalization(train_recs)
        np.testing.assert_allclose(d["mean"], mean)
        np.testing.assert_allclose(d["std"], std)
        # 검증 창은 전부 있고(NONE을 줄이지 않음) 시작은 1590 ms
        n_expected = sum(len(v2.decision_times(r["rows"])) for r in recs.values() if r["source_path"] in set(sp["cv"]["folds"][0]["validation_sources"]))
        self.assertEqual(sum(len(c[2]) for c in d["val"]), n_expected)
        self.assertTrue(all(c[3][0]["timestamp_ms"] == 1590 for c in d["val"]))


from collections import Counter  # noqa: E402

if __name__ == "__main__":
    unittest.main()
