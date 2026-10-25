"""BLE v2 간격-조기발행 진단 점검. 저장된 로그만 읽으며 학습하지 않는다."""
import tempfile
import unittest
from pathlib import Path

import v2
import v2_cal
import v2_gap_review as g


def ev(t, kind):
    return {"timestamp_ms": t, "class_index": 1, "kind": kind}


def src(name, e, events, counts):
    return {"source_path": f"data/sessions/x/{name}", "completion_ms": e, "direction": "UP", "rows": 400,
            "events": events, "counts": counts, "delays_ms": []}


def results(per_seed_sources):
    return [{"seed": s, "folds": [{"per_epoch": {"60": {"per_source": srcs}}}]} for s, srcs in enumerate(per_seed_sources)]


class Binning(unittest.TestCase):
    def test_bin_edges(self):
        self.assertEqual(g.bin_of(0), (0, 100))
        self.assertEqual(g.bin_of(99), (0, 100))
        self.assertEqual(g.bin_of(100), (100, 200))
        self.assertEqual(g.bin_of(299), (200, 300))
        self.assertEqual(g.bin_of(300), (300, 100000))
        self.assertEqual(g.bin_of(810), (300, 100000))
        self.assertIsNone(g.bin_of(-1))
        self.assertEqual([g.bin_name(b) for b in g.GAP_BINS], ["0~100", "100~200", "200~300", "300~"])

    def test_gap(self):
        self.assertEqual(g.gap_ms({"completion_ms": 2400, "main_motion_end_ms": 2280}), 120)


class ClipRates(unittest.TestCase):
    def test_clip_seed_fractions_and_bins(self):
        ann = {"data/sessions/x/raw_up.1.csv": {"completion_ms": 2000, "main_motion_end_ms": 1950},     # 간격 50
               "data/sessions/x/raw_up.2.csv": {"completion_ms": 2000, "main_motion_end_ms": 1500}}     # 간격 500
        a = lambda kind_list: [ev(1900 + 10 * i, k) for i, k in enumerate(kind_list)]
        seeds = [
            [src("raw_up.1.csv", 2000, a(["correct"]), {"correct": 1}), src("raw_up.2.csv", 2000, a(["early", "early"]), {"early": 2, "missed": 1})],
            [src("raw_up.1.csv", 2000, [], {"missed": 1}), src("raw_up.2.csv", 2000, a(["early"]), {"early": 1, "missed": 1})],
        ]
        rows = g.clip_table(results(seeds), 60, ann)
        by = {r["source_path"].rsplit("/", 1)[1]: r for r in rows}
        self.assertEqual((by["raw_up.1.csv"]["correct_frac"], by["raw_up.1.csv"]["emitted_frac"], by["raw_up.1.csv"]["early_frac"]), (.5, .5, 0))
        # 한 클립에서 조기 발행이 두 번이어도 그 seed는 한 번만 센다
        self.assertEqual((by["raw_up.2.csv"]["early_frac"], by["raw_up.2.csv"]["correct_frac"]), (1.0, 0.0))
        table = g.by_gap_bin(rows)
        self.assertEqual((table["0~100"]["clips"], table["0~100"]["clip_seed_pairs"], table["0~100"]["correct"]), (1, 2, .5))
        self.assertEqual((table["300~"]["clips"], table["300~"]["early"]), (1, 1.0))
        self.assertEqual(table["100~200"]["clips"], 0)
        self.assertIsNone(table["100~200"]["early"])

    def test_background_clips_are_ignored(self):
        bg = src("idle.1.csv", None, [ev(3000, "background_false")], {"background_false": 1})
        self.assertEqual(g.clip_table(results([[bg]]), 60, {}), [])


class Correlation(unittest.TestCase):
    def test_spearman(self):
        self.assertAlmostEqual(g.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(g.spearman([1, 2, 3, 4], [40, 30, 20, 10]), -1.0)
        self.assertIsNone(g.spearman([1, 2, 3, 4], [5, 5, 5, 5]))
        self.assertIsNone(g.spearman([1, 2], [1, 2]))
        self.assertAlmostEqual(g.spearman([1, 2, 2, 4], [1, 2, 2, 4]), 1.0)     # 동순위


class SavedResults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (v2_cal.results_dir("V2-S-P5-cal") / "summary.json").exists():
            raise unittest.SkipTest("과거 결과가 없다")

    def test_every_direction_clip_appears_once_per_run(self):
        ann = g.v2_diag.load_annotations()
        row = g.analyse("S-P5", "60", ann)
        self.assertEqual(row["n_clips"], 237)
        self.assertEqual(sum(b["clips"] for b in row["by_gap_bin"].values()), 237)

    def test_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "gap-vs-early.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                g.main(tmp)


if __name__ == "__main__":
    unittest.main()
