# 명령 아닌 움직임(other) 오발행 분석 계획

작성: 2026-10-30. 상태: **계획만, 미실행.** 실행 기록은 `docs/진행기록.md`와 `docs/experiments/ble-v2/return-label-01/README.md`에 남긴다. 남은 일 목록: `docs/TODO.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**목표:** 기준 모델(newtcnrotwarpnoacc)이 명령이 아닌 손 움직임에서 왜, 어떤 모양으로 명령을 잘못 내는지 밝히고, 줄일 방법의 후보를 근거와 함께 정한다.

**접근:** 학습하지 않는다. zoon_computer에 이미 있는 결과(gzip)·판정 점수(`*-scores.npz`)·원시 클립만 쓴다. 분석 도구는 저장소에 추적되는 파일 하나(`ml/v2_background.py`)와 테스트로 만든다. 학습이 필요한 해결책은 이 분석 결과를 보고 별도 계획으로 쓴다.

**기술:** Python 3.12, NumPy, `ml/.venv`, unittest. 판정 점수 파일이 zoon_computer(`C:\Users\zoonc\Desktop\RingPilot`)의 `ml/runs/`(깃 제외)에만 있으므로 3·5단계는 zoon_computer에서 한다.

## 출발점(측정된 사실, 2026-10-30)

- 기준 결과: tag `noacc-zoon-pc-20261029`, 분할별 선택 E(S-P1 60, S-P2 60, S-P3 40, S-P4 60, S-P5 60), 채점 `extreme_window`, 규칙 R0.
- S 다섯 분할 검증에서 배경 클립의 오발행: **idle(가만히 10 s) 300회 평가 0건, other(명령 아닌 움직임 10 s) 500회 평가 101건**(클립당 0.202건, 계속 이런 움직임을 한다고 치면 시간당 약 73회 환산). 정검출 97.11%보다 실제 사용에서 더 큰 위험일 수 있다.
- other 클립: 세션마다 5개, 모두 25개(P1 앉은 자세, P2·P3 누워서 바른 자세, P4 돌아누워 팔 꺾어 올린 자세, P5 돌아누워 팔 바른 자세). 한 S 분할은 검증 세션 4개의 other 20개를 seed 5개로 평가해 100회, 다섯 분할 합 500회다.
- 참고: 연속 3회 규칙 R4는 배경 오발행(idle+other 평균)을 0.135 → 0.050으로 줄였지만 정검출이 −2.2%p였다. 정지 평균을 뺀 가속도 조건(accsub)은 0.135 → 0.067이었지만 정검출 기준 미달로 미채택이었다.
- 한계: other 클립은 일부러 헷갈리는 움직임을 모은 최악에 가까운 자료다. 시간당 환산값은 실제 일상의 오발행 수가 아니다(실제 값은 Task 8 일상 녹화로 잰다).

## 알고 싶은 것(질문)

1. 오발행이 몇몇 클립·세션·자세에 몰려 있나, 고르게 퍼져 있나?
2. 어느 방향으로 많이 나가나? 클립 안 어느 시점인가?
3. 오발행 순간의 점수는 짧게 솟나(연속 2회), 길게 유지되나?
4. 오발행이 난 움직임은 제스처와 얼마나 닮았나(주축 회전 세기·누적 각도)? 약한 제스처 수준인가, 작은 움직임인가?
5. 발행 규칙(R0~R5)별로 other 오발행과 정검출이 어떻게 교환되나?
6. accsub에서 other 오발행이 줄어든 클립은 어떤 것인가(가속도가 도운 경우)?

## 결과를 읽는 방법(미리 정함)

- **몰림:** 오발행 상위 5개 클립이 전체의 60% 이상이면 "특정 움직임 문제"로 보고, 그 클립의 움직임을 기록·설명한다. 아니면 "모델 전반의 문제"로 본다.
- **닮음 정도:** 오발행 직전 0.8 s의 주축 자이로 최대 세기를 발행 방향의 제스처 중앙값(UP 457, DOWN 444, LEFT 227, RIGHT 202 dps)과 비교한다. 0.6배 이상 = "제스처 수준", 0.3~0.6배 = "약한 제스처 수준"(2026-10-28 약한 동작 기준과 같은 0.6배), 0.3배 미만 = "작은 움직임"으로 나눈다.
  - "제스처 수준"이 많으면 모델보다 **사용 규칙**(어떤 움직임을 명령으로 볼지)의 문제다. 제품 결정이 필요하다.
  - "작은 움직임"이 많으면 **모델 문제**다. other 같은 움직임을 NONE으로 더 학습하는 후보를 세운다.
- **규칙 교환:** 규칙마다 (S 평균 정검출, other 클립당 오발행)을 표로 낸다. 정검출 기준(R0 대비 −0.3%p 이내)을 지키면서 other 오발행을 절반 이하로 줄이는 규칙이 있으면 Task 8 시험 대상 후보로 올린다.

## Task 1: 분석 도구와 테스트(약 15분)

**Files:**
- Create: `ml/v2_background.py`
- Test: `ml/test_v2_background.py`
- Create(실행 결과): `docs/experiments/ble-v2/return-label-01/background/noacc-zoon-pc-20261029.json`

**Interfaces:**
- Consumes: `v2_return.OUT`, `v2_return.is_gesture`, `v2_return.load`, `v2.read_sensor`, `v2.SEEDS`, `v2.CLASSES`, `v2.AXES`
- Produces: `background_events(tag, label, epochs) -> (rows, evals)`, `motion_features(raw, t_ms) -> dict`, `likeness(peak_dps, issued) -> str`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
"""배경 오발행 분석 점검. 학습하지 않는다."""
import unittest

import numpy as np

import v2_background as bg

E = {"S-P1": 60, "S-P2": 60, "S-P3": 40, "S-P4": 60, "S-P5": 60}


class EventTests(unittest.TestCase):
    def test_counts_match_2026_10_30_hand_count(self):
        rows, evals = bg.background_events("noacc-zoon-pc-20261029", "newtcnrotwarpnoacc", E)
        other = [r for r in rows if bg.kind_of(r["source_path"]) == "other"]
        self.assertEqual(len(other), 101)
        self.assertEqual(sum(n for p, n in evals.items() if bg.kind_of(p) == "other"), 500)
        self.assertEqual(sum(n for p, n in evals.items() if bg.kind_of(p) == "idle"), 300)
        self.assertFalse([r for r in rows if bg.kind_of(r["source_path"]) == "idle"])


class FeatureTests(unittest.TestCase):
    def test_motion_features_find_peak_before_issue(self):
        raw = np.zeros((1000, 6))
        raw[:, 3:6] += (5.0, -3.0, 1.0)            # 자이로 치우침(클립 중앙값으로 뺀다)
        raw[400:420, 4] += 300.0                   # gyrY 회전(4.0~4.2 s)
        f = bg.motion_features(raw, 4500)          # 4.5 s 발행 → 앞 0.8 s(3.7~4.5 s)를 본다
        self.assertEqual(f["dominant_axis"], "gyrY")
        self.assertAlmostEqual(f["peak_dps"], 300.0, places=6)
        self.assertAlmostEqual(f["angle_deg"], 60.0, places=6)    # 300 dps × 0.2 s

    def test_likeness_uses_direction_median(self):
        self.assertEqual(bg.likeness(300, "UP"), "제스처 수준")      # 457 × 0.6 = 274
        self.assertEqual(bg.likeness(200, "UP"), "약한 제스처 수준")
        self.assertEqual(bg.likeness(50, "RIGHT"), "작은 움직임")     # 202 × 0.3 = 61
```

- [ ] **Step 2: 실패를 확인한다**

Run: `ml/.venv/Scripts/python.exe -m unittest discover -s ml -p "test_v2_background.py" -v`
Expected: `ModuleNotFoundError: No module named 'v2_background'`

- [ ] **Step 3: `ml/v2_background.py`를 만든다**

```python
"""명령 아닌 움직임(other)·가만히(idle) 클립의 오발행 분석(학습하지 않는다).

계획: docs/superpowers/plans/2026-10-30-v2-background-false-analysis.md
사용: ml/.venv/Scripts/python.exe ml/v2_background.py --tag noacc-zoon-pc-20261029 --label newtcnrotwarpnoacc
"""
import argparse
import gzip
import json
from collections import Counter

import numpy as np

import v2
import v2_return as vr

SCORING = "extreme_window"
SELECTED_E = {"S-P1": 60, "S-P2": 60, "S-P3": 40, "S-P4": 60, "S-P5": 60}   # noacc-zoon-pc-20261029 선택 E
GESTURE_MEDIAN_DPS = {"UP": 457, "DOWN": 444, "LEFT": 227, "RIGHT": 202}   # 2026-10-28 약한 동작 기준의 방향별 중앙값
WINDOW_MS = 800           # 오발행 시각 앞에서 움직임 특징을 보는 구간


def kind_of(source_path):
    return source_path.rsplit("/", 1)[-1].split(".")[0]


def background_events(tag, label, epochs):
    """S 분할 검증에서 배경 클립의 발행(모두 오발행)과 클립별 평가 횟수를 모은다."""
    rows, evals = [], Counter()
    for sp, e in epochs.items():
        for s in v2.SEEDS:
            with gzip.open(vr.OUT / "results" / tag / f"{label}-{sp}" / f"seed-{s}.json.gz", "rt", encoding="utf-8") as f:
                res = json.load(f)
            for fold in res["folds"]:
                for p in fold["per_epoch"][str(e)][SCORING]["per_source"]:
                    if vr.is_gesture(p["source_path"]):
                        continue
                    evals[p["source_path"]] += 1
                    for t, c, _ in p["events"]:
                        rows.append({"split": sp, "seed": s, "held_out": fold["held_out_session"],
                                     "source_path": p["source_path"], "t_ms": t, "issued": v2.CLASSES[c]})
    return rows, evals


def motion_features(raw, t_ms, window_ms=WINDOW_MS):
    """발행 시각 t 앞 window_ms 구간에서 주축 자이로(클립 중앙값을 뺀 값)의 최대 세기와 누적 각도."""
    i1 = int(t_ms) // 10 + 1
    g = raw[max(0, i1 - window_ms // 10):i1, 3:6] - np.median(raw[:, 3:6], axis=0)
    axis = int(np.argmax(np.abs(g).max(axis=0)))
    return {"dominant_axis": v2.AXES[3 + axis], "peak_dps": float(np.abs(g[:, axis]).max()),
            "angle_deg": float(np.abs(np.cumsum(g[:, axis]) * vr.SAMPLE_S).max())}


def likeness(peak_dps, issued):
    ratio = peak_dps / GESTURE_MEDIAN_DPS[issued]
    return "제스처 수준" if ratio >= 0.6 else "약한 제스처 수준" if ratio >= 0.3 else "작은 움직임"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--label", required=True)
    a = ap.parse_args()
    target = vr.OUT / "background" / f"{a.tag}.json"
    if target.exists():
        raise FileExistsError(f"{target}가 이미 있다")
    rows, evals = background_events(a.tag, a.label, SELECTED_E)
    raws = {p: v2.read_sensor(vr.ROOT / p)[1] for p in {r["source_path"] for r in rows}}
    for r in rows:
        r.update(motion_features(raws[r["source_path"]], r["t_ms"]))
        r["likeness"] = likeness(r["peak_dps"], r["issued"])
    per_clip = Counter(r["source_path"] for r in rows)
    top5 = sum(n for _, n in per_clip.most_common(5))
    out = {"tag": a.tag, "label": a.label, "epochs": SELECTED_E, "scoring": SCORING, "created_kst": v2.now(),
           "evaluations": {k: sum(n for p, n in evals.items() if kind_of(p) == k) for k in ("idle", "other")},
           "false_issues": {k: sum(1 for r in rows if kind_of(r["source_path"]) == k) for k in ("idle", "other")},
           "top5_clip_share": top5 / len(rows) if rows else None,
           "per_clip": {p: {"false": per_clip[p], "evaluations": evals[p]} for p in sorted(evals)},
           "by_issued": dict(Counter(r["issued"] for r in rows)),
           "by_likeness": dict(Counter(r["likeness"] for r in rows)),
           "by_held_out": dict(Counter(r["held_out"] for r in rows)),
           "events": rows}
    v2.dump(target, out)
    for k in ("evaluations", "false_issues", "top5_clip_share", "by_issued", "by_likeness", "by_held_out"):
        print(k, out[k])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 테스트와 기존 테스트를 확인한다**

Run: `ml/.venv/Scripts/python.exe -m unittest discover -s ml -p "test_*.py"`
Expected: 기존 91개 + 3개 = 94개 통과, 1개 묶음 건너뜀

## Task 2: 기본 분석 실행(질문 1·2·4, 약 5분)

- [ ] Run: `ml/.venv/Scripts/python.exe ml/v2_background.py --tag noacc-zoon-pc-20261029 --label newtcnrotwarpnoacc`
- [ ] Expected: `false_issues` other 101·idle 0, `evaluations` other 500·idle 300.
- [ ] 결과에서 읽을 것: 상위 5개 클립 비중(60% 이상이면 특정 움직임 문제), 방향별·세션별 분포, 닮음 정도 3분류 비율. 상위 클립 3개는 오발행 시각 앞뒤 2 s 자이로 그림을 그려(`ml/runs/figures/`, 깃 제외) 어떤 움직임인지 설명을 붙인다.

## Task 3: 점수 모양(질문 3, 약 10분, zoon_computer에서)

- [ ] `ml/runs/figures/score_shape.py`(2026-10-29, 깃 제외)를 복사해 배경 클립의 발행에도 적용한다. 같은 방식으로 발행 시점을 포함한 연속 충족 판정 수와 최고 점수를 센다.
- [ ] 비교 대상: 정답 발행(중앙값 4회, 2회뿐 2.8%), 돌아오는 동작 중 반대 방향(2회뿐 83%).
- [ ] 결과는 Task 2 결과 JSON의 이벤트별 `run`·`peak`로 더하거나 `background/score-shape-noacc-zoon-pc-20261029.json`으로 따로 둔다.

## Task 4: 규칙별 교환 관계(질문 5, 약 10분, zoon_computer에서)

- [ ] `ml/v2_rules.py`의 `rescore()`로 R0~R5를 다시 채점하고(이미 있는 함수), 배경 클립을 idle·other로 나눠 클립당 오발행을 센다. S 평균 정검출은 `rules-…json`, `rules2-…json`에 이미 있다.
- [ ] 표: 규칙 | S 평균 정검출 | other 클립당 오발행 | idle 클립당 오발행 | 무발행. 정검출 −0.3%p 이내에서 other 오발행을 절반 이하로 줄이는 규칙이 있는지 본다.

## Task 5: accsub와 비교(질문 6, 약 5분)

- [ ] Task 2를 `--tag zoon_computer-accsub-20261029 --label newtcnrotwarpaccsub`로 돌린다(선택 E는 C 40·S-P1 60·S-P2 60·S-P3 20·S-P4 40·S-P5 30이므로 `SELECTED_E`를 인자로 받게 고쳐서).
- [ ] 클립별로 noacc → accsub 오발행 변화를 보고, 줄어든 클립의 움직임 특징을 적는다. 가속도 정보가 명령 아닌 움직임을 거르는 데 도움이 되는지에 대한 근거가 된다(채택된 결정은 아님).

## Task 6: 기록과 다음 후보 정하기(약 10분)

- [ ] README에 "명령 아닌 움직임 오발행 분석" 절: 질문 1~6의 답, 표, 그림 경로.
- [ ] `docs/진행기록.md`에 날짜·목적·변경·결과·한계·다음.
- [ ] `docs/TODO.md` 갱신: 결과에 따라 다음 중 하나를 후보로 올린다(이 계획에서는 실행하지 않는다).
  - "제스처 수준" 위주 → 사용 규칙 결정(어느 세기부터 명령으로 볼지, 약한 동작 결정과 함께) — 사용자 결정
  - "작은 움직임" 위주 → other 같은 움직임 창을 NONE으로 더 학습하는 조건(판단 기준은 학습 전 고정)
  - 규칙으로 충분히 줄면 → Task 8 시험 대상 규칙 추가
  - 몇 클립에 몰림 → 그 움직임을 일상 녹화(Task 8 블록 D)에서 따로 확인

## 합계 시간

Task 1~2·4·6만: 약 40분. Task 3·5 포함: 약 1시간.
