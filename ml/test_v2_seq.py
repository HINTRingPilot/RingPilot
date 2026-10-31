"""앞 동작 합성 사본(newtcnrotwarpnoaccseq) 점검. 학습하지 않는다."""
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


class FoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.by_path, cls.nb = vr.load()
        cls.split = v2.load_split("S-P5")
        cls.seq, _ = vr.prepare_fold("newtcnrotwarpnoaccseq", cls.by_path, cls.nb, cls.split, 0)
        cls.base, _ = vr.prepare_fold("newtcnrotwarpnoacc", cls.by_path, cls.nb, cls.split, 0)

    def test_adds_training_windows_only(self):
        self.assertGreater(len(self.seq["y_train"]), len(self.base["y_train"]))
        self.assertEqual(len(self.seq["val"]), len(self.base["val"]))
        for a, b in zip(self.seq["val"], self.base["val"]):
            self.assertEqual(a[0]["source_path"], b[0]["source_path"])
        np.testing.assert_array_equal(self.seq["mean"], self.base["mean"])

    def test_prior_never_comes_from_validation(self):
        val = set(self.split["cv"]["folds"][0]["validation_sources"])
        pool = {p for p in self.split["train_sources"] if p not in val}
        seen = []
        real = vr.v2.read_sensor

        def spy(path):
            seen.append(str(path).replace("\\", "/"))
            return real(path)
        vr.v2.read_sensor = spy
        try:
            vr.prepare_fold("newtcnrotwarpnoaccseq", self.by_path, self.nb, self.split, 0)
        finally:
            vr.v2.read_sensor = real
        allowed = {p for p in pool} | {p for p in val}
        self.assertTrue(all(any(s.endswith(p) for p in allowed) for s in seen))
        cond = vr.CONDITIONS["newtcnrotwarpnoaccseq"]
        starts = vr.motion_starts()
        fn = vr.seq_augmenter(lambda r, t, x: [], cond["aug"], cond["seq"], sorted(pool & set(self.nb)), self.nb, starts)
        record = {**self.by_path[sorted(pool & set(self.nb))[0]], "completion_ms": 2000.0}
        ts, raw = real(v2.ROOT / record["source_path"])
        seen.clear()
        vr.v2.read_sensor = spy
        try:
            fn(record, ts, raw)
        finally:
            vr.v2.read_sensor = real
        self.assertTrue(seen)
        self.assertFalse(any(any(s.endswith(p) for p in val) for s in seen))


if __name__ == "__main__":
    unittest.main()
