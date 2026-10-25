"""BLE v2 NONE 선택 확인 도구 점검. 학습하지 않고 저장된 입력만 읽으며, 출력은 임시 폴더에만 쓴다."""
import copy
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import v2
import v2_none_review as nr


def meta_at(t, target=0, group="in_progress", path="data/sessions/x/raw_up.1.csv"):
    return {"source_path": path, "timestamp_ms": t, "target": target, "none_group": group}


def direction_record(e=2000, path="data/sessions/x/raw_up.1.csv"):
    return {"source_path": path, "session": "P1", "direction": "UP", "kind": "raw_up", "completion_ms": e}


class Buckets(unittest.TestCase):
    def test_boundaries_relative_to_completion(self):
        cases = {-601: "pre_earlier", -600: "pre_300_600", -301: "pre_300_600", -300: "pre_0_300", -1: "pre_0_300", 150: "post", 151: "post"}
        for dt, name in cases.items():
            self.assertEqual(nr.bucket_for_offset(dt), name, dt)

    def test_positive_zone_is_never_a_none_bucket(self):
        for dt in (0, 1, 100, 149):
            with self.assertRaises(ValueError):
                nr.bucket_for_offset(dt)

    def test_clip_row_counts_and_edges(self):
        e = 2000
        times = [e - 650, e - 600, e - 350, e - 300, e - 50, e, e + 100, e + 150, e + 200]
        meta = [meta_at(t, target=1 if e <= t < e + 150 else 0, group="in_progress" if t < e else "post_completion") for t in times]
        selected = [False, True, False, True, True, True, True, False, True]
        row = nr.clip_row(direction_record(e), meta, selected)
        self.assertEqual(row["available"], {"pre_0_300": 2, "pre_300_600": 2, "pre_earlier": 1, "post": 2})
        # 양성 창(e, e+100)은 NONE으로 세지 않는다(선택 여부와 무관)
        self.assertEqual(row["selected"], {"pre_0_300": 2, "pre_300_600": 1, "pre_earlier": 0, "post": 1})

    def test_selected_never_exceeds_available_and_sums_match(self):
        e = 2000
        times = list(range(1590, 3990, 50))
        meta = [meta_at(t, target=1 if e <= t < e + 150 else 0, group="in_progress" if t < e else "post_completion") for t in times]
        selected = [i % 3 == 0 for i in range(len(times))]
        row = nr.clip_row(direction_record(e), meta, selected)
        for b in row["available"]:
            self.assertLessEqual(row["selected"][b], row["available"][b])
        self.assertEqual(sum(row["available"].values()), sum(m["target"] == 0 for m in meta))
        self.assertEqual(sum(row["selected"].values()), sum(f for m, f in zip(meta, selected) if m["target"] == 0))

    def test_background_clip_goes_to_its_own_bucket(self):
        rec = {"source_path": "data/sessions/x/idle.1.csv", "session": "P2", "direction": "NONE", "kind": "idle", "completion_ms": None}
        meta = [meta_at(t, group="idle", path=rec["source_path"]) for t in (1590, 1640, 1690)]
        row = nr.clip_row(rec, meta, [True, False, False])
        self.assertEqual((row["kind"], row["available"], row["selected"]), ("idle", {"idle": 3, "other": 0}, {"idle": 1, "other": 0}))

    def test_in_progress_share(self):
        t = {b: {"available": 0, "selected": 0} for b in nr.ALL_BUCKETS}
        t["pre_0_300"] = {"available": 30, "selected": 3}
        t["pre_300_600"] = {"available": 30, "selected": 1}
        t["pre_earlier"] = {"available": 40, "selected": 6}
        s = nr.in_progress_share(t)
        self.assertEqual((s["in_progress_available"], s["in_progress_selected"]), (100, 10))
        self.assertAlmostEqual(s["share_available_last300"], .3)
        self.assertAlmostEqual(s["share_selected_last300"], .3)
        self.assertAlmostEqual(s["share_available_last600"], .6)
        self.assertAlmostEqual(s["share_selected_last600"], .4)


class TrainingOnlyGuard(unittest.TestCase):
    def test_clean_lists_pass(self):
        nr.assert_training_only(["a", "b"], {"c"}, {"d"})

    def test_validation_source_in_training_fails(self):
        with self.assertRaises(AssertionError):
            nr.assert_training_only(["a", "b"], {"b"}, {"d"})

    def test_eval_source_in_training_fails(self):
        with self.assertRaises(AssertionError):
            nr.assert_training_only(["a", "d"], {"c"}, {"d"})

    def test_duplicate_training_source_fails(self):
        with self.assertRaises(AssertionError):
            nr.assert_training_only(["a", "a"], set(), set())


class CountingRule(unittest.TestCase):
    def test_unique_view_counts_a_clip_once_across_folds(self):
        def row(path, picked):
            return {"source_path": path, "session": "P1", "direction": "UP", "kind": "direction", "completion_ms": 2000,
                    "available": {"pre_0_300": 6, "pre_300_600": 6, "pre_earlier": 6, "post": 6},
                    "selected": {"pre_0_300": picked, "pre_300_600": 0, "pre_earlier": 0, "post": 0}}
        folds = [{"fold": 0, "rows": [row("a", 0), row("b", 1)]}, {"fold": 1, "rows": [row("a", 0), row("b", 0)]},
                 {"fold": 2, "rows": [row("a", 0)]}]
        per_clip = nr.per_clip_across_folds(folds)
        self.assertEqual(set(per_clip), {"a", "b"})                    # 관측 5개, 고유 원본 2개
        summary = nr.unique_clip_summary(per_clip)
        self.assertEqual(summary["unique_direction_clips"], 2)
        self.assertEqual((summary["clips_zero_picks_in_every_training_fold"], summary["clips_zero_picks_in_at_least_one_training_fold"]), (1, 2))


class RealFolds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.by_path = v2.load_records()
        cls.report = nr.build_report()                                 # 25개 fold 전부(config 불일치면 여기서 실패한다)

    def test_all_25_folds_match_config_and_sums(self):
        self.assertEqual(self.report["config_match"]["folds_checked"], 25)
        self.assertTrue(self.report["config_match"]["all_match"])
        self.assertEqual(Counter(f["split"] for f in self.report["folds"]), {"S-P5": 4, "C": 5, "S-P1": 4, "S-P2": 4, "S-P3": 4, "S-P4": 4})

    def test_selection_reproduces_config_counts_for_one_fold(self):
        split = v2.load_split("S-P5")
        fold = nr.reproduce_fold(self.by_path, split, 0)
        config = nr.load_config("S-P5")
        self.assertTrue(nr.check_against_config(fold, config))
        self.assertEqual(fold["windows_selected"], config["folds"][0]["train_windows_selected"])
        self.assertTrue(nr.check_bucket_sums(fold))

    def test_config_mismatch_fails_loudly(self):
        split = v2.load_split("S-P5")
        fold = nr.reproduce_fold(self.by_path, split, 0)
        config = copy.deepcopy(nr.load_config("S-P5"))
        config["folds"][0]["train_none_groups"]["in_progress"] += 1
        with self.assertRaises(AssertionError):
            nr.check_against_config(fold, config)
        config = copy.deepcopy(nr.load_config("S-P5"))
        config["folds"][0]["train_windows_selected"][0] += 1
        with self.assertRaises(AssertionError):
            nr.check_against_config(fold, config)

    def test_rows_never_contain_validation_or_eval_sources(self):
        for name in ("S-P5", "C"):
            split = v2.load_split(name)
            for k in (0, split["cv"]["n_folds"] - 1):
                fold = nr.reproduce_fold(self.by_path, split, k)
                val, ev = set(split["cv"]["folds"][k]["validation_sources"]), set(split["eval_sources"])
                used = {r["source_path"] for r in fold["rows"]} | {p for keys in fold["selected_keys"].values() for p, _ in keys}
                self.assertFalse(used & val)
                self.assertFalse(used & ev)
                self.assertEqual(used - {r["source_path"] for r in fold["rows"]}, set())
                with self.assertRaises(AssertionError):                 # 검증 원본을 주입하면 검사가 실패한다
                    nr.assert_training_only(fold["train_paths"] + [sorted(val)[0]], val, ev)
                with self.assertRaises(AssertionError):
                    nr.assert_training_only(fold["train_paths"] + [sorted(ev)[0]], val, ev)

    def test_reproduction_is_deterministic(self):
        split = v2.load_split("C")
        a = nr.reproduce_fold(self.by_path, split, 1)
        b = nr.reproduce_fold(self.by_path, split, 1)
        self.assertEqual(a["rows"], b["rows"])
        self.assertEqual({k: sorted(v) for k, v in a["selected_keys"].items()}, {k: sorted(v) for k, v in b["selected_keys"].items()})
        again = nr.build_report(splits=("S-P5",), fold_limit=1)
        self.assertEqual(again["folds"][0], self.report["folds"][0])

    def test_unique_view_never_exceeds_distinct_clips(self):
        distinct = self.report["distinct_direction_clips_in_any_training"]
        self.assertLessEqual(distinct, sum(1 for r in self.data["records"] if r["completion_ms"] is not None))
        for name, view in self.report["splits"].items():
            split = v2.load_split(name)
            directional_train = sum(self.by_path[p]["completion_ms"] is not None for p in split["train_sources"])
            u, fo = view["unique_clips"], view["fold_observations"]
            self.assertEqual(u["unique_direction_clips"], directional_train)
            self.assertLessEqual(u["unique_direction_clips"], distinct)
            self.assertGreater(fo["n_fold_observations_direction_clips"], u["unique_direction_clips"])      # 같은 원본이 되풀이된다
            self.assertLessEqual(u["clips_zero_picks_in_every_training_fold"], u["clips_zero_picks_in_at_least_one_training_fold"])
            self.assertLessEqual(u["clips_zero_picks_in_at_least_one_training_fold"], u["unique_direction_clips"])
            self.assertLessEqual(fo["zero_picks_in_0_300"]["observations"], fo["n_fold_observations_direction_clips"])
            for b in nr.ALL_BUCKETS:
                self.assertLessEqual(fo["tally"][b]["selected"], fo["tally"][b]["available"])
                self.assertLessEqual(u["windows_selected_in_any_fold_unique"][b], u["windows_available_unique"][b])

    def test_session_split_has_no_held_out_session_in_training(self):
        for k, f in enumerate(f for f in self.report["folds"] if f["split"] == "S-P5"):
            self.assertEqual(f["held_out_session"], v2.load_split("S-P5")["cv"]["folds"][k]["held_out_session"])
        clips = self.report["clips"]
        for p, c in clips.items():
            self.assertNotIn("S-" + c["session"], c["by_split"])                      # S-Px 분할의 학습에는 Px 원본이 없다

    def test_markdown_mentions_counting_rule_and_no_causal_claim(self):
        md = nr.render_markdown(self.report)
        self.assertIn("독립", md)
        self.assertIn("원인을 주장하지 않는다", md)
        self.assertNotIn("\r", md)

    def test_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            targets = nr.write_outputs(self.report, d)
            self.assertTrue(all(t.exists() for t in targets))
            before = [t.read_bytes() for t in targets]
            with self.assertRaises(FileExistsError):
                nr.write_outputs(self.report, d)
            self.assertEqual(before, [t.read_bytes() for t in targets])
            self.assertNotIn(b"\r\n", before[0])
        with tempfile.TemporaryDirectory() as d:                                   # 둘 중 하나만 있어도 아무것도 쓰지 않는다
            (Path(d) / nr.OUT_MD).write_bytes(b"keep")
            with self.assertRaises(FileExistsError):
                nr.write_outputs(self.report, d)
            self.assertFalse((Path(d) / nr.OUT_JSON).exists())
            self.assertEqual((Path(d) / nr.OUT_MD).read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
