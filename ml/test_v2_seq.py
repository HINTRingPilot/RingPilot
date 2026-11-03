"""앞 동작 합성(compose_sequence, 연속 동작 평가용) 점검. 학습하지 않는다."""
import unittest

import numpy as np

import v2
import v2_return as vr


def fake_clip(bias, center_ms, rows=400):
    t = np.arange(rows) * 10.0
    raw = np.zeros((rows, 6))
    raw[:, 2] = 9.8
    raw[:, 3:] = bias
    raw[:, 4] += 300 * np.exp(-0.5 * ((t - center_ms) / 60) ** 2)
    return raw


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.raw = fake_clip([1.0, 2.0, 3.0], 1800)
        self.prior = fake_clip([-4.0, 5.0, -6.0], 1500)

    def test_keeps_precue_and_aligns_bias(self):
        out, _, _, _ = vr.compose_sequence(self.raw, 1600, 1950, self.prior, 1300, 1650, 200, 100)
        np.testing.assert_array_equal(out[:vr.PRECUE_SAMPLES], self.raw[:vr.PRECUE_SAMPLES])
        np.testing.assert_allclose(np.median(out[:vr.PRECUE_SAMPLES, 3:6], axis=0), [1.0, 2.0, 3.0])
        # 앞 동작 첫 행의 자이로 X·Z는 이 클립의 영점이어야 한다
        np.testing.assert_allclose(out[vr.PRECUE_SAMPLES, [3, 5]], [1.0, 3.0])

    def test_moves_labels_with_motion(self):
        out, valid, r2, prior_r2 = vr.compose_sequence(self.raw, 1600, 1950, self.prior, 1300, 1650, 200, 100)
        self.assertEqual(prior_r2, 900 + 350)
        # 정지 90행 + 앞 동작 (1650 + 100 − 1300)/10 = 45행 + 간격 20행 뒤에 원본 1600 ms가 온다
        self.assertEqual(r2, 1950 + (90 + 45 + 20) * 10 - 1600)
        self.assertEqual(out.shape, self.raw.shape)
        self.assertEqual(valid, 395)   # 원본 끝까지 이어도 400행에 못 미친다
        start = 90 + 45 + 20
        np.testing.assert_array_equal(out[start:start + 50], self.raw[160:210])

    def test_valid_rows_when_shorter(self):
        _, valid, _, _ = vr.compose_sequence(self.raw, 3500, 3600, self.prior, 1300, 1400, 0, 0)
        self.assertEqual(valid, 90 + 10 + 50)


if __name__ == "__main__":
    unittest.main()
