"""정지 구간 평균을 뺀 가속도 조건(newtcnrotwarpaccsub) 점검. 마지막 테스트만 fold 하나의 학습 집합을 만든다(학습은 하지 않는다)."""
import unittest

import numpy as np

import v2
import v2_return as vr

REC = {"source_path": "synthetic", "completion_ms": None, "kind": "background"}


def synthetic_raw(n=400):
    rng = np.random.default_rng(0)
    raw = rng.normal(scale=0.1, size=(n, 6))
    raw[:, 0:3] += (1.0, -2.0, 9.5)          # 정지 자세의 중력
    raw[200:, 0:3] += (3.0, 0.0, -4.0)       # 동작 중 바뀐 가속도
    return np.arange(n) * 10.0, raw


class WindowTests(unittest.TestCase):
    def test_precue_mean_is_removed_from_acc_only(self):
        ts, raw = synthetic_raw()
        mean, std = np.zeros(6), np.ones(6)
        x0, _, _ = vr.windows_with_angle(REC, ts, raw, mean, std, "precue")
        x1, _, _ = vr.windows_with_angle(REC, ts, raw, mean, std, "precue", acc_mode="precue_sub")
        static = raw[:vr.PRECUE_SAMPLES, 0:3].mean(axis=0)
        np.testing.assert_allclose(x1[:, :, 0:3], x0[:, :, 0:3] - static, atol=1e-5)
        np.testing.assert_array_equal(x1[:, :, 3:], x0[:, :, 3:])
        self.assertLess(np.abs(x1[0, :, 0:3]).max(), 1.0)          # 첫 창(정지 구간)은 0 근처

    def test_condition_differs_only_in_acc(self):
        accsub = dict(vr.CONDITIONS["newtcnrotwarpaccsub"])
        self.assertEqual(accsub.pop("acc"), "precue_sub")
        self.assertEqual(accsub, vr.CONDITIONS["newtcnrotwarp"])


class FoldTests(unittest.TestCase):
    def test_fold_acc_channels_are_normalized_on_train_windows(self):
        _, by_path, nb = vr.load()
        d, _ = vr.prepare_fold("newtcnrotwarpaccsub", by_path, nb, v2.load_split("S-P5"), 0)
        self.assertEqual(d["x_train"].shape[2], 9)
        acc = d["x_train"][:, :, 0:3].astype(np.float64)
        np.testing.assert_allclose(acc.mean(axis=(0, 1)), 0, atol=1e-3)
        np.testing.assert_allclose(acc.std(axis=(0, 1)), 1, atol=1e-3)
        prep = vr.prep_values("newtcnrotwarpaccsub", d)
        self.assertEqual(prep["acc_mode"], "precue_sub")
        self.assertEqual(len(prep["acc_mean"]), 3)
        self.assertEqual(prep["input_channels"][:3], ["accX", "accY", "accZ"])
