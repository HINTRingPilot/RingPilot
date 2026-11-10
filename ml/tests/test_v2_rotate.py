"""회전 증강 수식 점검(사본 생성은 test_v2_rotwarp.py). 학습하지 않는다. 계획 docs/superpowers/plans/2026-10-27-v2-augmentation.md §6.

수식 검사는 알려진 영점 b로 한다. 실제 중앙값 추정기를 사본에 다시 적용한 영향은 합격·불합격이 아니라 측정으로 따로 보고한다.
"""
import unittest

import numpy as np

import v2_return as vr


def fake_raw(seed=0, rows=400):
    rng = np.random.default_rng(seed)
    acc = rng.normal([0, 0, 9.8], 2.0, size=(rows, 3))
    gyro = rng.normal([3, -10, 5], 60.0, size=(rows, 3))
    return np.concatenate([acc, gyro], axis=1)


class RotationMathTests(unittest.TestCase):
    def test_rotation_matrix_is_proper(self):
        rng = np.random.default_rng(1)
        for _ in range(50):
            r = vr.random_rotation(rng, 30, 15)
            np.testing.assert_allclose(r @ r.T, np.eye(3), atol=1e-12)
            self.assertAlmostEqual(np.linalg.det(r), 1.0, places=12)

    def test_y_rotation_keeps_y_axis_and_angle_range(self):
        rng = np.random.default_rng(2)
        for _ in range(50):
            r = vr.random_rotation(rng, 30, 0)
            np.testing.assert_allclose(r @ [0, 1, 0], [0, 1, 0], atol=1e-12)
            self.assertLessEqual(np.degrees(np.arccos(np.clip(r[0, 0], -1, 1))), 30 + 1e-9)

    def test_identity_returns_the_original(self):
        raw = fake_raw()
        b = np.median(raw[:vr.PRECUE_SAMPLES, 3:6], axis=0)
        np.testing.assert_allclose(vr.rotate_raw(raw, np.eye(3), b), raw, rtol=0, atol=1e-12)

    def test_magnitudes_are_preserved(self):
        raw, b = fake_raw(), np.array([3.0, -10.0, 5.0])
        r = vr.random_rotation(np.random.default_rng(3), 30, 15)
        out = vr.rotate_raw(raw, r, b)
        np.testing.assert_allclose(np.linalg.norm(out[:, :3], axis=1), np.linalg.norm(raw[:, :3], axis=1), rtol=1e-12)
        np.testing.assert_allclose(np.linalg.norm(out[:, 3:] - b, axis=1), np.linalg.norm(raw[:, 3:] - b, axis=1), rtol=1e-12)

    def test_cumulative_angle_rotates_with_known_bias(self):
        raw, b = fake_raw(4), np.array([3.0, -10.0, 5.0])
        r = vr.random_rotation(np.random.default_rng(5), 30, 15)
        out = vr.rotate_raw(raw, r, b)
        angle = np.cumsum((raw[:, 3:] - b) * vr.SAMPLE_S, axis=0)
        np.testing.assert_allclose(np.cumsum((out[:, 3:] - b) * vr.SAMPLE_S, axis=0), angle @ r.T, atol=1e-9)


if __name__ == "__main__":
    unittest.main()
