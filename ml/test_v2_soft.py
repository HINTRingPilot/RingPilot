"""부드러운 라벨(newtcnrotwarpsoft) 점검. 학습하지 않는다."""
import unittest

import numpy as np

import v2
import v2_return as vr

SOFT = vr.CONDITIONS["newtcnrotwarpsoft"]["soft"]


class SoftWeightTests(unittest.TestCase):
    def test_profile(self):
        e, rp = 2000, 1800
        w = lambda t: vr.soft_weight(t, e, rp, SOFT)
        self.assertEqual([w(t) for t in (2000, 2050, 2100)], [1.0, 1.0, 1.0])            # r ~ r+150: 지금과 같은 1
        self.assertEqual([round(w(t), 3) for t in (2150, 2200, 2250, 2300)], [0.75, 0.5, 0.25, 0.0])
        self.assertEqual([round(w(t), 3) for t in (1800, 1900, 1950)], [0.0, 0.3, 0.45])  # 복귀 피크 ~ r: 0 → 0.6
        self.assertEqual(w(1790), 0.0)                                                     # 복귀 피크 전은 NONE
        self.assertEqual(vr.soft_weight(1900, e, None, SOFT), 0.0)                         # 복귀 피크를 모르면 앞쪽은 올리지 않는다

    def test_chooser_keeps_base_selection_and_adds_ramp(self):
        y = np.array([0, 0, 2, 0, 0, 0])
        meta = [{"soft_w": w, "soft_class": 2} for w in (0.0, 0.3, 1.0, 0.75, 0.0, 0.0)]
        base = lambda y, meta, seed: np.array([2, 5])
        ch = vr.soft_chooser(base)
        idx = ch(y, meta)
        self.assertEqual(idx.tolist(), [1, 2, 3, 5])
        self.assertEqual(ch.added, 2)
        np.testing.assert_allclose(ch.targets, [[0.7, 0, 0.3, 0, 0], [0, 0, 1, 0, 0], [0.25, 0, 0.75, 0, 0], [1, 0, 0, 0, 0]])


class SoftWarpTests(unittest.TestCase):
    def test_warp_copy_moves_return_peak_with_r(self):
        aug = vr.CONDITIONS["newtcnrotwarpsoft"]["aug"]
        rec = {"source_path": "s/raw_up.1.csv", "completion_ms": 2200, "return_peak_ms": 2050, "direction": "UP", "kind": "raw_up"}
        t = np.arange(400) * 10.0
        raw = np.zeros((400, 6))
        raw[:, 2] = 9.8
        raw[:, 4] = 300 * np.exp(-0.5 * ((t - 2000) / 150) ** 2)
        fn = vr.rotate_warp_augmenter(aug, starts={rec["source_path"]: 1200})
        for copy, _, _ in fn(rec, t, raw):
            if copy["completion_ms"] != rec["completion_ms"]:
                s = (copy["completion_ms"] - aug["anchor_ms"]) / (rec["completion_ms"] - aug["anchor_ms"])
                self.assertAlmostEqual(copy["return_peak_ms"], aug["anchor_ms"] + s * (rec["return_peak_ms"] - aug["anchor_ms"]))


if __name__ == "__main__":
    unittest.main()
