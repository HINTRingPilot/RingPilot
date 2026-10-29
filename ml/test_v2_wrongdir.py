"""다른 방향 발행 진단 점검. 학습하지 않는다."""
import unittest

import numpy as np

import v2_return as vr
import v2_wrongdir as wd

N = {"outbound_peak_ms": 1660, "extreme_ms": 1820, "return_peak_ms": 1900, "event_ms": 2000,
     "dominant_axis": "gyrY", "outbound_sign": "-"}


class PhaseTests(unittest.TestCase):
    def test_buckets(self):
        self.assertEqual(wd.phase(1600, N), "가는 피크 전")
        self.assertEqual(wd.phase(1700, N), "가는 피크~끝점")
        self.assertEqual(wd.phase(1820, N), "끝점~복귀 피크")
        self.assertEqual(wd.phase(1950, N), "복귀 피크~r")
        self.assertEqual(wd.phase(2000 + vr.EXTREME_AFTER_R_MS, N), "r~r+300")
        self.assertEqual(wd.phase(2001 + vr.EXTREME_AFTER_R_MS, N), "r+300 뒤")

    def test_rebound_uses_outbound_sign(self):
        raw = np.zeros((400, 6))
        raw[195, 4] = -250.0      # 복귀 피크 뒤 가는 방향(−)으로 다시 튐
        raw[200, 4] = 300.0       # 복귀 방향(+)은 반동으로 세지 않는다
        self.assertEqual(wd.rebound_dps(N, raw), 250.0)


class StoredResultTests(unittest.TestCase):
    def test_noacc_s_p5_e60_matches_hand_count(self):
        # 2026-10-29 손 계산(계획 §0.2): 20건, 반대 방향 14건, 정답 뒤 7건
        _, by_path, nb = vr.load()
        rows = wd.off_direction(wd.load_results("noacc-20261029", "newtcnrotwarpnoacc", "S-P5", by_path, nb), 60, nb)
        self.assertEqual(len(rows), 20)
        self.assertEqual(sum(r["opposite"] for r in rows), 14)
        self.assertEqual(sum(r["after_correct"] for r in rows), 7)
