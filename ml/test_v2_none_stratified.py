"""NONE 배분만 바꾸는 선택기의 불변식과 실제 fold 호환성."""
import unittest
from collections import Counter
from pathlib import PurePosixPath

import numpy as np

import v2
import v2_none_stratified as balanced


def fixture(sessions=5, clips=10, windows=9, positives=100):
    y = [1] * positives
    meta = [{"none_group": "post_completion", "source_path": "data/sessions/P1/raw_up.0.csv", "timestamp_ms": i} for i in range(positives)]
    for kind in ("idle", "in_progress", "other", "post_completion"):
        for s in range(sessions):
            for c in range(clips):
                for w in range(windows):
                    y.append(0)
                    meta.append({"none_group": kind, "source_path": f"data/sessions/P{s + 1}/{kind}.{c}.csv", "timestamp_ms": w})
    return np.asarray(y), meta


class SamplerTests(unittest.TestCase):
    def test_total_positives_and_kind_quotas_match_legacy(self):
        y, meta = fixture(positives=103)
        old = v2.choose_training(y, meta)
        new = balanced.choose_training(y, meta)
        np.testing.assert_array_equal(new[y[new] != 0], old[y[old] != 0])
        self.assertEqual(len(new), len(old))
        self.assertEqual(len(set(new)), len(new))
        groups = lambda idx: Counter(meta[i]["none_group"] for i in idx if y[i] == 0)
        self.assertEqual(groups(new), groups(old))
        self.assertTrue(np.all(new[:-1] < new[1:]))

    def test_sessions_and_clips_are_balanced_when_capacity_allows(self):
        y, meta = fixture(positives=103)
        chosen = balanced.choose_training(y, meta)
        for kind in ("idle", "in_progress", "other", "post_completion"):
            per_session = Counter()
            per_clip = Counter()
            for i in chosen:
                m = meta[i]
                if y[i] == 0 and m["none_group"] == kind:
                    per_session[str(PurePosixPath(m["source_path"]).parent)] += 1
                    per_clip[m["source_path"]] += 1
            self.assertEqual(len(per_session), 5)
            self.assertLessEqual(max(per_session.values()) - min(per_session.values()), 1)
            for s in range(1, 6):
                counts = [per_clip[f"data/sessions/P{s}/{kind}.{c}.csv"] for c in range(10)]
                self.assertLessEqual(max(counts) - min(counts), 1)

    def test_seed_reproducibility_and_input_is_not_mutated(self):
        y, meta = fixture()
        original = [dict(m) for m in meta]
        a = balanced.choose_training(y, meta, 7)
        np.testing.assert_array_equal(a, balanced.choose_training(y, meta, 7))
        self.assertFalse(np.array_equal(a, balanced.choose_training(y, meta, 8)))
        self.assertEqual(meta, original)

    def test_common_clips_keep_legacy_window_priority(self):
        y, meta = fixture(positives=163)
        old, new = v2.choose_training(y, meta), balanced.choose_training(y, meta)
        def by_clip(indices):
            groups = {}
            for i in indices:
                if y[i] == 0:
                    groups.setdefault((meta[i]["none_group"], meta[i]["source_path"]), set()).add(int(i))
            return groups
        a, b = by_clip(old), by_clip(new)
        for key in a.keys() & b.keys():
            self.assertTrue(a[key] <= b[key] or b[key] <= a[key], key)

    def test_tiny_session_capacity_is_redistributed_without_duplicates(self):
        y, meta = fixture(sessions=2, clips=1, windows=1, positives=30)
        for i in range(50):
            y = np.append(y, 0)
            meta.append({"none_group": "in_progress", "source_path": "data/sessions/P2/in_progress.1.csv", "timestamp_ms": i + 10})
        old, new = v2.choose_training(y, meta), balanced.choose_training(y, meta)
        self.assertEqual(len(old), len(new))
        self.assertEqual(len(set(new)), len(new))
        counts = lambda idx: Counter(meta[i]["none_group"] for i in idx if y[i] == 0)
        self.assertEqual(counts(old), counts(new))

    def test_scarce_none_keeps_the_available_total(self):
        y, meta = fixture(sessions=1, clips=1, windows=1, positives=20)
        chosen = balanced.choose_training(y, meta)
        self.assertEqual((sum(y[chosen] != 0), sum(y[chosen] == 0)), (20, 4))

    def test_missing_session_path_is_rejected(self):
        y, meta = fixture()
        meta[-1]["source_path"] = "other.csv"
        with self.assertRaises(ValueError):
            balanced.choose_training(y, meta)


if __name__ == "__main__":
    unittest.main()
