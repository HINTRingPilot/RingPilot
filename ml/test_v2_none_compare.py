import unittest

import v2_none_compare as compare


class ComparisonTests(unittest.TestCase):
    def test_improvement_requires_no_correct_rate_or_error_tradeoff(self):
        self.assertEqual(compare.classify_change({"score": .1, "correct_rate": .1, "early_clip_rate": -.1, "unmatched_per_source": -.1}), "개발용 개선 관찰")
        self.assertEqual(compare.classify_change({"score": .1, "correct_rate": -.1, "early_clip_rate": -.1, "unmatched_per_source": -.2}), "지표 간 교환관계")
        self.assertEqual(compare.classify_change({"score": -.1, "correct_rate": -.1, "early_clip_rate": .1, "unmatched_per_source": .1}), "개발용 악화 관찰")
        self.assertEqual(compare.classify_change({"score": 0, "correct_rate": 0, "early_clip_rate": 0, "unmatched_per_source": 0}), "관측값 동일")

    def test_paired_differences_keep_seed_identity(self):
        old = {1: {"score": .2}, 2: {"score": .4}}
        new = {2: {"score": .3}, 1: {"score": .4}}
        p = compare.paired_metrics(old, new)
        self.assertAlmostEqual(p["score"]["mean"], .05)
        self.assertEqual((p["score"]["up"], p["score"]["down"], p["score"]["equal"]), (1, 1, 0))
        with self.assertRaises(ValueError):
            compare.paired_metrics(old, {1: {"score": .5}})


if __name__ == "__main__":
    unittest.main()
