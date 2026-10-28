"""회전 + 속도 증강(newtcnrotwarp) 점검. 학습하지 않는다. 계획 docs/superpowers/plans/2026-10-27-v2-augmentation.md §7(3차 개정)."""
import unittest

import numpy as np

import v2
import v2_return as vr

AUG = vr.CONDITIONS["newtcnrotwarp"]["aug"]
B = np.array([3.0, -10.0, 5.0])


def bump_raw(rows=400, center_ms=2000.0, width_ms=200.0, peak=300.0):
    """정지(영점 B + 작은 잡음) 뒤 매끈한 회전 덩어리 하나. 가속도는 중력 + 완만한 변화."""
    t = np.arange(rows) * 10.0
    rng = np.random.default_rng(0)
    raw = np.zeros((rows, 6))
    raw[:, :3] = [0.5, 0.2, 9.8] + 0.3 * np.sin(t / 700.0)[:, None]
    raw[:, 3:] = B + rng.normal(0, 0.3, size=(rows, 3))
    raw[:, 4] += peak * np.exp(-0.5 * ((t - center_ms) / width_ms) ** 2)
    return raw


def scale_of(path, copy):
    rng = vr.clip_rng(path, copy)
    vr.random_rotation(rng, AUG["rot_y_deg"], AUG["tilt_deg"])
    return float(np.exp(rng.uniform(np.log(AUG["scale_min"]), np.log(AUG["scale_max"]))))


class WarpRawTests(unittest.TestCase):
    def test_unit_scale_is_identity(self):
        raw = bump_raw()
        out, n, jump = vr.warp_raw(raw, 1.0, B, 890)
        np.testing.assert_allclose(out, raw, rtol=0, atol=1e-12)
        self.assertEqual((n, jump), (400, 0.0))

    def test_precue_rows_and_bias_are_untouched(self):
        raw = bump_raw()
        for s in (0.8, 1.25):
            out, _, _ = vr.warp_raw(raw, s, B, 890)
            np.testing.assert_array_equal(out[:vr.PRECUE_SAMPLES], raw[:vr.PRECUE_SAMPLES])   # 0~890 ms 90행
            np.testing.assert_array_equal(np.median(out[:vr.PRECUE_SAMPLES, 3:6], axis=0),
                                          np.median(raw[:vr.PRECUE_SAMPLES, 3:6], axis=0))
            self.assertFalse(np.array_equal(out[vr.PRECUE_SAMPLES:], raw[vr.PRECUE_SAMPLES:]))

    def test_values_follow_the_time_map(self):
        raw, s = bump_raw(), 0.85
        out, n, jump = vr.warp_raw(raw, s, B, 890)
        t = np.arange(400) * 10.0
        for row in (90, 150, 230, n - 1):
            src = 890 + (t[row] - 890) / s
            g = np.array([np.interp(src, t, raw[:, j]) for j in range(6)])
            np.testing.assert_allclose(out[row, :3], g[:3], atol=1e-12)                        # 가속도는 보간만
            np.testing.assert_allclose(out[row, 3:], (g[3:] - B) / s + B, atol=1e-12)         # 자이로는 영점 빼고 1/s배
        g900 = np.array([np.interp(890 + 10 / s, t, raw[:, j]) for j in range(3, 6)])
        self.assertAlmostEqual(jump, float(np.max(np.abs(g900 - B)) * abs(1 / s - 1)), places=12)

    def test_valid_rows(self):
        raw = bump_raw()
        self.assertEqual(vr.warp_raw(raw, 0.8, B, 890)[1], 338)    # 890 + 0.8·3100 = 3370 ms까지 유효
        self.assertEqual(vr.warp_raw(raw, 1.25, B, 890)[1], 400)

    def test_rotation_amount_is_preserved_over_the_motion(self):
        # 대응 동작 구간: 원본 [start, r+150] ↔ 사본 [890 + s(start−890), r′+150]. 끝(r+150 = 2550 ms)은 덩어리가
        # 아직 0이 아닌 곳이라 구간 경계가 실제로 맞아야 통과한다. 샘플 사이는 선형 보간한 1 ms 격자로 적분한다.
        raw, t = bump_raw(), np.arange(400) * 10.0
        start, r = 1400.0, 2400.0

        def amount(x, a, b):
            fine = np.arange(a, b + 0.5, 1.0)
            return np.trapezoid(np.interp(fine, t, x[:, 4]) - B[1], dx=0.001)

        orig = amount(raw, start, r + 150)
        for s in (0.8, 0.9, 1.1, 1.25):
            out, _, _ = vr.warp_raw(raw, s, B, 890)
            r2 = 890 + s * (r - 890)
            self.assertAlmostEqual(amount(out, 890 + s * (start - 890), r2 + 150), orig, delta=abs(orig) * 5e-3, msg=s)
            self.assertGreater(abs(amount(out, 890 + s * (start - 890), r2 + 150) - amount(out, 890 + s * (start - 890), r2)), 1.0)

    def test_positive_windows(self):
        self.assertEqual(vr.positive_windows(2000, 400, 400), 3)
        self.assertEqual(vr.positive_windows(1506, 400, 400), 2)      # 첫 판정 1590 ms 앞으로 당겨짐
        self.assertEqual(vr.positive_windows(3300, 400, 338), 1)      # 유효 끝 3370 ms: 3340만 남음
        self.assertEqual(vr.positive_windows(3900, 400, 400), 2)      # 3940, 3990


class RotateWarpCopyTests(unittest.TestCase):
    def setUp(self):
        self.raw = bump_raw()
        self.rot = vr.rotate_augmenter(vr.CONDITIONS["newtcnrot"]["aug"])

    def gesture(self, name, e=2200):
        return {"source_path": f"x/{name}", "kind": "raw_up", "direction": "UP", "completion_ms": e}

    def test_rotation_matches_newtcnrot_and_label_moves(self):
        rec = self.gesture("raw_up.1.csv")
        fn = vr.rotate_warp_augmenter(AUG, starts={rec["source_path"]: 1500})
        for c, ((rw, xw, nw), (rr, xr, nr)) in enumerate(zip(fn(rec, None, self.raw), self.rot(rec, None, self.raw)), 1):
            self.assertEqual(rw["source_path"], rr["source_path"])                            # 같은 사본 이름(#rot1·#rot2)
            np.testing.assert_array_equal(xw[:vr.PRECUE_SAMPLES], xr[:vr.PRECUE_SAMPLES])     # 같은 R, 영점 구간 보존
            s = scale_of(rec["source_path"], c)
            self.assertAlmostEqual(rw["completion_ms"], 890 + s * (2200 - 890))
            self.assertEqual({**rw, "completion_ms": 2200}, {**rec, "source_path": rr["source_path"]})
        self.assertEqual(fn.stats["warp"], 2)

    def test_ineligible_copies_equal_newtcnrot(self):
        bg = {"source_path": "x/idle.1.csv", "kind": "idle", "direction": "NONE", "completion_ms": None}
        early = self.gesture("raw_up.2.csv")
        recs = [bg, early]
        starts = {early["source_path"]: 880}
        jumpy = self.gesture("raw_up.3.csv")
        recs.append(jumpy)
        starts[jumpy["source_path"]] = 1500
        fn = vr.rotate_warp_augmenter({**AUG, "max_jump_dps": 0.0}, starts=starts)           # 모든 경계 점프가 기준 초과
        for rec in recs:
            for (rw, xw, nw), (rr, xr, nr) in zip(fn(rec, None, self.raw), self.rot(rec, None, self.raw)):
                self.assertEqual((rw, nw), (rr, nr))
                np.testing.assert_array_equal(xw, xr)
        self.assertEqual(dict(fn.stats), {"background": 2, "early_start": 2, "jump": 2})

    def check_positive_loss(self, e):
        """라벨 e의 사본 중 양성 창 수가 줄어드는 사본만 회전만 남는다(s에 따라 갈림)."""
        recs = [self.gesture(f"raw_up.{i}.csv", e=e) for i in range(40)]
        fn = vr.rotate_warp_augmenter(AUG, starts={r["source_path"]: 1100 for r in recs})
        lost = []
        for rec in recs:
            for c, ((rw, xw, nw), (rr, xr, nr)) in enumerate(zip(fn(rec, None, self.raw), self.rot(rec, None, self.raw)), 1):
                s = scale_of(rec["source_path"], c)
                valid = vr.warp_raw(xr, s, B, 890)[1]
                is_lost = vr.positive_windows(890 + s * (e - 890), 400, valid) < vr.positive_windows(e, 400, 400)
                lost.append((s, is_lost))
                self.assertEqual(np.array_equal(xw, xr), is_lost)
                if not is_lost:
                    _, y, meta = v2.windows_from_raw(rw, np.arange(400) * 10.0, xw, np.zeros(6), np.ones(6))
                    kept = [lab for lab, m in zip(y, meta) if m["timestamp_ms"] <= (nw - 1) * 10]
                    self.assertEqual(int(np.sum(np.array(kept) > 0)), vr.positive_windows(e, 400, 400))
        n_lost = sum(is_lost for _, is_lost in lost)
        self.assertEqual(fn.stats["positive_loss"], n_lost)
        self.assertTrue(0 < n_lost < 80, n_lost)
        return lost

    def test_positive_loss_at_the_end(self):
        self.check_positive_loss(3600)      # r′ > 3890 ms(s > 1.107)이면 3990 ms 안에 양성 창 2개만 남는다

    def test_positive_loss_before_the_first_decision(self):
        self.check_positive_loss(1660)      # r′ ≤ 1540 ms(s ≤ 0.844)이면 첫 판정 1590 ms 앞이라 양성 창이 2개로 준다

    def test_positive_loss_inside_the_valid_end(self):
        # s < 1이면 유효 끝이 890 + 3100s로 당겨진다. 이전 조건(r′+150 ≤ 3990 ms)은 이 경우를 놓쳤다
        lost = self.check_positive_loss(3900)
        missed_before = [is_lost and 890 + s * (3900 - 890) + v2.POSITIVE_MS <= 3990 for s, is_lost in lost]
        self.assertGreater(sum(missed_before), 0)

    def test_scale_range(self):
        s = [scale_of(f"x/raw_up.{i}.csv", c) for i in range(200) for c in (1, 2)]
        self.assertTrue(0.8 <= min(s) and max(s) <= 1.25)
        self.assertLess(abs(np.median(np.log(s))), 0.05)                                         # 로그 균등: 중앙값 ≈ 1


class RotateWarpFoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not v2.RECORDS.exists():
            raise unittest.SkipTest("records.json이 아직 없다")
        _, cls.by_path, cls.nb = vr.load()

    def test_every_gesture_has_a_motion_start(self):
        starts = vr.motion_starts()
        gestures = [p for p, r in self.by_path.items() if r["completion_ms"] is not None]
        self.assertTrue(all(p in starts for p in gestures))
        self.assertEqual(sum(starts[p] < 900 for p in gestures), 22)   # 2026-10-28 raw_left.1(신호 전 동작) 제외로 23 → 22

    def test_fold_keeps_copy_count_and_validation(self):
        split = v2.load_split("C")
        d, _ = vr.prepare_fold("newtcnrotwarp", self.by_path, self.nb, split, 0)
        rot, _ = vr.prepare_fold("newtcnrot", self.by_path, self.nb, split, 0)
        self.assertEqual(d["train_aug_copies"], rot["train_aug_copies"])
        self.assertEqual(sum(d["train_aug_stats"].values()), d["train_aug_copies"])
        self.assertGreater(d["train_aug_stats"]["warp"], 0)
        self.assertEqual(d["train_aug_skipped"], 0)
        self.assertFalse(any("#" in c[0]["source_path"] for c in d["val"]))
        np.testing.assert_array_equal(d["mean"], rot["mean"])
        np.testing.assert_array_equal(d["std"], rot["std"])
        for c, cr in zip(d["val"], rot["val"]):
            np.testing.assert_array_equal(c[1][:, :, :6], cr[1][:, :, :6])


if __name__ == "__main__":
    unittest.main()
