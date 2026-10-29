"""발행 규칙 변형 점검. 학습하지 않는다."""
import unittest

import numpy as np

import v2
import v2_return as vr
import v2_rules as rules


def confident(cls, p=0.95):
    s = np.full(5, (1 - p) / 4)
    s[cls] = p
    return s


SEQ = [1, 1, 0, 0, 2, 2]      # UP 2회 → 발행(50 ms), NONE 2회 → 재무장, DOWN 2회 → 250 ms에 발행


class RuleTests(unittest.TestCase):
    def test_default_matches_protocol_rule(self):
        rng = np.random.default_rng(0)
        for _ in range(50):
            raw = rng.random((80, 5)) ** 4          # 가끔 한 클래스가 크게 튀는 점수
            scores = raw / raw.sum(axis=1, keepdims=True)
            times = np.arange(80) * 50
            self.assertEqual(rules.issue_events_rule(times, scores), v2.issue_events(times, scores))

    def test_refractory_blocks_quick_second_issue(self):
        times, scores = np.arange(len(SEQ)) * 50, np.array([confident(c) for c in SEQ])
        self.assertEqual([e["class_index"] for e in v2.issue_events(times, scores)], [1, 2])
        self.assertEqual([e["class_index"] for e in rules.issue_events_rule(times, scores, refractory_ms=500)], [1])
        self.assertEqual([e["class_index"] for e in rules.issue_events_rule(times, scores, refractory_ms=200)], [1, 2])

    def test_rearm_needs_more_none(self):
        times, scores = np.arange(len(SEQ)) * 50, np.array([confident(c) for c in SEQ])
        self.assertEqual([e["class_index"] for e in rules.issue_events_rule(times, scores, rearm=4)], [1])

    def test_consecutive_three_drops_two_decision_blips(self):
        # 2회만 솟는 DOWN은 연속 3회 규칙에서 발행되지 않고, 3회 이어지는 UP은 세 번째 판정(100 ms)에 발행된다
        seq = [2, 2, 0, 0, 1, 1, 1]
        times, scores = np.arange(len(seq)) * 50, np.array([confident(c) for c in seq])
        self.assertEqual([(e["timestamp_ms"], e["class_index"]) for e in v2.issue_events(times, scores)], [(50, 2), (250, 1)])
        self.assertEqual([(e["timestamp_ms"], e["class_index"]) for e in rules.issue_events_rule(times, scores, consecutive=3)],
                         [(300, 1)])


class ScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.by_path, cls.nb = vr.load()
        cls.split = v2.load_split("S-P5")

    def test_val_chunk_times_match_training_windows(self):
        chunks = rules.val_chunks(self.split, 0, self.by_path)
        val = set(self.split["cv"]["folds"][0]["validation_sources"])
        recs = [self.by_path[p] for p in self.split["train_sources"] if p in val]
        made = v2.make_chunks(recs, np.zeros(6), np.ones(6))
        self.assertEqual([c[0]["source_path"] for c in chunks], [c[0]["source_path"] for c in made])
        self.assertEqual([[m["timestamp_ms"] for m in c[3]] for c in chunks], [[m["timestamp_ms"] for m in c[3]] for c in made])

    def test_score_with_protocol_rule_matches_v2_return_score(self):
        chunks = rules.val_chunks(self.split, 0, self.by_path)
        n = sum(len(c[2]) for c in chunks)
        raw = np.random.default_rng(1).random((n, 5)) ** 6
        scores = (raw / raw.sum(axis=1, keepdims=True)).astype(np.float32)
        _, expected = vr.score(chunks, scores, self.by_path, self.nb, rules.SCORING)
        self.assertEqual(rules.score_with(chunks, scores, self.by_path, self.nb, v2.issue_events), expected)
