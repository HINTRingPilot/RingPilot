"""BLE v2 보정 실행기 점검. 학습용 데이터 안의 짧은 학습만 쓰며 평가용은 읽지 않는다."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

import v2
import v2_cal


def source(name, e=None, counts=None, events=(), delays=()):
    bg = e is None
    return {"source_path": f"data/sessions/x/{name}", "counts": dict(counts or {}), "delays_ms": list(delays),
            "events": list(events), "completion_ms": e, "direction": "NONE" if bg else "UP",
            "rows": 1000 if bg else 400, "session": "P1"}


def epoch_entry(per_source, loss=1.0):
    return {"event_totals": {}, "per_source": per_source, "val_loss": loss, "window_accuracy": .5, "train_loss": loss}


def seed_result(seed, folds):
    """folds: [{E: [per_source...]}]"""
    return {"seed": seed, "folds": [{"fold": k, "per_epoch": {str(e): epoch_entry(ps) for e, ps in f.items()}}
                                    for k, f in enumerate(folds)]}


class SummarizeTests(unittest.TestCase):
    def test_score_is_pooled_over_folds_then_averaged_over_seeds(self):
        # fold0: 방향 원본 1개(정검출 1), fold1: 3개(정검출 0, 미매칭 3) -> 합산 (1-3)/4 = -0.5
        # (fold 점수 평균이라면 (1 + -1)/2 = 0 이 되어 값이 다르다)
        f0 = [source("raw_up.1.csv", 2000, {"correct": 1})]
        f1 = [source(f"raw_up.{i}.csv", 2000, {"missed": 1, "wrong_direction": 1}) for i in (2, 3, 4)]
        s = v2_cal.summarize_seed_epoch(seed_result(1, [{5: f0}, {5: f1}])["folds"], 5)
        self.assertEqual((s["correct"], s["unmatched"], s["direction_sources"]), (1, 3, 4))
        self.assertAlmostEqual(s["score"], -0.5)

    def test_chosen_epoch_mean_over_seeds_and_tie_goes_to_smaller(self):
        def clip(c, u):
            return [source("raw_up.1.csv", 2000, {"correct": c, "early": u})]
        # E=5: seed별 점수 1, 0 -> 평균 .5 / E=10: 0, 1 -> 평균 .5 (동점) / E=20: 0, 0 -> 0
        a = seed_result(1, [{5: clip(1, 0), 10: clip(0, 0), 20: clip(0, 0)}])
        b = seed_result(2, [{5: clip(0, 0), 10: clip(1, 0), 20: clip(0, 0)}])
        out = v2_cal.summarize_dir([a, b], epochs=(5, 10, 20))
        self.assertEqual((out["chosen_E"], out["tied_epochs"]), (5, [5, 10]))
        self.assertAlmostEqual(out["per_epoch"]["5"]["mean_score"], .5)

    def test_background_false_does_not_change_the_choice_but_is_reported(self):
        def folds(bg_false):
            return [{5: [source("raw_up.1.csv", 2000, {"correct": 1}),
                         source("idle.1.csv", None, {"background_false": bg_false})]}]
        for bg in (0, 9):
            out = v2_cal.summarize_dir([seed_result(1, folds(bg))], epochs=(5,))
            t = out["per_epoch"]["5"]
            self.assertAlmostEqual(t["mean_score"], 1.0)
            self.assertEqual(t["per_seed"]["1"]["kinds"]["background_false"], bg)
        # 10초 클립의 판정 구간 = (1000행*10ms − 1590 ms) = 8.41초
        self.assertAlmostEqual(t["per_seed"]["1"]["background_exposure_s"], 8.41)
        self.assertAlmostEqual(t["per_seed"]["1"]["background_false_per_min"], 9 / (8.41 / 60))

    def test_early_near_completion_and_delay(self):
        ev = [{"timestamp_ms": 1950, "class_index": 1, "kind": "early"}, {"timestamp_ms": 1800, "class_index": 1, "kind": "early"}]
        p = source("raw_up.1.csv", 2000, {"early": 2, "correct": 1}, ev, delays=[120])
        s = v2_cal.summarize_seed_epoch(seed_result(1, [{5: [p]}])["folds"], 5)
        self.assertEqual(s["early_within_100ms"], 1)      # 1950은 e보다 50 ms 앞, 1800은 200 ms 앞
        self.assertEqual(s["delay_ms"], {"n": 1, "median": 120.0, "p95": 120.0})

    def test_clipped_horizon_is_listed(self):
        p = source("raw_left.16.csv", 3530, {"missed": 1})
        s = v2_cal.summarize_seed_epoch(seed_result(1, [{5: [p]}])["folds"], 5)
        self.assertEqual(s["match_horizon_clipped_sources"], ["data/sessions/x/raw_left.16.csv"])


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not v2.RECORDS.exists() or not (v2.SPLITS / "v2-S-P5.json").exists():
            raise unittest.SkipTest("주석·분할이 아직 없다")
        cls.data, cls.by_path = v2.load_records()
        cls.split = v2.load_split("S-P5")

    def test_snapshot_equals_separate_fixed_epoch_run(self):
        """한 번 길게 학습하며 중간 저장한 점수 = 그 epoch에서 멈춘 별도 학습의 점수."""
        d = v2.fold_sets(self.by_path, self.split, 0)
        x_val = np.concatenate([c[1] for c in d["val"]])
        long_run, _ = v2.fit_snapshots(d["x_train"], d["y_train"], x_val, v2.SEED, (3, 6))
        short_run, _ = v2.fit_snapshots(d["x_train"], d["y_train"], x_val, v2.SEED, (3,))
        self.assertEqual(float(np.abs(long_run[3] - short_run[3]).max()), 0.0)
        self.assertGreater(float(np.abs(long_run[3] - long_run[6]).max()), 0.0)   # 시점마다 실제로 다른 가중치

    def test_mini_run_structure_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            result = v2_cal.run_seed("S-P5", v2.SEED, tmp, tmp / "scores", folds=[1], epochs=(1, 2), log=lambda *a: None)
            v2.dump(tmp / "r.json", result)                      # NaN·numpy 형식이 섞이면 여기서 실패한다
            result = json.loads((tmp / "r.json").read_text(encoding="utf-8"))
            fold = result["folds"][0]
            held = self.split["cv"]["folds"][1]["validation_sources"]
            self.assertEqual(fold["held_out_session"], self.split["cv"]["folds"][1]["held_out_session"])
            self.assertEqual(len(fold["train_loss_by_epoch"]), 2)
            for e in ("1", "2"):
                entry = fold["per_epoch"][e]
                self.assertEqual(sorted(p["source_path"] for p in entry["per_source"]), sorted(held))   # 원본마다 정확히 한 번
                summed = {}
                for p in entry["per_source"]:
                    for k, v in p["counts"].items():
                        summed[k] = summed.get(k, 0) + v
                self.assertEqual({k: v for k, v in summed.items() if v}, {k: v for k, v in entry["event_totals"].items() if v})
                self.assertTrue(np.isfinite(entry["val_loss"]) and 0 <= entry["window_accuracy"] <= 1)
            with np.load(tmp / "scores" / f"seed-{v2.SEED}-fold-1-scores.npz") as scores:
                shape = scores["e1"].shape
            windows = json.loads((tmp / "scores" / f"seed-{v2.SEED}-fold-1-windows.json").read_text(encoding="utf-8"))
            self.assertEqual(shape, (len(windows), 5))
            expected = sum(len(v2.decision_times(self.by_path[p]["rows"])) for p in held)
            self.assertEqual(len(windows), expected)            # NONE 창을 줄이지 않음
            # 평가용 원본은 어디에도 나오지 않는다
            evaluation = set(self.split["eval_sources"])
            self.assertFalse(evaluation & {w["source_path"] for w in windows})


if __name__ == "__main__":
    unittest.main()
