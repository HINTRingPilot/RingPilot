"""회전 증강(newtcnrot) 점검. 학습하지 않는다. 계획 docs/superpowers/plans/2026-10-27-v2-augmentation.md §6.

수식 검사는 알려진 영점 b로 한다. 실제 중앙값 추정기를 사본에 다시 적용한 영향은 합격·불합격이 아니라 측정으로 따로 보고한다.
"""
import unittest

import numpy as np

import v2
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


class RotationCopyTests(unittest.TestCase):
    aug = vr.CONDITIONS["newtcnrot"]["aug"]

    def test_condition_matches_newtcnrt_except_aug(self):
        rot, rt = dict(vr.CONDITIONS["newtcnrot"]), dict(vr.CONDITIONS["newtcnrt"])
        self.assertEqual(rot.pop("aug"), {"kind": "rotate", "rot_y_deg": 30, "tilt_deg": 15, "copies": 2})
        self.assertEqual(rt.pop("aug"), None)
        self.assertEqual(rot, rt)

    def test_copies_are_fixed_per_clip_and_copy(self):
        augment = vr.augmenter(self.aug)
        raw = fake_raw()
        rec = {"source_path": "data/sessions/x/raw_up.1.csv", "kind": "raw_up", "direction": "UP", "completion_ms": 2000}
        a, b = augment(rec, None, raw), augment(dict(rec), None, raw.copy())
        self.assertEqual([c[0]["source_path"] for c in a], [rec["source_path"] + "#rot1", rec["source_path"] + "#rot2"])
        for (ra, xa, na), (rb, xb, nb) in zip(a, b):
            np.testing.assert_array_equal(xa, xb)
            self.assertEqual((na, nb), (400, 400))
            self.assertEqual({**ra, "source_path": rec["source_path"]}, rec)    # 라벨 시각·방향은 원본 그대로
        self.assertFalse(np.array_equal(a[0][1], a[1][1]))
        other = augment({**rec, "source_path": "data/sessions/x/raw_up.2.csv"}, None, raw)
        self.assertFalse(np.array_equal(a[0][1], other[0][1]))

    def test_windows_keep_labels_and_none_groups(self):
        rec = {"source_path": "x/raw_up.1.csv", "kind": "raw_up", "direction": "UP", "completion_ms": 2000}
        raw, ts = fake_raw(), np.arange(400) * 10.0
        rc, raw_c, _ = vr.augmenter(self.aug)(rec, ts, raw)[0]
        _, y, meta = v2.windows_from_raw(rec, ts, raw, np.zeros(6), np.ones(6))
        _, yc, meta_c = v2.windows_from_raw(rc, ts, raw_c, np.zeros(6), np.ones(6))
        np.testing.assert_array_equal(y, yc)
        self.assertEqual([m["none_group"] for m in meta], [m["none_group"] for m in meta_c])


class RotationFoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not v2.RECORDS.exists():
            raise unittest.SkipTest("records.json이 아직 없다")
        _, cls.by_path, cls.nb = vr.load()

    def test_fold_adds_two_copies_to_training_only(self):
        split = v2.load_split("C")
        d, _ = vr.prepare_fold("newtcnrot", self.by_path, self.nb, split, 0)
        base, _ = vr.prepare_fold("newtcnrt", self.by_path, self.nb, split, 0)
        self.assertEqual((d["train_aug_copies"], d["train_aug_skipped"], d["train_windows_excluded"]),
                         (2 * d["train_sources"], 0, 0))
        self.assertEqual(d["train_all_counts"][1:], [3 * n for n in base["train_all_counts"][1:]])
        self.assertFalse(any("#" in c[0]["source_path"] for c in d["val"]))
        # 6축 정규화 통계와 검증 6축 창은 증강과 무관하다(회전각 3채널은 학습 창 통계로 정규화하므로 달라진다)
        np.testing.assert_array_equal(d["mean"], base["mean"])
        np.testing.assert_array_equal(d["std"], base["std"])
        for c, cb in zip(d["val"], base["val"]):
            np.testing.assert_array_equal(c[1][:, :, :6], cb[1][:, :, :6])


if __name__ == "__main__":
    unittest.main()
