# V2 다음 단계 계획: 기준 조건 확정 → 다른 방향 발행 → 연속 조작 확인 → 배포 준비

작성: 2026-10-29. 기준 커밋 `06dd201`. **계획 문서이며 실행 기록은 `docs/experiments/ble-v2/return-label-01/README.md`와 `docs/진행기록.md`에 남긴다.**

개정(2026-10-29, 2차): 외부 검토와 사용자 결정을 반영했다. ① Task 6(모델 저장)을 긴 학습보다 먼저 했다. ② E100 연장(Task 2)은 보류하고, Task 3에 필요한 점수 파일은 기존 선택 E(E60 이하)까지만 이 PC에서 다시 학습해 얻는다. ③ 불응기 등 발행 규칙은 재채점으로 후보만 고르고, **채택은 연속 조작 녹화(Task 8) 확인 뒤**에 한다. ④ E 선택 규칙과 조건 채택 기준을 나눠 적었다. ⑤ 보드 추론 시간은 지금 모델로 일찍 따로 잰다(Task 7a). ⑥ Task 9는 새 자료 평가로 바꿨다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**목표:** 가속도 채널 제외 조건(newtcnrotwarpnoacc)을 기준으로 확정하고, 그 부작용인 다른 방향 발행을 줄인 뒤, 보드에 올릴 모델(가중치·전처리 값)을 준비한다.

**접근:** 지금까지처럼 한 번에 요인 하나만 바꾼다. 재학습이 필요 없는 진단·재채점을 먼저 하고, 발행 규칙은 실제 연속 조작에서 확인한 뒤 채택한다. 보드 추론 시간은 학습 결과를 기다리지 않고 지금 모델로 먼저 잰다. 튜닝과 보드 이식 본 작업은 이 계획의 결과를 보고 별도 계획으로 쓴다.

**기술:** Python 3.12, TensorFlow 2.21(`ml/.venv`), unittest. 보드는 XIAO nRF52840 Sense(IMU LSM6DS3TR-C), Arduino.

## 전역 제약

- 데이터(334개)·분할 6개·라벨·채점(`extreme_window` = [끝점, r+300 ms])·E 선택 규칙(seed 평균 selection_score 최대, 같으면 작은 E)은 그대로 둔다. 각 Task가 바꾸는 요인만 예외다.
- **E 선택과 조건 채택을 나눈다.** E는 지금처럼 `selection_score`(= (정답 − 정답 외 발행) / 방향 클립 수, seed 평균 최대, 같으면 작은 E)로 고른다. 이 규칙은 프로토콜부터 고정돼 있어 이전 결과와 비교할 수 있고, 중복·조기·늦은 발행도 감점한다. **조건·규칙 채택**은 그렇게 고른 E에서 정검출(`clean_success_rate`) 우선으로 한다. 배경 오발행은 정검출이 잡음 범위(약 0.5%p) 안에서 비슷할 때만 쓴다(2026-10-28 사용자 결정). 두 기준이 다른 E를 고른 예: noacc S-P1 선택 E40 96.69%, 정검출 최대 E60 96.78%(나머지 분할은 같거나 동점).
- 비교는 같은 PC·같은 venv에서 한다. CPU가 다르면 같은 코드·seed라도 E5 이후 결과가 달라진다(README 재현성 절).
- PC 이름(README "실행 PC 이름" 절): 이 계획을 실행하는 `C:\Users\zoonc\Desktop\RingPilot`(i5-13600KF, 논리 20개)은 **zoon_computer**다. 문서에서는 "이 PC" 대신 이 이름을 쓰고, 새 실행 tag에 `zoon_computer`를 넣는다. 0.1절의 noacc 결과는 user 경로 PC(`C:\Users\user\Desktop\prj\watch`)에서 나왔다.
- 기존 결과·요약·로그를 덮어쓰지 않는다. 새 실행은 새 `--tag`로 한다.
- 각 분할의 평가용 세션(`eval_sources`)은 그 분할 실행 안에서만 분리돼 있다. 334개 모두 다른 분할의 교차검증에 이미 쓰였으므로(S-P1 66/66 … S-P5 65/65, 2026-10-29 확인) 독립 최종 평가 자료가 아니다(Task 9).
- 채택 기준은 결과를 보기 전에 이 문서에 고정한다.
- 테스트: 저장소 루트에서 `ml/.venv/Scripts/python.exe -m unittest discover -s ml -p "test_*.py"`. 계획 시작 때 73개 통과, 1개 묶음 건너뜀(진행기록 기준).
- 학습 실행 중에는 `ml/v2.py`·`ml/v2_return.py`·`ml/model.py`를 고치지 않는다. `run-all`은 작업마다 새 프로세스를 띄우므로, 실행 중에 고치면 뒤쪽 작업이 바뀐 코드로 돈다.
- 학습 실행 중에는 전체 테스트·모델 재생처럼 TensorFlow를 쓰는 무거운 작업을 같이 돌리지 않는다. 2026-10-29 accsub 실행에서 병렬 6개와 함께 돌렸다가 작업 6개가 메모리 부족(ResourceExhaustedError)으로 실패했다.
- 명령은 저장소 루트(`C:\Users\zoonc\Desktop\RingPilot`)에서 실행한다. 다른 폴더에서 실행해 상대 경로를 못 찾은 적이 있다(2026-10-29).
- 커밋은 사용자 확인 후에 한다. 의미 있는 단계마다 `docs/진행기록.md`에 날짜·목적·변경·이유·검증·문제·다음을 남긴다(AGENTS.md).

## 0. 출발점(측정된 사실)

### 0.1 newtcnrotwarp → newtcnrotwarpnoacc (다른 PC `C:\Users\user\Desktop\prj\watch`, seed 5, 선택 E)

| 분할 | newtcnrotwarp | noacc | 무발행 | 다른 방향 발행 | 약한 동작 | 배경 오발행 |
|---|---|---|---|---|---|---|
| C | 98.63% (E30) | 98.29% (E60) | 13 → 13 | 3 → 7 | 91.4 → 92.9% | 0.180 → 0.167 |
| S-P1 | 92.20% (E30) | 96.69% (E40) | 87 → 34 | 5 → 5 | 75.0 → 100% | 0.100 → 0.150 |
| S-P2 | 93.68% (E30) | 97.18% (E60) | 62 → 21 | 12 → 12 | 58.3 → 81.7% | 0.119 → 0.087 |
| S-P3 | 88.94% (E20) | 97.45% (E60) | 123 → 20 | 7 → 10 | 72.3 → 89.2% | 0.212 → 0.181 |
| S-P4 | 88.21% (E20) | 97.26% (E60) | 133 → 24 | 5 → 8 | 64.3 → 88.6% | 0.181 → 0.188 |
| S-P5 | 96.88% (E30) | 96.71% (E60) | 29 → 19 | 8 → 20 | 75.4 → 92.3% | 0.194 → 0.119 |

- noacc는 여섯 분할 중 다섯에서 E 후보의 끝값인 E60이 선택됐다. 후보는 `v2.EPOCH_CANDIDATES = (1, 5, 10, 20, 30, 40, 60)`이다. 더 학습하면 나아질 여지가 있다.
- 이 PC(`C:\Users\zoonc\Desktop\RingPilot`)의 `ml/runs/`에는 noacc 결과와 점수 파일(`*-scores.npz`)이 없다. 저장소에는 gzip 결과(발행 기록)만 있다.

### 0.2 S-P5 다른 방향 발행 20건의 선행 진단(2026-10-29, 재학습 없음)

저장소의 noacc S-P5 결과(E60, seed 5개 합)에서 방향 클립의 정답과 다른 방향 발행을 모두 모았다.

| 묶음 | 건수 | 내용 |
|---|---|---|
| 정답 발행 **뒤** 반대 방향 재발행 | 7 | 모두 `late_unmatched`, r 뒤 340~460 ms. UP→DOWN 5건(P4 세션 `raw_up.5·8·10·14`), RIGHT→LEFT 2건(P4 `raw_right.15`) |
| 정답 없이 다른 방향(구간 안) | 11 | `wrong_direction`. 반대 방향 4건(P1 `raw_down.16` DOWN→UP이 seed 3개에서 반복, P4 `raw_up.11`), 좌우↔상하 7건 |
| 조기 발행 | 2 | P3 `raw_right.6` RIGHT→LEFT(newtcnrotwarp에도 있던 클립) |

- README의 "위↔아래 9건"은 이 중 UP→DOWN 6건(재발행 5 + 구간 안 1)과 DOWN→UP 3건이다. **9건 중 5건은 정답을 낸 뒤 반대 방향으로 한 번 더 나간 것이다.** 정답이 나간 뒤 확실한 NONE 2회(100 ms)로 너무 빨리 재무장해서 생긴 것으로 보인다(추정, Task 3에서 확인).
- newtcnrotwarp(E30)는 같은 집계로 8건이었고, 정답 뒤 재발행은 0건이었다.

### 0.3 보드 자원 추정(2026-10-29 개정, 계산값이며 보드 실측 아님)

- 대상: XIAO nRF52840 Sense(Cortex-M4F 64 MHz, RAM 256 KB, Flash 1 MB), 코어 Seeed nRF52 Boards non-mbed 1.1.13(Bluefruit). `imu_ble_stream` 컴파일 기준 앱이 쓸 수 있는 RAM 237,568 B 중 전역 변수 18,676 B, Flash 811,008 B 중 125,692 B를 쓴다(진행기록).
- 메모리: noacc TCN(4,421 파라미터)은 float32로도 가중치 17.7 KB(Flash 상수로 두면 RAM 0), 활성값과 패딩 버퍼 약 50 KB 이하로 추정되어 OOM 여유가 크다. 큰 버퍼는 `loop()` 지역 변수가 아니라 전역·static으로 둔다(FreeRTOS loop 태스크 스택이 작다).
- 시간: 160 시점 전체를 계산하면 판정 1회 675,920 MAC이고, float 단순 구현으로 약 40~85 ms라 50 ms 판정 주기를 넘길 수 있다. 모델은 마지막 시점 출력만 쓰므로(`Cropping1D`) 그 출력에 필요한 위치만 계산하면 결과는 같고 96,464 MAC(블록별 93·45·21·9·3·1 위치)으로 약 7배 줄어 float로 약 6~12 ms로 추정된다.
- 런타임: Arduino용 TFLite Micro 포트는 대부분 mbed 코어 기준이라 non-mbed 코어에서 바로 쓰기 어려울 수 있다(확인 필요). 모델이 작아 런타임 없이 C로 직접 구현하는 쪽을 1순위로 둔다.
- 결론: int8은 메모리 때문에 필요하지 않다. Task 7 실측에서 시간·전력이 부족할 때만 한다.

## 실행 순서와 의존 관계

2차 개정 순서(상태는 2026-10-29 기준):

```
Task 0 기준 조건 확정                                   [완료]
Task 1 다른 방향 발행 진단                               [완료]
Task 6 모델·전처리 값 저장 기능(Step 2~7)                 [완료, int8은 보류]
Task 3 발행 규칙 재채점                                  [완료: 네 규칙 모두 후보 기준 미달(최대 −22%). R1은 정답 뒤 재발행 11→0이라 사후에 Task 8 시험 대상으로 추가(기준 미달 판정 유지)]
  ├─ Step 0 이 PC에서 noacc 6분할 × seed 5 재학습(E60, 모델 저장) = 점수 파일 + 이 PC 기준선
  └─ 재채점으로 규칙 "후보" 선정 (채택은 Task 8 확인 뒤)
Task 8 연속 조작·배경 녹화와 온라인 영점 확인              [사용자 녹화 필요, Task 3 후보 채택의 관문]
Task 7a 지금 모델로 보드 C 추론 시간 조기 측정             [병렬 가능, Task 6 산출물 사용]
Task 4 (조건부) 학습 쪽 수정                              [첫 조건 accsub 미채택(S 평균 95.95%, 복귀 중 반대 27건). 다음 후보는 사용자 결정]
Task 5 튜닝 계획 개정 ── 별도 계획 (E100 연장(Task 2)은 여기서 함께 본다)
Task 2 E 후보 연장(E80·E100)                            [보류]
Task 7 보드 이식 본 작업 ── 별도 계획 (int8은 7a·7에서 부족할 때만)
Task 9 최종 평가 ── 설계 고정 뒤 새로 녹화한 세션으로
```

---

### Task 0: 기준 조건 확정과 실행 PC 결정

**Files:**
- Modify: `docs/experiments/ble-v2/return-label-01/README.md`(가속도 채널 제외 절의 "판단" 줄)
- Modify: `docs/진행기록.md`

- [ ] **Step 1: 사용자 결정 두 가지를 받는다**
  1. newtcnrotwarpnoacc를 기준 조건으로 채택하는가(다른 방향 발행 증가는 Task 1~4에서 다룬다).
  2. 앞으로 학습 비교를 어느 PC에서 하는가. 이 PC면 Task 2 실행이 곧 이 PC 기준선이 된다. 다른 PC(`C:\Users\user\Desktop\prj\watch`)면 Task 2·3을 그 PC에서 하고 점수 파일도 그 PC에 남는다.
- [ ] **Step 2: README의 판단 줄을 결정으로 바꾼다**

```markdown
- 결정(2026-10-29, 사용자): newtcnrotwarpnoacc를 기준 조건으로 채택한다. 다른 방향 발행 증가는 `docs/superpowers/plans/2026-10-29-v2-next-steps.md` Task 1~4에서 다룬다. 이후 비교 PC: <PC 이름·경로>.
```

- [ ] **Step 3: 진행기록에 같은 내용을 한 항목으로 남긴다**(제목 예: `## 2026-10-29 — 가속도 채널 제외 조건 채택과 다음 단계 계획`)
- [ ] **Step 4: 커밋(사용자 확인 후)**

```bash
git add docs/experiments/ble-v2/return-label-01/README.md docs/진행기록.md
git commit -m "Adopt newtcnrotwarpnoacc as the baseline condition"
```

---

### Task 1: 다른 방향 발행 진단 도구

§0.2의 손 계산을 다시 돌릴 수 있는 도구로 만들고, 여섯 분할 모두에 적용한다. 학습하지 않는다.

**Files:**
- Create: `ml/v2_wrongdir.py`
- Test: `ml/test_v2_wrongdir.py`
- Create(실행 결과): `docs/experiments/ble-v2/return-label-01/wrong-direction/<tag>-<label>-<split>-E<E>.json`

**Interfaces:**
- Consumes: `v2_return.load()`, `v2_return.rescored()`, `v2_return.OUT`, `v2_return.EXTREME_AFTER_R_MS`, `v2.read_sensor()`, `v2.SEEDS`, `v2.CLASSES`
- Produces: `phase(t, n) -> str`, `rebound_dps(n, raw) -> float`, `load_results(tag, label, split, by_path, nb) -> list[dict]`, `off_direction(results, epoch, nb) -> list[dict]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
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
```

- [ ] **Step 2: 실패를 확인한다**

Run: `ml/.venv/Scripts/python.exe -m unittest discover -s ml -p "test_v2_wrongdir.py" -v`
Expected: `ModuleNotFoundError: No module named 'v2_wrongdir'`

- [ ] **Step 3: `ml/v2_wrongdir.py`를 만든다**

```python
"""다른 방향 발행 진단(학습하지 않는다).

저장소에 올린 결과(results/<tag>/<label>-<split>/seed-*.json.gz)의 발행 기록을 동작 시점(가는 피크·끝점·복귀 피크·r)에 맞춰 나눈다.
방향 클립에서 정답과 다른 방향으로 나간 발행은 채점 종류(early·wrong_direction·late_unmatched)와 무관하게 모두 모은다.
clean_success_rate가 이 발행을 모두 실패로 세기 때문이다.

사용: ml/.venv/Scripts/python.exe ml/v2_wrongdir.py --tag noacc-20261029 --label newtcnrotwarpnoacc --split S-P5 --epoch 60
"""
import argparse
import gzip
import json
from collections import Counter

import numpy as np

import v2
import v2_return as vr

OPPOSITE = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
GYRO = {"gyrX": 3, "gyrY": 4, "gyrZ": 5}
REBOUND_MS = 400          # 복귀 피크 뒤 반동을 찾는 구간
SCORING = "extreme_window"


def phase(t, n):
    """발행 시각 t(ms)가 동작의 어느 구간인지. n은 ble-v2-return records의 한 항목."""
    if t < n["outbound_peak_ms"]:
        return "가는 피크 전"
    if t < n["extreme_ms"]:
        return "가는 피크~끝점"
    if t < n["return_peak_ms"]:
        return "끝점~복귀 피크"
    if t < n["event_ms"]:
        return "복귀 피크~r"
    if t <= n["event_ms"] + vr.EXTREME_AFTER_R_MS:
        return "r~r+300"
    return "r+300 뒤"


def rebound_dps(n, raw):
    """복귀 피크 뒤 REBOUND_MS 안에서 주축 자이로가 가는 방향 부호로 다시 튄 최대 세기(deg/s, 영점 보정 없음). 없으면 0."""
    sign = 1.0 if n["outbound_sign"] == "+" else -1.0
    i0 = n["return_peak_ms"] // 10
    seg = sign * raw[i0:i0 + REBOUND_MS // 10, GYRO[n["dominant_axis"]]]
    return float(max(seg.max(), 0.0))


def load_results(tag, label, split, by_path, nb):
    out = []
    for s in v2.SEEDS:
        path = vr.OUT / "results" / tag / f"{label}-{split}" / f"seed-{s}.json.gz"
        with gzip.open(path, "rt", encoding="utf-8") as f:
            out.append(vr.rescored(json.load(f), SCORING, by_path, nb))
    return out


def off_direction(results, epoch, nb):
    rows = []
    for res in results:
        for fold in res["folds"]:
            for p in fold["per_epoch"][str(epoch)][SCORING]["per_source"]:
                n = nb.get(p["source_path"])
                if n is None:                       # 배경 클립
                    continue
                truth = v2.CLASSES.index(n["direction"])
                correct_t = [t for t, _, kind in p["events"] if kind == "correct"]
                for t, c, kind in p["events"]:
                    if c == truth:
                        continue
                    rows.append({"seed": res["seed"], "held_out": fold["held_out_session"], "source_path": p["source_path"],
                                 "truth": n["direction"], "issued": v2.CLASSES[c], "kind": kind,
                                 "opposite": v2.CLASSES[c] == OPPOSITE[n["direction"]], "phase": phase(t, n),
                                 "t_minus_r_ms": t - n["event_ms"], "after_correct": any(ct < t for ct in correct_t),
                                 "clip_has_correct": bool(correct_t)})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--epoch", type=int, required=True)
    a = ap.parse_args()
    target = vr.OUT / "wrong-direction" / f"{a.tag}-{a.label}-{a.split}-E{a.epoch}.json"
    if target.exists():
        raise FileExistsError(f"{target}가 이미 있다")
    _, by_path, nb = vr.load()
    rows = off_direction(load_results(a.tag, a.label, a.split, by_path, nb), a.epoch, nb)
    rebound = {p: rebound_dps(n, v2.read_sensor(vr.ROOT / p)[1]) for p, n in nb.items()}
    keys = ("kind", "phase", "opposite", "after_correct", "clip_has_correct", "held_out")
    out = {"tag": a.tag, "label": a.label, "split": a.split, "epoch": a.epoch, "scoring": SCORING, "created_kst": v2.now(),
           "total": len(rows), "counts": {k: {str(v): c for v, c in Counter(r[k] for r in rows).items()} for k in keys},
           "rebound_dps": {"median_by_direction": {d: float(np.median([rebound[p] for p, n in nb.items() if n["direction"] == d]))
                                                   for d in OPPOSITE},
                           "after_correct_clips": {p: rebound[p] for p in sorted({r["source_path"] for r in rows if r["after_correct"]})}},
           "events": rows}
    v2.dump(target, out)
    print("다른 방향 발행", len(rows))
    for k in keys:
        print(f"  {k}: {out['counts'][k]}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 테스트 통과와 기존 테스트 유지를 확인한다**

Run: `ml/.venv/Scripts/python.exe -m unittest discover -s ml -p "test_*.py"`
Expected: 76개 통과(기존 73 + 3), 1개 묶음 건너뜀

- [ ] **Step 5: 여섯 분할 × 두 조건을 진단한다**(E는 각 요약의 선택 E)

| 조건 | tag | E (C, S-P1, S-P2, S-P3, S-P4, S-P5) |
|---|---|---|
| newtcnrotwarpnoacc | `noacc-20261029` | 60, 40, 60, 60, 60, 60 |
| newtcnrotwarp | `rotations-20261029` (C·S-P1~P4), `soft-20261029` (S-P5) | 30, 30, 30, 20, 20, 30 |

Run(예): `ml/.venv/Scripts/python.exe ml/v2_wrongdir.py --tag noacc-20261029 --label newtcnrotwarpnoacc --split S-P3 --epoch 60`

- [ ] **Step 6: README에 "다른 방향 발행 진단" 절을 추가한다.** 분할별 표(전체·정답 뒤·정답 없이·조기)와 판단(Task 3을 할지, Task 4가 필요한지)을 쓴다. 판단 기준(미리 고정): 여섯 분할 합에서 "정답 뒤" 발행이 noacc 증가분(62 − 40 = 22건)의 절반 이상이면 Task 3이 주 해결책이다. 아니면 Task 3 뒤에도 Task 4가 필요하다.
- [ ] **Step 7: 진행기록에 남기고 커밋(사용자 확인 후)**

```bash
git add ml/v2_wrongdir.py ml/test_v2_wrongdir.py docs/experiments/ble-v2/return-label-01/wrong-direction docs/experiments/ble-v2/return-label-01/README.md docs/진행기록.md
git commit -m "Diagnose wrong-direction issues for newtcnrotwarpnoacc across six splits"
```

---

### Task 2: 조건별 E 후보와 에폭 연장 실행 — 보류(2차 개정)

**보류 이유:** Task 3에 필요한 것은 점수 파일이고, 그것은 기존 선택 E(E60 이하)까지의 재학습(Task 3 Step 0)으로 얻는다. E80·E100 비교는 튜닝(Task 5)에서 다른 후보와 함께 본다. 아래 단계 중 `keep_awake`(대기 모드 차단)만 Task 3 Step 0 실행 전에 넣었다.

E100까지 한 번 학습하면 E≤60 스냅숏은 같은 PC의 newtcnrotwarpnoacc 결과와 같다(같은 seed·같은 섞기 순서·결정적 연산, 학습률 일정 없음). 따라서 이 한 번의 실행으로 세 가지를 얻는다: ① 실행 PC의 noacc 기준선, ② Task 3에 쓸 점수 파일, ③ E80·E100 비교.

**Files:**
- Modify: `ml/v2_return.py`(조건 표, `epochs_of`, `cmd_run`, `cmd_summarize`, `cmd_run_all`)
- Test: `ml/test_v2_epochs.py`

**Interfaces:**
- Produces: `epochs_of(label) -> tuple[int, ...]`, 조건 `newtcnrotwarpnoacc100`, 요약 JSON은 결과에 기록된 `epochs`로 E를 고른다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
"""조건별 E 후보 점검. 학습하지 않는다."""
import unittest

import v2
import v2_return as vr


class EpochCandidateTests(unittest.TestCase):
    def test_existing_conditions_keep_protocol_epochs(self):
        for label in ("newtcnrotwarp", "newtcnrotwarpnoacc"):
            self.assertEqual(vr.epochs_of(label), tuple(v2.EPOCH_CANDIDATES))

    def test_long_condition_only_adds_epochs(self):
        self.assertEqual(vr.epochs_of("newtcnrotwarpnoacc100"), (*v2.EPOCH_CANDIDATES, 80, 100))
        long = dict(vr.CONDITIONS["newtcnrotwarpnoacc100"])
        long.pop("epochs")
        self.assertEqual(long, vr.CONDITIONS["newtcnrotwarpnoacc"])
```

- [ ] **Step 2: 실패를 확인한다**

Run: `ml/.venv/Scripts/python.exe -m unittest discover -s ml -p "test_v2_epochs.py" -v`
Expected: `AttributeError: module 'v2_return' has no attribute 'epochs_of'`

- [ ] **Step 3: 구현한다**

`ml/v2_return.py`의 `CONDITIONS["newtcnrotwarpnoacc"] = ...` 바로 아래(LABELS 정의 전)에 추가한다.

```python
# epochs: E 후보(없으면 v2.EPOCH_CANDIDATES). max(E)까지 한 번 학습하므로 E≤60 스냅숏은 같은 PC의 newtcnrotwarpnoacc와 같다
CONDITIONS["newtcnrotwarpnoacc100"] = {**CONDITIONS["newtcnrotwarpnoacc"], "epochs": [1, 5, 10, 20, 30, 40, 60, 80, 100]}
```

`augmenter` 함수 위에 추가한다.

```python
def epochs_of(label):
    """조건의 E 후보. 조건에 epochs가 없으면 프로토콜 값(v2.EPOCH_CANDIDATES)."""
    return tuple(CONDITIONS[label].get("epochs") or v2.EPOCH_CANDIDATES)
```

`cmd_run`에서 `epochs = tuple(v2.EPOCH_CANDIDATES)`를 바꾼다.

```python
    epochs = epochs_of(label)
```

`cmd_summarize`의 분할 반복 안을 결과에 기록된 E 후보로 바꾼다.

```python
            res = [rescored(json.loads(result_path(lab, sp, s, tag).read_text(encoding="utf-8")), "extreme_window", by_path, nb)
                   for s in v2.SEEDS]
            cands = tuple(res[0]["epochs"])
            assert all(tuple(r["epochs"]) == cands for r in res)
            panel = {}
            for sc in SCORINGS:
                by_e = {str(e): epoch_stats(res, e, sc, skip) for e in cands}
                for e in cands:
                    w = epoch_stats(res, e, sc, only=weak)
                    by_e[str(e)]["weak"] = {k: w[k] for k in ("clean_success_rate", "no_issue_rate", "success_rate")}
                    by_e[str(e)]["weak"]["clip_evaluations_per_seed"] = w["per_seed"][0]["n"]
                best = max(cands, key=lambda e: (round(by_e[str(e)]["selection_score"], 12), -e))
                panel[sc] = {"selected_E": best, "by_epoch": by_e}
```

대기 모드로 실행이 멈춘 일이 두 번 있었다(2026-10-28 약 1시간 40분, 2026-10-29 약 6분). `cmd_run_all` 첫 줄에서 실행 중에만 대기를 막는다(전원 설정은 바꾸지 않는다).

```python
def keep_awake():
    """실행하는 동안 Windows 대기 모드를 막는다. 프로세스가 끝나면 풀리고 전원 설정은 바꾸지 않는다."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
```

```python
def cmd_run_all(parallel, labels=LABELS, tag=None, splits=SPLITS):
    """(기존 docstring 유지)"""
    keep_awake()
    jobs = ...
```

- [ ] **Step 4: 테스트를 확인한다**

Run: `ml/.venv/Scripts/python.exe -m unittest discover -s ml -p "test_*.py"`
Expected: Task 1 포함 78개 통과, 1개 묶음 건너뜀

- [ ] **Step 5: 짧은 동일성 확인(선택, 약 20분).** 실행 PC에 newtcnrotwarpnoacc 결과가 없으면, S-P5 seed 1개를 두 조건으로 돌려 E60 발행 기록이 같은지 본다. 같지 않으면 Step 6의 "E≤60 = 기준선" 가정을 쓰지 않고 기준선을 따로 돌린다.

Run: `ml/.venv/Scripts/python.exe ml/v2_return.py run --label newtcnrotwarpnoacc --split S-P5 --seed 20261021 --tag samecheck-<날짜>`
Run: `ml/.venv/Scripts/python.exe ml/v2_return.py run --label newtcnrotwarpnoacc100 --split S-P5 --seed 20261021 --tag samecheck-<날짜>`
확인: 두 결과 JSON(`ml/runs/return-label-01/samecheck-<날짜>/results/`)의 `folds[*].per_epoch["60"].extreme_window.per_source[*].events`가 모두 같다.

- [ ] **Step 6: 본 실행(백그라운드, 수 시간).** 이전 PC 기준 S-P5 fold 하나가 E60에서 약 250초였다. E100이면 약 1.7배, 6분할 × seed 5 = fold 125개다.

Run: `ml/.venv/Scripts/python.exe ml/v2_return.py run-all --labels newtcnrotwarpnoacc100 --splits C S-P1 S-P2 S-P3 S-P4 S-P5 --tag long-<날짜> --parallel 8 --save-models`(Task 6을 먼저 했으므로 후보 E 모델도 함께 저장)
Expected: 마지막 줄 `failed: none`

Run: `ml/.venv/Scripts/python.exe ml/v2_return.py summarize --tag long-<날짜> --splits C S-P1 S-P2 S-P3 S-P4 S-P5 --out summary-long.json`

- [ ] **Step 7: 판정한다(기준 미리 고정).** 같은 실행 안에서 "E≤60 중 선택 E"와 "E≤100 중 선택 E"를 비교한다.
  - E 후보를 100까지 늘리는 조건: S 다섯 분할 평균 정검출이 **+0.5%p 이상**이고, **다섯 중 셋 이상**의 분할에서 오른다.
  - 못 미치면 후보는 60까지로 두고 결과만 기록한다.
  - 어느 쪽이든 E≤60 결과를 실행 PC의 noacc 기준선으로 README에 기록한다(Step 5에서 같음을 확인했을 때만).
- [ ] **Step 8: README·진행기록 기록과 결과 gzip 사본, 커밋(사용자 확인 후).** 결과 gzip 사본은 지금까지와 같이 `docs/experiments/ble-v2/return-label-01/results/long-<날짜>/`에 둔다.

```bash
git add ml/v2_return.py ml/test_v2_epochs.py docs/experiments/ble-v2/return-label-01 docs/진행기록.md
git commit -m "Add per-condition epoch candidates and run newtcnrotwarpnoacc to E100"
```

---

### Task 3: 발행 규칙 재채점(불응기·재무장)

§0.2에서 정답 발행 뒤 340~460 ms에 반대 방향이 한 번 더 나갔다. 재학습 없이 저장된 점수로 발행 규칙만 바꿔 다시 채점한다. 점수 파일(`seed-<s>-fold-<k>-scores.npz`)이 필요하다.

**2차 개정:**
- 점수 파일: 다른 PC의 noacc 점수 파일은 이 PC에 없다. **Step 0**으로 이 PC에서 newtcnrotwarpnoacc를 여섯 분할 × seed 5, 기존 E 후보(E60까지)로 다시 학습한다(`--save-models`, tag `noacc-zoon-pc-20261029`). 이 결과가 이 PC의 noacc 기준선도 된다. 다른 PC의 점수 파일을 가져올 수 있으면 그 실행 기록(결과 JSON·요약)과 함께 같은 방식으로 재채점할 수 있다.
- 코드: Step 0 실행 중에는 `ml/v2_return.py`를 고칠 수 없어, `score`에 `issue_fn` 인자를 더하는 대신 `v2_rules.score_with()`를 따로 두었다. 같은 채점임은 테스트(지금 규칙으로 `v2_return.score`와 클립별 결과 동일)와 Step 6의 R0 assert로 확인한다. 판정 시각은 `val_chunks()`가 센서 행 수로 다시 만든다(학습 창의 시각과 같음을 테스트로 확인).
- 판정: 아래 기준으로 **후보**를 고른다. 채택(이후 비교와 보드에 쓰는 규칙으로 정하는 것)은 Task 8의 연속 조작 녹화에서 불응기가 정상 다음 명령을 막지 않는지 확인한 뒤에 한다. 지금 채점은 클립마다 발행 상태를 초기화하므로 그 문제를 볼 수 없다.

**Files:**
- Create: `ml/v2_rules.py`
- Test: `ml/test_v2_rules.py`

**Interfaces:**
- Consumes: `v2_return.classify`, `v2_return.success_window`, `v2_return.epoch_stats`, `v2_return.run_dir`, Step 0 요약(`summary-noacc-zoon_computer.json`)
- Produces: `issue_events_rule(times, scores, refractory_ms=0, rearm=2) -> list[dict]`, `score_with(val, scores, by_path, nb, issue_fn) -> list[dict]`, `val_chunks(split, k, by_path)`, `RULES`, 결과 `docs/experiments/ble-v2/return-label-01/rules-<tag>-<label>.json`

- [ ] **Step 0: 점수 파일 만들기(이 PC 재학습, 백그라운드)**

Run: `ml/.venv/Scripts/python.exe ml/v2_return.py run-all --labels newtcnrotwarpnoacc --splits C S-P1 S-P2 S-P3 S-P4 S-P5 --tag noacc-zoon-pc-20261029 --parallel 6 --save-models`
Expected: `failed: none`. 이어서 `ml/.venv/Scripts/python.exe ml/v2_return.py summarize --tag noacc-zoon-pc-20261029 --splits C S-P1 S-P2 S-P3 S-P4 S-P5 --out summary-noacc-zoon_computer.json`. 다른 PC 결과(§0.1)와의 차이는 재현성 기록으로 남긴다.

**규칙 후보(미리 고정):**

| 이름 | 불응기(직전 발행 뒤 발행 금지) | 재무장에 필요한 확실한 NONE |
|---|---|---|
| R0 | 0 ms | 2회(지금 규칙) |
| R1 | 500 ms | 2회 |
| R2 | 800 ms | 2회 |
| R3 | 0 ms | 4회(200 ms) |

**후보 기준(미리 고정, 2차 개정에서 "채택"을 "후보"로 바꿈):**
- S 다섯 분할 평균 정검출이 R0보다 0.1%p 넘게 낮지 않다.
- 여섯 분할의 다른 방향 발행 합이 R0보다 **30% 이상** 줄어든다.
- C 정검출 감소 0.3%p 이내, 정답 지연 중앙값 변화 ±10 ms 이내.
- 여럿이 통과하면 가장 약한 변경을 고른다(R1 → R3 → R2 순).
- 제품 제약(사용자 확인): 동작 하나가 가는 피크 → r까지 약 300~450 ms라서, r 뒤 500 ms 안에 다음 명령을 내는 일은 드물다고 본다. 800 ms(R2)는 빠른 연속 조작을 막을 수 있다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
"""발행 규칙 변형 점검. 학습하지 않는다."""
import unittest

import numpy as np

import v2
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

    def test_rearm_needs_more_none(self):
        times, scores = np.arange(len(SEQ)) * 50, np.array([confident(c) for c in SEQ])
        self.assertEqual([e["class_index"] for e in rules.issue_events_rule(times, scores, rearm=4)], [1])
```

- [ ] **Step 2: 실패를 확인한다**

Run: `ml/.venv/Scripts/python.exe -m unittest discover -s ml -p "test_v2_rules.py" -v`
Expected: `ModuleNotFoundError: No module named 'v2_rules'`

- [ ] **Step 3: `v2_return.score`에 발행 함수 인자를 더한다(기본값은 지금 규칙)** — 2차 개정: 하지 않는다. `v2_rules.score_with()`로 대신하고, 아래 Step 4 코드의 `vr.score(..., issue_fn=fn)` 호출도 `score_with(..., fn)`로 바뀌었다. 실제 코드는 `ml/v2_rules.py`가 기준이다.

```python
def score(val_chunks, scores, by_path, nb, scoring, issue_fn=v2.issue_events):
    totals, offset, per_source = Counter(), 0, []
    for record, _, labels, meta in val_chunks:
        n = len(labels)
        events = issue_fn([m["timestamp_ms"] for m in meta], scores[offset:offset + n])
```

- [ ] **Step 4: `ml/v2_rules.py`를 만든다**

```python
"""발행 규칙 변형과 저장된 점수로 다시 채점(학습하지 않는다).

점수는 학습한 PC의 ml/runs/return-label-01/<tag>/<label>-<split>/seed-<seed>-fold-<k>-scores.npz(깃 제외)에 있다.
분할마다 같은 tag 요약의 선택 E(지금 규칙 기준)에서 규칙만 바꿔 채점한다.

사용: ml/.venv/Scripts/python.exe ml/v2_rules.py --tag long-<날짜> --label newtcnrotwarpnoacc100 --summary summary-long.json
"""
import argparse
import json

import numpy as np

import v2
import v2_return as vr

RULES = {"R0": {"refractory_ms": 0, "rearm": 2},       # 지금 규칙(v2.issue_events와 같다)
         "R1": {"refractory_ms": 500, "rearm": 2},
         "R2": {"refractory_ms": 800, "rearm": 2},
         "R3": {"refractory_ms": 0, "rearm": 4}}
SPLITS = ("C", "S-P1", "S-P2", "S-P3", "S-P4", "S-P5")
SCORING = "extreme_window"


def issue_events_rule(times, scores, refractory_ms=0, rearm=2):
    """v2.issue_events와 같되, 직전 발행 뒤 refractory_ms 안에는 발행하지 않고, 재무장에 확실한 NONE이 rearm번 필요하다."""
    events, last = [], None
    locked, candidate, count, none_count = False, None, 0, 0
    for t, p in zip(times, scores):
        top = int(np.argmax(p))
        if locked:
            none_count = none_count + 1 if top == 0 and p[0] >= .8 else 0
            if none_count >= rearm:
                locked, candidate, count, none_count = False, None, 0, 0
            continue
        margin = np.sort(p)[-1] - np.sort(p)[-2]
        if top != 0 and p[top] >= .8 and margin >= .2:
            count = count + 1 if top == candidate else 1
            candidate = top
            if count >= 2 and (last is None or t - last >= refractory_ms):
                events.append({"timestamp_ms": int(t), "class_index": top, "score": float(p[top])})
                locked, candidate, count, none_count, last = True, None, 0, 0, t
        else:
            candidate, count = None, 0
    return events


def val_chunks(split, k, by_path):
    """fold k 검증 원본을 학습 때와 같은 순서(v2.fold_sets)로, 판정 시각만 채운 (record, None, ends, meta)로 돌려준다."""
    val = set(split["cv"]["folds"][k]["validation_sources"])
    chunks = []
    for p in split["train_sources"]:
        if p in val:
            ts, _ = v2.read_sensor(vr.ROOT / p)
            ends = np.arange(v2.WINDOW - 1, len(ts), v2.STRIDE)
            chunks.append((by_path[p], None, ends, [{"timestamp_ms": int(ts[i])} for i in ends]))
    return chunks


def rescore(tag, label, split_name, epoch, rule, by_path, nb):
    split = v2.load_split(split_name)
    fn = lambda times, scores: issue_events_rule(times, scores, **RULES[rule])
    seeds = []
    for s in v2.SEEDS:
        folds = []
        for k in range(split["cv"]["n_folds"]):
            npz = vr.run_dir(tag) / f"{label}-{split_name}" / f"seed-{s}-fold-{k}-scores.npz"
            scores = np.load(npz)[f"e{epoch}"]
            _, per_source = vr.score(val_chunks(split, k, by_path), scores, by_path, nb, SCORING, issue_fn=fn)
            folds.append({"per_epoch": {str(epoch): {SCORING: {"per_source": per_source}}}})
        seeds.append({"folds": folds})
    return seeds


def off_direction_count(seeds, epoch, nb):
    """방향 클립에서 정답과 다른 방향으로 나간 발행 수(seed 합)."""
    return sum(1 for res in seeds for f in res["folds"] for p in f["per_epoch"][str(epoch)][SCORING]["per_source"]
               if p["source_path"] in nb
               for _, c, _ in p["events"] if c != v2.CLASSES.index(nb[p["source_path"]]["direction"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--summary", required=True, help="같은 tag의 summarize 결과 파일 이름(분할별 선택 E를 읽는다)")
    a = ap.parse_args()
    target = vr.OUT / f"rules-{a.tag}-{a.label}.json"
    if target.exists():
        raise FileExistsError(f"{target}가 이미 있다")
    summary = json.loads((vr.OUT / a.summary).read_text(encoding="utf-8"))
    _, by_path, nb = vr.load()
    out = {"tag": a.tag, "label": a.label, "summary": a.summary, "rules": RULES, "scoring": SCORING,
           "created_kst": v2.now(), "panels": {}}
    for sp in SPLITS:
        panel = summary["panels"][f"{a.label}-{sp}"][SCORING]
        e = panel["selected_E"]
        out["panels"][sp] = {"epoch": e}
        for name in RULES:
            seeds = rescore(a.tag, a.label, sp, e, name, by_path, nb)
            st = vr.epoch_stats(seeds, e, SCORING)
            if name == "R0":       # 지금 규칙으로 다시 채점하면 요약과 같아야 한다(점수와 판정 시각 정렬 확인)
                assert abs(st["clean_success_rate"] - panel["by_epoch"][str(e)]["clean_success_rate"]) < 1e-12
            row = {k: st[k] for k in ("clean_success_rate", "no_issue_rate", "background_false_per_clip", "delay_median_ms")}
            row["off_direction"] = off_direction_count(seeds, e, nb)
            out["panels"][sp][name] = row
            print(f"{sp} E{e} {name}: 정검출 {row['clean_success_rate'] * 100:.2f}% 무발행 {row['no_issue_rate'] * 100:.2f}% "
                  f"다른 방향 {row['off_direction']} 배경 {row['background_false_per_clip']:.3f}")
    v2.dump(target, out)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 테스트를 확인한다**

Run: `ml/.venv/Scripts/python.exe -m unittest discover -s ml -p "test_*.py"`
Expected: 81개 통과, 1개 묶음 건너뜀

- [ ] **Step 6: 재채점을 실행한다**

Run: `ml/.venv/Scripts/python.exe ml/v2_rules.py --tag noacc-zoon-pc-20261029 --label newtcnrotwarpnoacc --summary summary-noacc-zoon_computer.json`
Expected: R0 assert 통과(통과하지 않으면 점수와 판정 시각의 정렬이 틀린 것이니 결과를 쓰지 않는다), 분할 × 규칙 24줄 출력

- [x] **추가(2026-10-29, 점수 모양 진단 뒤): 연속 판정 3회 규칙 R4·R5.** 저장 점수로 발행 직전·직후의 연속 충족 판정 수를 셌다(`ml/runs/figures/score_shape.py`, 깃 제외; 결과 `wrong-direction/score-shape-noacc-zoon-pc-20261029.json`). 복귀 중 반대 방향 발행 24건 중 20건이 연속 2회(최소)만 조건을 채웠고 최고 점수는 높았다(중앙값 0.995). 정답 발행 6,896건 중 연속 2회는 196건(2.8%)이고 중앙값은 4회다. 그래서 R4(연속 3회), R5(연속 3회 + 불응기 500 ms)를 더해 재채점한다. **아래 기준은 이 분포를 본 뒤, R4·R5 재채점 전에 정했다.**
  - S 다섯 평균 정검출이 R0보다 0.1%p 넘게 낮지 않다. C 정검출 감소 0.3%p 이내.
  - 여섯 분할 다른 방향 발행 합이 R0(49건)보다 30% 이상 준다(34건 이하). 복귀 중 반대 방향 발행 24건이 12건 이하로 준다.
  - S 다섯 평균 무발행이 R0보다 0.3%p 넘게 늘지 않는다(연속 2회뿐인 정답이 무발행으로 바뀔 수 있다).
  - 정답 지연 중앙값 증가 50 ms 이하(연속 3회는 구조상 약 50 ms 늦다). 이 지연이 체감상 괜찮은지는 보드·연속 조작 확인(Task 7·8)에서 사용자가 판단한다.
  - 통과해도 채택이 아니라 Task 8 연속 조작 시험 대상이다(빠른 연속 동작에서 정상 명령을 놓치는지 확인).
- [ ] **Step 7: 후보 기준으로 판정하고 기록한다.** 후보는 Task 8의 연속 조작 확인을 통과하면 채택한다. 채택하면 그 규칙을 이후 모든 비교·내보내기·보드 구현의 발행 규칙으로 쓰고, `v2.issue_events`를 바로 바꾸지는 않는다(바꾸는 시점은 Task 5에서 정한다). 진행기록·README에 남기고 커밋(사용자 확인 후).

```bash
git add ml/v2_return.py ml/v2_rules.py ml/test_v2_rules.py docs/experiments/ble-v2/return-label-01 docs/진행기록.md
git commit -m "Rescore issue rules with refractory and rearm variants"
```

---

### Task 4: (조건부) 학습 쪽 수정 — 별도 계획

**들어가는 조건:** Task 3 뒤에도 여섯 분할 다른 방향 발행 합이 newtcnrotwarp 수준(40건)보다 많다.

Task 1 결과에 따라 아래 후보 중 하나를 골라 별도 계획(`docs/superpowers/plans/<날짜>-v2-orientation-free-acc.md`)으로 쓴다. 각 후보는 새 조건 하나이고, 실행 PC의 noacc 기준선(Task 2 E≤60)과 여섯 분할에서 비교한다.

| 후보 | 생각 | 언제 |
|---|---|---|
| 정지 구간 평균을 뺀 가속도 3채널 | 클립의 정지 구간(0~890 ms) 가속도 평균을 빼서 시작 자세의 중력 값을 없앤다. 동작 중 회전으로 바뀌는 중력 성분은 남으므로 선형 가속도와 같지 않다 | "정답 없이 반대 방향"이 많을 때. 가속도가 가는 동작과 돌아오는 동작을 가르는 데 도움을 줬다는 추정을 직접 시험한다 |
| 중력 방향 전체 회전 증강 + 가속도 유지 | 학습 사본마다 가속도·자이로를 함께 임의 3차원 회전한다(지금은 Y축 ±30°, 기울기 ±15°) | 위 후보로 부족할 때. 사본 수가 늘어 학습 시간이 커진다 |
| 복귀 뒤 반동 창을 NONE으로 더 뽑기 | `outbound_none_chooser`처럼, r+150~r+500 ms에 끝나는 창을 NONE 학습 창에 더 넣는다 | Task 3 규칙으로 줄지 않은 "정답 뒤" 발행이 남았을 때 |

#### Task 4 첫 조건과 판단 기준(2026-10-29 확정, 학습 전)

- **진입:** zoon_computer noacc의 다른 방향 발행 합이 R0 49건, R1 38건이다. 남은 주 원인은 돌아오는 동작 중 반대 방향 24건이고, 시험한 규칙(R1~R5) 중 기준을 통과한 것은 없다(R4·R5는 다른 방향을 크게 줄였지만 무발행이 약 2.8%p 늘었다). user 경로 PC의 40건은 참고값이다.
- **조건 `newtcnrotwarpaccsub`(하나만):** newtcnrotwarp와 같고(9채널: 가속도 3·자이로 3·회전각 3), 가속도 3채널만 바꾼다. 창마다 원시 가속도(m/s²)에서 **그 클립(증강 사본이면 사본)의 정지 구간 0~890 ms 평균**을 뺀 뒤, fold 학습 창의 축별 평균·표준편차로 정규화한다(회전각 정규화와 같은 방식). 시작 자세의 중력 값만 빠지고, 동작 중 회전으로 바뀌는 중력 성분은 남는다. 손목 자세 영향 제거를 보장하지 않으며 그 효과를 확인하는 실험이다. 보드에서는 가속도도 켜야 하고 정지 구간 평균을 온라인으로 잡아야 한다(Task 8에서 확인).
- **실행:** zoon_computer, 여섯 분할 × seed 5, E60까지, `--save-models`, tag `zoon_computer-accsub-20261029`. 비교 기준은 같은 PC의 `noacc-zoon-pc-20261029`(`summary-noacc-zoon_computer.json`). 두 모델을 각각 R0·R1으로 채점한다.
- **판단 기준(모두 만족해야 다음 단계 후보, 기준값은 zoon_computer noacc):**

| 항목 | 기준 noacc | 기준 |
|---|---|---|
| S 다섯 평균 정검출(R0) | 97.11% | 96.81% 이상(−0.3%p 이내) |
| S-P3·S-P4 각각 정검출(R0) | 97.62%·97.18% | 각각 −0.5%p 이내(97.12%·96.68% 이상) |
| 돌아오는 동작 중 반대 방향 발행(R0, 6분할 합) | 24건 | 12건 이하 |
| 다른 방향 발행 합(6분할) | R0 49건·R1 38건 | R0 34건 이하, R1 27건 이하(각 −30%) |
| S 다섯 평균 무발행(R0) | 2.09% | 2.59% 이하(+0.5%p 이내) |
| 배경 오발행 6분할 평균(R0) | 0.135건/클립 | 0.165 이하(+0.03 이내) |
| 정답 지연 중앙값(R0) | 분할별 56~60 ms | 분할별 ±10 ms 이내 |

- 발행 건수 합은 seed 5개·분할 6개를 더한 값이라 독립된 실제 사용 오류 수가 아니다. 통과해도 Task 8(연속 조작·온라인 기준값)에서 다시 확인한다.

---

### Task 5: 튜닝 계획 개정 — 별도 계획

2026-10-28 튜닝 계획(진행기록 "하이퍼파라미터 튜닝 준비 논의")을 고쳐 별도 계획(`docs/superpowers/plans/<날짜>-v2-tuning.md`)으로 쓴다. 바꿀 점:

- 거르기 분할: S-P5만 쓰던 것을 **S-P3·S-P4**로 바꾼다. S-P5는 손목 방향 짝이 모두 학습에 남는 가장 유리한 분할이었고, 가속도 제외 효과도 거의 보이지 않았다(96.88 → 96.71%). S-P3·S-P4는 짝 없는 세션이 검증에 들어간다.
- 확인 단계: 상위 3개를 **여섯 분할 × seed 5**로 돌린다(기존 계획은 C·S-P5).
- 기준 조건: Task 0·2·3에서 정한 조건·E 후보·발행 규칙.
- 후보는 유지한다: 채널 폭, 드롭아웃, 학습률, 증강 사본 수와 범위, 부드러운 라벨(뒤쪽만, 더하는 창 수 조정).
- 첫 시도는 Task 6의 가중치 저장을 켠 기준 조건이다.

---

### Task 6: 가중치 저장과 int8 확인

지금 코드는 점수만 남기고 모델을 저장하지 않는다. 보드 이식 전에 ① 모델과 전처리 값 저장, ② int8 변환 뒤 발행이 float와 같은지를 확인한다. Task 2와 병렬로 할 수 있다(조건은 지금 기준 조건으로 하고, Task 3 결과가 나오면 발행 규칙만 바꿔 다시 비교한다).

**개정(2026-10-29, §0.3):** Step 1~7(가중치·전처리 값 저장)은 그대로 한다. Step 8~10(int8)은 Task 7에서 C 직접 구현의 시간·전력이 부족하다고 측정될 때만 한다. 그 전까지 보드 쪽 비교 기준은 float 모델이다.

**실행(2026-10-29, 사용자 요청으로 Task 2보다 먼저):** Step 2~7을 구현했다. 아래 계획 코드와 다른 점:
- `fit_snapshots`는 `save_to`(마지막 시점 하나) 대신 `save_dir`를 받아 **후보 E 시점마다** `save_dir/e<E>.keras`를 저장한다. 긴 실행(Task 2)에서 점수와 함께 모든 후보 E의 가중치를 얻기 위해서다(다시 학습하지 않음).
- `run`·`run-all`에 `--save-models`를 더했다. fold마다 `ml/runs/return-label-01/<tag>/models/<label>-<split>/seed-<s>-fold-<k>/`에 `e<E>.keras`와 `prep.json`(`prep_values`: 채널 순서, 6축·회전각 정규화 값, 영점 방식, 처리 순서)을 저장한다. 결과 JSON에 `models_saved`를 기록한다.
- `export`는 `e<E>.keras`와 `export.json`(`prep_values` 포함)을 저장한다.
- Step 1(TFLite 확인)과 Step 8~10(int8)은 하지 않았다. 나중에 하면 `v2_int8.py`는 Task 3에서 채택한 발행 규칙(`issue_fn`)과 Task 2에서 정한 E로 채점해야 한다(계획 코드는 기본 규칙으로 채점한다).
- 확인: ml 테스트 79개 통과(1개 묶음 건너뜀). S-P5 seed 20261021을 E1로 `export --fold 0`과 `run --save-models`를 돌려(임시 tag, 확인 뒤 삭제), fold 4개 모두 다시 불러온 모델 출력이 저장된 점수와 최대 1.2e-7 차이, `export` 검증 채점이 `run` fold 0과 같음을 확인했다. 모델 파일은 약 143 KB(옵티마이저 상태 포함)라 Task 2 전체(fold 125개 × E 9개)는 약 160 MB다.

**Files:**
- Modify: `ml/v2.py:615-647`(`fit_snapshots`에 `save_to`)
- Modify: `ml/v2_return.py`(`prepare_fold`가 `k=None`이면 학습 원본 전체, `cmd_export`, `export` 하위 명령)
- Create: `ml/v2_int8.py`
- Test: `ml/test_v2_export.py`
- Create(실행 결과): `docs/experiments/ble-v2/deploy-01/int8-<export 이름>.json`

**Interfaces:**
- Produces: `v2.fit_snapshots(..., save_to=None)`, `v2_return.prepare_fold(label, by_path, nb, split, None)`, `v2_return.cmd_export(label, split_name, seed, epoch, fold=None, tag=None)` → `ml/runs/return-label-01/<tag>/export/<이름>/{model.keras, export.json}`

**int8 채택 기준(미리 고정):** S-P5 fold 4개 × seed 20261021(검증 클립 269개)에서
- 발행 기록(시각·방향)이 float와 다른 클립이 **2% 이하**(5클립 이하).
- 정검출 감소가 **0.5%p 이하**, 다른 방향 발행이 늘지 않는다.
- 못 미치면 양자화 인식 학습을 Task 7 계획에 넣는다.

- [ ] **Step 1: 이 venv에 TFLite 변환기·인터프리터가 있는지 확인한다**

Run: `ml/.venv/Scripts/python.exe -c "import tensorflow as tf; print(tf.__version__, hasattr(tf.lite, 'TFLiteConverter'), hasattr(tf.lite, 'Interpreter'))"`
Expected: `2.21.0 True True`. 인터프리터가 없거나 사용 중단 경고만 나오면 `ml/.venv/Scripts/python.exe -m pip install ai-edge-litert`로 설치하고 `requirements.txt`에 버전과 함께 적는다.

- [ ] **Step 2: 실패하는 테스트를 쓴다**

```python
"""모델 저장 점검. 첫 테스트는 아주 작은 학습(1 epoch)을 한다."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

import v2
import v2_return as vr


class ExportTests(unittest.TestCase):
    def test_saved_model_reproduces_scores(self):
        import tensorflow as tf
        rng = np.random.default_rng(0)
        x = rng.normal(size=(32, v2.WINDOW, 6)).astype(np.float32)
        y = rng.integers(0, 5, size=32)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "model.keras"
            scores, _ = v2.fit_snapshots(x, y, x[:4], 20261021, (1,), model_fn=vr.tcn, save_to=path)
            loaded = tf.keras.models.load_model(path)
            np.testing.assert_allclose(loaded(x[:4], training=False).numpy(), scores[1], atol=1e-6)

    def test_full_training_set_has_no_validation(self):
        _, by_path, nb = vr.load()
        split = v2.load_split("S-P5")
        d, _ = vr.prepare_fold("newtcnrotwarpnoacc", by_path, nb, split, None)
        self.assertEqual(d["val"], [])
        self.assertEqual(d["train_sources"], len(split["train_sources"]))
        self.assertEqual(d["x_train"].shape[2], 6)          # 자이로 3 + 회전각 3
```

- [ ] **Step 3: 실패를 확인한다**

Run: `ml/.venv/Scripts/python.exe -m unittest discover -s ml -p "test_v2_export.py" -v`
Expected: `TypeError: fit_snapshots() got an unexpected keyword argument 'save_to'`

- [ ] **Step 4: `v2.fit_snapshots`에 저장을 더한다(없으면 지금과 같다)**

```python
def fit_snapshots(x_train, y_train, x_val, seed, epochs, model_fn=None, save_to=None):
    """max(epochs)까지 한 번 학습하고 epochs에 든 epoch가 끝날 때마다 검증 점수를 저장한다.

    입력 채널 수는 x_train에서 읽는다(기본 6축). model_fn(channels)을 주면 그 모델을 쓴다(기본 build_model).
    save_to를 주면 학습이 끝난 모델(max(epochs) 시점)을 그 경로(.keras)에 저장한다.
    """
```

```python
    hist = model.fit(ds, epochs=max(epochs), verbose=0, shuffle=False, callbacks=[snap])
    if save_to is not None:
        model.save(save_to)
    return snap.scores, hist.history["loss"]
```

- [ ] **Step 5: `prepare_fold`가 학습 원본 전체도 만들게 하고, 학습 함수가 키워드 인자를 넘기게 한다**

```python
def prepare_fold(label, by_path, nb, split, k):
    """조건 label의 fold k 학습·검증 집합과 학습 함수를 돌려준다. k가 None이면 분할의 학습 원본 전체로 학습하고 검증은 없다."""
    cond = CONDITIONS[label]
    window_fn = (lambda r, ts, raw, m, s: windows_with_angle(r, ts, raw, m, s, cond["angle_bias"])) if cond["angle"] else None
    none_fn = outbound_none_chooser(nb) if cond["hard"] == "outbound" else None
    augment_fn = augmenter(cond["aug"])
    rb = relabel(by_path, nb, label)
    if k is None:
        d = v2.build_sets([rb[p] for p in split["train_sources"]], [], window_fn=window_fn, none_fn=none_fn, augment_fn=augment_fn)
    else:
        d = v2.fold_sets(rb, split, k, window_fn=window_fn, none_fn=none_fn, augment_fn=augment_fn)
    d["train_aug_stats"] = dict(getattr(augment_fn, "stats", {}))
    if cond["angle_norm"]:
        normalize_angle(d)
    if cond["drop_acc"]:
        drop_acc(d)
    if cond["model"] == "tcn":
        return d, lambda *args, **kw: v2.fit_snapshots(*args, model_fn=tcn, **kw)
    return d, v2.fit_snapshots
```

- [ ] **Step 6: `cmd_export`와 하위 명령을 더한다**

```python
def cmd_export(label, split_name, seed, epoch, fold=None, tag=None):
    """label 조건을 E까지 학습해 Keras 모델과 전처리 값을 저장한다(깃 제외 ml/runs/). fold가 None이면 학습 원본 전체로 학습한다."""
    name = f"{label}-{split_name}-seed-{seed}-E{epoch}-" + ("all" if fold is None else f"fold{fold}")
    folder = run_dir(tag) / "export" / name
    if folder.exists():
        raise FileExistsError(f"{folder}가 이미 있다")
    _, by_path, nb = load()
    split = v2.load_split(split_name)
    d, fit = prepare_fold(label, by_path, nb, split, fold)
    folder.mkdir(parents=True)
    x_val = np.concatenate([c[1] for c in d["val"]]) if d["val"] else d["x_train"][:1]
    scores, _ = fit(d["x_train"], d["y_train"], x_val, seed, (epoch,), save_to=folder / "model.keras")
    cond = CONDITIONS[label]
    channels = list(v2.AXES[3:] if cond["drop_acc"] else v2.AXES) + (["angX", "angY", "angZ"] if cond["angle"] else [])
    meta = {"label": label, "condition": cond, "split": split_name, "seed": seed, "epoch": epoch, "fold": fold, "tag": tag,
            "created_kst": now(), "code_sha256": {f: digest(ROOT / "ml" / f) for f in ("v2.py", "v2_return.py", "model.py")},
            "records_sha256": digest(v2.RECORDS), "new_records_sha256": digest(NEW_RECORDS),
            "input_channels": channels, "window": v2.WINDOW, "stride": v2.STRIDE, "classes": list(CLASSES),
            "norm_mean_6axis": d["mean"].tolist(), "norm_std_6axis": d["std"].tolist(),
            "angle_mean": d["angle_mean"].tolist() if "angle_mean" in d else None,
            "angle_std": d["angle_std"].tolist() if "angle_std" in d else None,
            "angle_scale_deg": ANGLE_SCALE_DEG, "angle_bias": cond["angle_bias"], "precue_samples": PRECUE_SAMPLES,
            "env": runtime_env()}
    if d["val"]:
        meta["val_totals"] = score(d["val"], scores[epoch], by_path, nb, "extreme_window")[0]
    dump(folder / "export.json", meta)
    print("saved", folder)
```

`main()`에 하위 명령을 더한다.

```python
    x = sub.add_parser("export")
    x.add_argument("--label", choices=LABELS, required=True)
    x.add_argument("--split", choices=v2.SPLIT_NAMES, required=True)
    x.add_argument("--seed", type=int, required=True)
    x.add_argument("--epoch", type=int, required=True)
    x.add_argument("--fold", type=int, help="생략하면 분할의 학습 원본 전체로 학습한다(배포 후보)")
    x.add_argument("--tag")
```

```python
    elif args.cmd == "export":
        cmd_export(args.label, args.split, args.seed, args.epoch, args.fold, args.tag)
```

(마지막 `else:` 분기는 `summarize` 그대로)

- [ ] **Step 7: 테스트를 확인한다**

Run: `ml/.venv/Scripts/python.exe -m unittest discover -s ml -p "test_*.py"`
Expected: 83개 통과, 1개 묶음 건너뜀(두 번째 테스트는 S-P5 학습 원본 전체 증강이라 수십 초 걸릴 수 있다)

- [ ] **Step 8: `ml/v2_int8.py`를 만든다**

```python
"""float 모델과 int8 변환 모델의 발행을 같은 검증 fold에서 비교한다(배포 전 확인).

사용: ml/.venv/Scripts/python.exe ml/v2_int8.py --export ml/runs/return-label-01/<tag>/export/<이름>
"""
import argparse
import json
from pathlib import Path

import numpy as np

import v2
import v2_return as vr

REPRESENTATIVE = 500      # 대표 입력 창 수(학습 창에서 고정 seed로 뽑는다)
SCORING = "extreme_window"


def interpreter(model_bytes):
    try:
        from ai_edge_litert.interpreter import Interpreter
    except ImportError:
        import tensorflow as tf
        Interpreter = tf.lite.Interpreter
    it = Interpreter(model_content=model_bytes)
    it.allocate_tensors()
    return it


def convert(saved_dir, x_train):
    import tensorflow as tf
    idx = np.random.default_rng(v2.SEED).choice(len(x_train), size=min(REPRESENTATIVE, len(x_train)), replace=False)
    conv = tf.lite.TFLiteConverter.from_saved_model(str(saved_dir))
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = lambda: ([x_train[i:i + 1]] for i in idx)
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.int8
    conv.inference_output_type = tf.int8
    return conv.convert()


def run_int8(it, x):
    inp, out = it.get_input_details()[0], it.get_output_details()[0]
    s_in, z_in = inp["quantization"]
    s_out, z_out = out["quantization"]
    scores = np.empty((len(x), len(v2.CLASSES)), dtype=np.float32)
    for i in range(len(x)):
        it.set_tensor(inp["index"], np.clip(np.round(x[i:i + 1] / s_in + z_in), -128, 127).astype(np.int8))
        it.invoke()
        scores[i] = (it.get_tensor(out["index"]).astype(np.float32) - z_out) * s_out
    return scores


def op_names(it):
    try:
        return sorted({op["op_name"] for op in it._get_ops_details()})     # 비공개 API. 없으면 기록하지 않는다
    except AttributeError:
        return None


def main():
    import tensorflow as tf
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", required=True, help="v2_return.py export가 만든 폴더(--fold를 준 것)")
    a = ap.parse_args()
    folder = Path(a.export)
    meta = json.loads((folder / "export.json").read_text(encoding="utf-8"))
    if meta["fold"] is None:
        raise ValueError("검증 fold가 있는 export만 비교한다")
    target = v2.DOC / "deploy-01" / f"int8-{folder.name}.json"
    if target.exists():
        raise FileExistsError(f"{target}가 이미 있다")
    _, by_path, nb = vr.load()
    d, _ = vr.prepare_fold(meta["label"], by_path, nb, v2.load_split(meta["split"]), meta["fold"])
    model = tf.keras.models.load_model(folder / "model.keras")
    model.export(str(folder / "saved_model"))
    tfl = convert(folder / "saved_model", d["x_train"])
    (folder / "model_int8.tflite").write_bytes(tfl)
    it = interpreter(tfl)
    x_val = np.concatenate([c[1] for c in d["val"]])
    results = {}
    for name, s in (("float", model.predict(x_val, batch_size=256, verbose=0)), ("int8", run_int8(it, x_val))):
        totals, per_source = vr.score(d["val"], s, by_path, nb, SCORING)
        st = vr.epoch_stats([{"folds": [{"per_epoch": {"0": {SCORING: {"per_source": per_source}}}}]}], 0, SCORING)
        results[name] = {"totals": totals, "clean_success_rate": st["clean_success_rate"], "per_source": per_source}
    differ = [f["source_path"] for f, q in zip(results["float"]["per_source"], results["int8"]["per_source"])
              if f["events"] != q["events"]]
    out = {"export": folder.name, "export_meta": meta, "created_kst": v2.now(), "tflite_bytes": len(tfl), "ops": op_names(it),
           "val_clips": len(d["val"]), "clips_with_different_events": differ,
           "float_matches_training_scores": results["float"]["totals"] == meta.get("val_totals"),
           "float": {k: results["float"][k] for k in ("totals", "clean_success_rate")},
           "int8": {k: results["int8"][k] for k in ("totals", "clean_success_rate")}}
    v2.dump(target, out)
    print(f"tflite {len(tfl)} bytes, 발행이 다른 클립 {len(differ)}/{len(d['val'])}, "
          f"정검출 float {out['float']['clean_success_rate'] * 100:.2f}% int8 {out['int8']['clean_success_rate'] * 100:.2f}%")


if __name__ == "__main__":
    main()
```

- [ ] **Step 9: fold 4개를 내보내고 비교한다**(E는 Task 2 판정 뒤 S-P5 선택 E. Task 2 전이면 60)

Run(k = 0, 1, 2, 3 반복): `ml/.venv/Scripts/python.exe ml/v2_return.py export --label newtcnrotwarpnoacc --split S-P5 --seed 20261021 --epoch 60 --fold 0 --tag deploy-<날짜>`
Run(k마다): `ml/.venv/Scripts/python.exe ml/v2_int8.py --export ml/runs/return-label-01/deploy-<날짜>/export/newtcnrotwarpnoacc-S-P5-seed-20261021-E60-fold0`
Expected: 결과 JSON 4개. `float_matches_training_scores`가 false면 원인(predict와 학습 중 호출의 수치 차이로 경계 발행이 바뀐 것인지)을 먼저 확인한다.

- [ ] **Step 10: 채택 기준으로 판정하고 기록한다.** fold 4개 합으로 다른 클립 수, 정검출 차이, 다른 방향 발행 차이를 쓰고, 연산 목록(`ops`)과 tflite 크기를 Task 7 계획의 입력으로 남긴다. 진행기록에 남기고 커밋(사용자 확인 후).

```bash
git add ml/v2.py ml/v2_return.py ml/v2_int8.py ml/test_v2_export.py docs/experiments/ble-v2/deploy-01 docs/진행기록.md requirements.txt
git commit -m "Save trained models and compare float and int8 issuing on S-P5 folds"
```

---

### Task 7: 보드 이식 — 별도 계획

Task 6의 연산 목록·크기를 받아 `docs/superpowers/plans/<날짜>-v2-board.md`로 쓴다. 이 계획에서 미리 정하는 확인 항목은 다음과 같다.

| 항목 | 확인 방법 | 기준·기록 |
|---|---|---|
| 추론 구현(1순위) | Task 6에서 저장한 float 가중치를 C 배열로 내보내고, Conv1D(인과·팽창)·ReLU·Add·Dense·softmax를 C로 직접 구현한다. 마지막 시점 출력에 필요한 위치(블록별 93·45·21·9·3·1)만 계산한다 | PC에서 같은 C 코드(호스트 빌드)와 Keras 출력이 같은지 먼저 확인(최대 오차 1e-5 이하), 그다음 보드 |
| 런타임(대안) | C 구현이 시간 기준을 못 맞출 때만 TFLite Micro + int8(Task 6 Step 8~10). non-mbed 코어에서 쓸 수 있는 포트인지 먼저 확인 | 보드 코어·라이브러리 버전, 필요한 연산 지원 여부 |
| 자원 | 텐서 아레나 크기, Flash·RAM 사용량 | 빌드 로그 보존 |
| 시간 | 100 Hz 수집과 BLE를 켠 채 전처리 + 추론 1회 시간 median/p95/max | 판정 주기 50 ms 안 |
| 입력 파이프라인 | 자이로 160샘플 링 버퍼, 6축 정규화 값 중 자이로 3개, 회전각을 창 시작 기준으로 다시 누적 | PC replay와 같은 입력이 만들어지는지 |
| 회전각 영점 | 지금은 클립 0~890 ms 중앙값이다. 보드는 연속 스트림이라 "직전 정지 구간의 자이로 중앙값"으로 바꿔야 한다 | **먼저 PC에서** 이 방식으로 바꿔도 Task 3 Step 0 기준선과 결과가 같은지 확인하고, Task 8 연속 녹화에서 다시 확인 |
| PC–보드 일치 | 같은 클립을 보드에 흘려 보드 점수가 PC float 점수와 같은지(int8을 쓰면 PC int8과) | 발행 기록 일치율 |
| 가속도 끄기 | noacc면 보드에서 가속도가 필요 없을 수 있다. LSM6DS3TR-C 가속도를 끄고 전류를 비교(`firmware/battery_test`) | 다른 단계가 가속도를 쓰지 않는지 먼저 확인 |
| 실제 지연 | 동작 끝 → 앱이 명령을 받은 시각 | r+300 ms가 체감상 괜찮은지는 **사용자 확인**으로만 검증 완료 처리 |

### Task 7a: 지금 모델로 보드 C 추론 시간 조기 측정(2차 개정에서 추가, 병렬 가능)

학습 결과를 기다리지 않고 포팅 위험을 먼저 본다(`docs/제스처인식구조안.md`의 "가장 작은 배포 가능 모델을 조기 빌드" 원칙). 결과는 튜닝(Task 5)에서 모델 크기를 키울 수 있는지의 근거가 된다. 세부 단계는 착수할 때 별도 계획으로 쓴다.

- 입력: Task 3 Step 0의 저장 모델 하나(예: S-P5 seed 20261021 fold 0 E60)와 `prep.json`.
- 할 일: ① Keras 가중치를 C 배열로 내보내는 스크립트, ② Conv1D(인과·팽창)·ReLU·Add·Dense·softmax를 C로 구현(마지막 시점에 필요한 위치만 계산), ③ PC 호스트 빌드로 Keras 출력과 비교(최대 오차 1e-5 이하), ④ 보드에서 100 Hz 수집·BLE를 켠 채 추론 1회 시간 median/p95/max와 RAM·Flash 측정.
- 기준: 추론 1회가 50 ms 판정 주기 안에 들어가고, 측정 조건(코어 버전, 컴파일 옵션, BLE 상태)을 기록한다. 보드 실행은 관찰 또는 사용자 확인이 있을 때만 검증 완료로 적는다.

---

### Task 8: 연속 조작·배경 녹화와 온라인 영점 확인(2차 개정에서 앞당김)

Task 3에서 고른 발행 규칙 후보의 **채택 관문**이다. 지금 채점은 클립마다 발행 상태를 초기화해, 불응기가 정상적인 다음 명령까지 막는지, 연속 스트림에서 영점을 온라인으로 잡아도 되는지를 볼 수 없다.

**Files:**
- Create(데이터): `data/sessions/<새 세션>/`(연속 제스처 녹화, 제스처 없는 일상 녹화)
- 별도 계획 필요: 긴 파일은 `v2.read_sensor`의 파일 이름별 행 수 검사(`expected_rows`)를 통과하지 못하므로 읽는 함수, 발행 상태를 파일 안에서 유지하는 연속 재생 채점, 온라인 영점 추정 함수가 필요하다. 녹화가 확보되면 작은 계획으로 쓴다.

- [ ] **Step 1: 연속 제스처 녹화(사용자).** 같은 방향 반복(UP·UP·UP), 반대 방향 연속(UP→DOWN, RIGHT→LEFT), 다른 방향 연속을 편한 속도와 가장 빠른 속도로 한다. 각 동작의 의도한 방향과 순서를 기록한다(정답은 녹화 뒤 자동 라벨 + 검토로 만든다). 손목 방향과 자세를 섞는다.
- [ ] **Step 2: 배경 녹화(사용자).** 반지를 낀 채 제스처 없이 일상 동작을 한다: 타이핑, 마우스, 걷기, 말하며 손짓, 컵 들기 등 각 10분 이상, 합계 1시간 이상.
- [ ] **Step 3: 연속 재생 채점.** 저장 모델(Task 3 Step 0)로 녹화를 처음부터 끝까지 흘리며 발행 상태를 유지한다. 규칙 R0와 후보 규칙을 함께 채점한다. 영점은 "직전 정지 구간 자이로 중앙값"(온라인)과 클립 방식에 가까운 값을 비교한다.
- [ ] **Step 4: 관문 판정(기준은 녹화 전에 사용자와 정한다).** 제안: 가장 빠른 속도의 연속 동작에서 후보 규칙 때문에 막힌 정상 명령이 0건이고, 반대 방향 재발행은 R0보다 적다. 배경 지표는 시간당 오발행 수다(제안 목표: 시간당 1회 이하. 지금 배경 클립 오발행 0.09~0.19건/클립(약 10초)은 연속 사용으로 바로 환산할 수 없다).
- [ ] **Step 5: 약한 동작 규칙 재검토(새 근거가 있을 때만).** 2026-10-28 사용자 결정(약한 동작도 명령으로 받고 평가에 포함)을 기본으로 유지한다. noacc에서 약한 동작 정검출은 분할별 81.7~100%로 올랐다(이전 58~75%). 배경 오발행이 목표를 넘고 그 원인이 약한 동작 학습으로 보일 때만 다시 논의한다.
- [ ] **Step 6: 진행기록과 [데이터 큐레이션 기록](../../데이터큐레이션기록.md)에 결과·결정을 남긴다.**

---

### Task 9: 최종 평가(새 자료 수집)

튜닝·규칙·보드 조건이 모두 고정된 뒤 한 번만 한다.

- 지금 데이터 334개는 모두 개발에 쓰였다(각 분할의 `eval_sources`도 다른 분할의 교차검증에 들어 있다). 이 자료로 다시 평가한 값은 "기존 자료 추가 평가"로만 부른다.
- 독립 최종 평가는 설계를 고정한 뒤 **새로 녹화한 세션**(새 손목 방향·자세 포함)으로 한다. 최종 조건으로 334개 전체를 학습하고(`export`를 `--fold` 없이), 새 세션을 한 번만 평가해 seed 5개 평균·범위를 보고한다.
- 평가 결과를 보고 조건을 다시 고치면 그 세션도 개발 자료가 된다.
- 평가 명령은 이 시점에 작은 계획으로 추가한다(`v2_return.py`에 `evaluate` 하위 명령).

## 자체 점검

- 출발점의 미완 항목(기준 조건 확정, 다른 방향 발행, E60 끝값, 튜닝 분할, 가중치·int8, 보드, r+300 확인, 연속 조작, 약한 동작, 배경 오발행, 최종 평가)은 각각 Task 0·1·3·4, 2·5, 5, 6, 7a·7, 7, 8, 8, 8, 9에 있다.
- 이름 일치(2차 개정 기준): `issue_events_rule`·`score_with`·`val_chunks`·`RULES`(Task 3, `ml/v2_rules.py`), tag `noacc-zoon-pc-20261029`·요약 `summary-noacc-zoon_computer.json`(Task 3 Step 0), `prepare_fold(..., None)`·`prep_values`·`cmd_export`·`save_dir`·`--save-models`(Task 6). `epochs_of`·`newtcnrotwarpnoacc100`(Task 2)은 보류.
- 테스트 수: 계획 시작 73 → Task 1 뒤 76 → Task 6 뒤 79 → Task 3 뒤 84(실제 순서 기준).
