# 제스처 분류 모델 실험 기록

Edge Impulse 프로젝트 `RingPilot-Windows`(ID 1129540)에서 진행한 1600 ms causal window 분류 모델 실험의 상세 기록이다. 진행 경과의 요약은 `진행기록.md`에 날짜별로 있고, 여기서는 실험 설계·수치·해석만 모아둔다.

## 공통 전제

- 원본 데이터: `RingPilot`(1122630)의 `raw_up/down/left/right`(3초, 100 Hz, 6축) 및 `idle`/`other`(10초).
- 완료 시점 정의: 방향 이동과 자연 복귀의 자이로 에너지 99% 이후, IMU가 180 ms 안정되기 시작한 첫 시점(`tools/suggest-gesture-completions.js`).
- 윈도우: 1600 ms, 50 ms stride, 완료 시점 뒤 150 ms만 해당 방향 양성, 나머지 `NONE`(`tools/export-gesture-windows.js`).
- 입력: 6축(accX/Y/Z, gyrX/Y/Z) raw, 160 샘플(1600 ms × 100 Hz) = 960 features.
- NONE은 학습 30개로 캡(원본 샘플마다 번갈아 샘플링), 테스트는 `NONE 개수 × test-fraction(0.2)`.

## 실험 1 — 입력 길이 선별(800/1200/1600 ms), 로컬 선형 모델

- 날짜: 2026-09-28. 상세: `WindowLengthComparison.md`.
- 목적: 최종 모델이 아니라 입력 길이 후보를 거르는 진단.
- 모델: 10개 시간 bin의 6축 평균/표준편차 + 양 끝 차이로 만든 126개 특징, 635-parameter 선형 softmax.
- 데이터: AUTO 30개(단일 세션), 5-fold 교차검증.

| 길이 | 맥락 포함 | 이벤트 검출 | macro F1 |
|---:|---:|---:|---:|
| 800 ms | 6/30 | 6/30 | 0.216 |
| 1200 ms | 19/30 | 12/30 | 0.253 |
| 1600 ms | 28/30 | 8/30 | 0.272 |

- 결론: 800 ms는 동작 시작 맥락을 자주 잃어 제외. 1600 ms를 기본 후보로 채택. RIGHT F1은 세 조건 모두 0.08 미만으로 특히 낮았음(이 선형 모델 한정).

## 실험 2 — 1차 Edge Impulse 업로드, Dense 기준선

- 날짜: 2026-10-06.
- 데이터: 단일 세션 AUTO 30개 → 학습 91개(NONE 30/UP 18/RIGHT 18/DOWN 13/LEFT 12), 테스트 24개.
- 모델: Dense 20→10, cycles 30, learning rate 0.0005(Studio 기본값).

결과(validation): 정확도 52.6%, loss 11.30.

| 클래스 | DOWN | LEFT | NONE | RIGHT | UP |
|---|---:|---:|---:|---:|---:|
| F1 | 0.29 | 0.50 | 0.33 | 0.44 | 1.00 |

- DOWN의 80%가 RIGHT로 오분류.

## 실험 3 — 1D conv 1층 + 입력 스케일 조정

- 구조: Reshape(6열) → 1D conv/pool(8 filters, kernel 3) → Flatten → Dense(5). 데이터는 실험 2와 동일.
- 스케일 1.0(기본): 정확도 63.2%, loss **12.73**. DOWN F1 0.75, RIGHT F1 0.29, NONE 75%가 LEFT로 오분류.
- **loss가 비정상적으로 높은 원인 분석**: 가속도(약 ±10)와 자이로(수백 deg/s)의 단위 스케일 차이가 커서 logits가 커지고, softmax의 exp() 계산이 불안정해져 틀린 예측의 loss가 극단적으로 커짐.
- Raw data 블록의 Scale axes를 0.01로 조정 후 재학습: loss **0.94**로 급락, 정확도는 63.2%로 동일(검증 19개 기준 윈도우 1~2개 차이는 재배열).

결과(validation, 스케일 0.01): 정확도 63.2%, loss 0.94.

| 클래스 | DOWN | LEFT | NONE | RIGHT | UP |
|---|---:|---:|---:|---:|---:|
| F1 | 0.75 | 0.40 | 0.55 | 0.57 | 1.00 |

- 해석 한계: 검증 윈도우가 약 19개(클래스당 3~6개)뿐이라 수 퍼센트 차이는 통계적으로 거의 의미 없음.

## 실험 4 — DOWN/RIGHT 혼동 원인 점검(로컬, 읽기 전용)

- DOWN과 RIGHT가 Dense 기준선에서 서로 혼동되는 것을 보고 로컬에서 파형을 직접 비교.
- DOWN(6개): 자이로 Y축 에너지 비율 83~97%, 음→양 순서.
- RIGHT(7개): X/Z축이 섞임(Z 43~64%), 음→양 순서.
- 클래스 평균 자이로 파형 코사인 유사도: DOWN-RIGHT **-0.23**(비슷하지 않음), UP-DOWN -0.85.
- 결론: "시간 패턴이 비슷해서 헷갈린다"는 가설은 기각. 신호 자체는 구분되므로, 당시 모델·데이터 양의 한계로 판단.

## 실험 5 — 2차 세션 녹화 및 완료 시점 재계산

- `tools/record-gesture-samples.js` 추가(시리얼 녹화, `edge-impulse-cli` 번들 `serialport` v8 재사용).
- 2차 세션(`data/sessions/2026-10-06T04-12-41/`) 40개 녹화. 축/패턴 스크리닝으로 `raw_up.1`(주축이 다른 9개와 다름), `raw_left.9`(주축 불명확), `raw_right.5`(최대 자이로 1038 deg/s, ±1000 포화 범위 초과)를 이상치로 제외, 37개로 진행.
- `return_pose_offset`(시작-종료 중력 방향 12도 이상 차이) 조건을 AUTO/REVIEW 판정에서 제거: 제스처의 최종 자세가 시작 자세와 같아야 할 근거가 없다고 판단.
  - 조건 제거 전/후: 기존 40개 AUTO 30→31, 신규 37개 AUTO 14→23.
- 남은 REVIEW 14개 사유: `early_motion`(LEFT/RIGHT에 집중, 녹화 스크립트에 카운트다운이 없어 급하게 시작했을 가능성), `late_completion`(DOWN에 집중, 3초가 빠듯했을 가능성), `no_180ms_settle` 2개. 원인은 가설이며 파형으로 확인하지 않음.

## 실험 6 — 두 세션 합산 재학습

- 두 세션 AUTO 합산(UP 17/DOWN 11/LEFT 13/RIGHT 13 원본 샘플) → 학습 145개(NONE 30/UP 39/DOWN 25/LEFT 24/RIGHT 27), 테스트 36개.
- 구조는 실험 3과 동일(Reshape+1D conv 1층, 스케일 0.01).

결과(validation): 정확도 **75.9%**, loss **0.82**.

| 클래스 | DOWN | LEFT | NONE | RIGHT | UP |
|---|---:|---:|---:|---:|---:|
| F1 | 0.40 | 0.80 | 0.67 | 0.83 | 0.95 |

- 실험 3 대비 정확도 63.2%→75.9%, loss 0.94→0.82로 개선. 구조·스케일을 고정하고 데이터만 늘렸으므로 데이터 부족이 실제 요인 중 하나였다는 근거가 됨.
- 한계: Studio의 train/validation 분할이 두 세션을 섞어서 나눴을 가능성이 높아, 이 수치는 "새로운 조건에서의 일반화"가 아니라 "더 다양한 데이터 내부 분할"에 가까움. DOWN F1이 0.40으로 가장 약함(25%는 NONE, 25%는 UP으로 분산).

## 실험 7 — 데이터 증강(5배) 및 재학습, validation-testing 괴리 발견

- `tools/augment-gesture-windows.js`(사용자가 별도 에이전트 자문으로 작성, 업로드 전 에이전트가 직접 검증: 테스트셋 바이트 동일/학습 원본 바이트 동일/겹치는 윈도우 동일 시각 노이즈 공유/`sample_id` 기준 train-test 누수 없음/전부 160행 확인).
- 방식: 학습 윈도우마다 원본 1개 + 변형 4개(`sample_id`당 하나의 강체 회전 ±5도, 랜덤 축 + 가우시안 노이즈: 가속도 std 0.02 m/s², 자이로 std 0.2 deg/s, ±3σ 클리핑). 테스트는 증강하지 않음.
- 업로드: 학습 725개(NONE 150/UP 195/DOWN 125/LEFT 120/RIGHT 135), 테스트 36개(원본 유지).

결과(validation): 정확도 **98.6%**, loss **0.14**.

결과(Model testing, 증강되지 않은 testing 36개로 평가): 정확도 **44.44%**.

| 클래스 | DOWN | LEFT | NONE | RIGHT | UP |
|---|---:|---:|---:|---:|---:|
| F1 | 0.80 | 0.20 | 0.33 | 0.00 | 0.94 |

- RIGHT F1 0.00(9개 전부 NONE 또는 `uncertain`으로 오분류). LEFT는 절반이 `uncertain`.
- **핵심 발견**: validation 98.6%는 신뢰할 수 없다고 판단. 근거: (1) 같은 원본의 variant 5개가 모두 `training` 카테고리에 있고 Studio의 기본 train/validation 분할은 무작위 샘플 단위라서, 같은 원본의 거의 동일한 변형이 train과 validation 양쪽에 나뉘어 들어갔을 가능성이 높음. (2) loss와 정확도의 변화 폭(0.82→0.14, 75.9%→98.6%)이 데이터가 5배 늘어난 것만으로 설명하기엔 과함. (3) 증강되지 않은 독립 testing set 성능(44.44%)과 큰 괴리.
- **아직 확인 못한 것**: 증강 전 모델(실험 6)을 같은 testing 36개로 평가한 적이 없어서, 44.44%가 "증강이 성능을 악화시켰다"는 뜻인지 "증강 전부터 실제 일반화 성능이 이 정도였는데 validation이 부풀려 보여줬을 뿐"인지 아직 구분할 수 없음. 비교 실험 필요(실험 6 데이터를 재업로드 → Model testing).

## 실험 8 — 구조 증설(conv 2~3층 + dropout), GAP 시도와 폐기

데이터는 실험 7과 동일(증강본, 학습 725개/testing 36개, 원본 유지).

### 8a. conv 2층 + dropout + Dense(32)

- 구조: `Reshape(6) → Conv1D(16,k5,same)+MaxPool(2)+Dropout(0.25) → Conv1D(32,k5,same)+MaxPool(2)+Dropout(0.25) → Flatten(1280) → Dense(32)+Dropout(0.3) → Dense(5,softmax)`.
- 결과(Model testing, testing 36개): 정확도 **63.89%**.

| 클래스 | DOWN | LEFT | NONE | RIGHT | UP |
|---|---:|---:|---:|---:|---:|
| F1 | 0.91 | 0.55 | 0.37 | 0.46 | 1.00 |

- 실험 7의 1층 구조(testing 44.44%) 대비 +19.45%p. RIGHT F1이 0.00→0.46으로 회복. 구조가 얕았다는 지적이 맞았다는 근거.
- 파라미터 추정: Dense(32) 직전 Flatten(1280)이 전체의 약 93%(40,992/약 44,000)를 차지. Dense 직전 크기를 줄이는 게 다음 개선 지점으로 식별됨.

### 8b. GlobalAveragePooling1D(GAP) 시도 — 폐기

- Studio 기본 UI의 레이어 목록에 GAP이 없어, "커스텀 러닝 블록" 안내를 보고 에이전트가 조사. Custom learning block(Docker+CLI 필요, 타 프레임워크/사전가중치용)과 Expert Mode(Studio 안에서 Keras 코드 직접 편집, 추가 도구 불필요)를 구분해 Expert Mode로 충분하다고 안내.
- 사용자가 공유한 Studio 자동생성 Expert Mode 코드에 이미 `GlobalAveragePooling1D()` → `Conv1D(32, kernel=1, activity_regularizer=l1(1e-5))`(Dense와 수학적으로 동일하게 표현한 패턴) 구성이 들어있었음.
- 코드 검토로 버그 2개 발견: (1) import 문에 `GlobalAveragePooling1D` 누락(`NameError` 가능), (2) GAP 출력(2D)에 바로 `Conv1D`(3D 입력 요구)를 적용해 차원 불일치 가능성. `Conv1D(32,1,...)`를 `Dense(32,...)`로 대체하도록 수정 제안.
- 사용자가 GAP 버전으로 실제 학습: **검증 정확도 소폭 감소, Model testing 정확도 대폭 감소**(정확한 testing 수치는 기록되지 않음, 8a보다 뚜렷이 낮았다고 보고됨).
- 사용자의 1차 가설("중간 Dense가 계산량을 많이 차지해서")은 파라미터 계산으로 반박: GAP(32) 뒤 Dense(32)는 1,056개 파라미터뿐으로 8a의 40,992개 대비 97% 이상 적어, 계산량 문제로 보기 어려움.
- 에이전트 해석: GAP은 전체 윈도우에 대한 채널별 평균이라 시간 순서·위치 정보를 완전히 버린다. 이 태스크의 신호는 (1) 방향 판정이 순서 의존적(예: DOWN은 자이로 Y 음→양, UP은 양→음)이고 (2) 양성 구간이 1600 ms 중 완료 직후 150 ms로 매우 짧아 긴 비활성 구간에 평균이 희석되는 구조라, GAP의 "위치 불변성" 전제와 맞지 않아 과소적합을 유발했을 것으로 추정. "학습도 평가도 전부" 나빠졌다는 보고는 과적합이 아니라 과소적합 신호와 일치.
- 결론: GAP 폐기.

### 8c. conv 3층(중간 Dense 제거)

- 구조: `Reshape(6) → Conv1D(16,k5,same)+MaxPool(2)+Dropout(0.2) → Conv1D(32,k5,same)+MaxPool(2)+Dropout(0.25) → Conv1D(32,k3,same)+MaxPool(2)+Dropout(0.25) → Flatten(640) → Dropout(0.3) → Dense(5,softmax)`. GAP 대신 conv를 한 층 더 쌓아 시간 정보를 유지하면서 Flatten 직전 크기(1280→640)를 줄이고, 중간 Dense(32)는 제거.
- 결과(Model testing, testing 36개): 정확도 **66.67%**. 사용자 보고로 validation은 8a 대비 소폭 감소.

| 클래스 | DOWN | LEFT | NONE | RIGHT | UP |
|---|---:|---:|---:|---:|---:|
| F1 | 1.00 | 0.73 | 0.27 | 0.46 | 1.00 |

- 8a 대비 +2.78%p. DOWN·LEFT 개선, NONE 악화(0.37→0.27, `uncertain` 비중 증가), **RIGHT는 0.46으로 변화 없음**.
- 해석 한계: testing 36개에서 2.78%p는 윈도우 1개 차이 수준이라 통계적으로 유의하다고 보기 어려움. validation이 8a보다 낮은데 testing은 더 높다는 점은, validation을 신뢰하기 어렵다는 실험 7의 결론을 다시 뒷받침.
- RIGHT→NONE 혼동(66.7%)이 1층→2층→3층 구조 변화에도 일관되게 남아 있음: 구조보다 RIGHT 신호 자체의 약함(과거 raw_right 점검에서 최대 자이로가 다른 방향보다 작았음, 약 86~347 deg/s)이 원인일 가능성이 구조 문제보다 커 보임.

## 현재 열린 문제

1. **구조 증설은 효과가 있었지만 수익체감 구간**: 1층(44.44%) → 2층+dropout(63.89%) → 3층+GAP 제거(66.67%). 처음 한 번의 개선 폭(+19.45%p)에 비해 두 번째(+2.78%p)는 testing 36개 기준 노이즈 수준이라 추가 구조 미세조정의 기대 효과는 작아 보임.
2. **RIGHT→NONE 혼동이 구조 변화로 해결되지 않음**(F1 0.46에서 정체). 데이터/신호 문제일 가능성이 구조 문제보다 크다고 판단됨. RIGHT 데이터 보강 또는 class weight 조정이 다음 후보.
3. **GAP은 이 태스크에 부적합하다고 잠정 결론**(실험 8b). 시간 순서·짧은 피크 신호를 쓰는 분류 문제에서는 Flatten 계열이 더 적합. 아직 시도하지 않은 대안: GlobalMaxPooling1D(평균 대신 최댓값이라 짧은 피크가 희석되지 않음, 순서 정보는 여전히 버림).
4. **validation 대 testing 괴리**: 실험 7(증강 variant 누수 가설)뿐 아니라 실험 8c(구조만 바꿨는데 validation↓·testing↑)에서도 반복 관찰됨. Studio validation 수치는 구조·데이터 변경과 무관하게 판단 근거로 쓰지 않고, 매번 Model testing(testing 36개)으로 확인하는 것으로 운영 방침을 굳힘. 다만 testing 36개 자체도 작아 수 %p 차이는 신뢰 구간 밖일 수 있음 — 테스트셋 확대가 필요.
5. **완료 시점 기반 라벨링 대 패턴 기반 라벨링**: 사용자가 "완료 전 구간도 패턴이 보이면 해당 방향으로 라벨링하고 후처리로 완료 시 발행"하는 대안을 제시(2026-10-06). 이는 애초 확정안(`연속 IMU → sliding window → TinyML 5클래스 → 얇은 후처리 → GestureEvent`)에 가깝다. 장점은 라벨링 단순화와 양성 데이터 증가(현재 NONE:방향 비율 약 50:1의 극단적 불균형 완화), 단점은 복귀 구간 라벨 정책(같은 방향/반대 방향/NONE)에 따라 오인식·중복 발행 위험이 달라진다는 점. 결정 보류 상태.
6. 모든 결과는 윈도우 단위 분류 정확도이며, 연속 스트림에서의 이벤트 검출률·지연·false positive/hour는 아직 전혀 측정하지 않았다.

## 파일 경로 참고

- 어노테이션: `data/annotations/gesture-completions.csv`(원격, 1122630), `data/annotations/gesture-completions-session-2026-10-06.csv`(2차 세션 로컬)
- 윈도우: `data/windows/`(증강 전, 145 train/36 test), `data/windows-augmented-5x/`(증강 후, 725 train/36 test), `data/windows-augmented-5x/augmentation.json`(증강 파라미터)
- 2차 세션 원본: `data/sessions/2026-10-06T04-12-41/`
- 스크립트: `tools/suggest-gesture-completions.js`, `tools/export-gesture-windows.js`, `tools/record-gesture-samples.js`, `tools/augment-gesture-windows.js`, `tools/compare-window-lengths.js`
- Edge Impulse 프로젝트: 원시 데이터 `RingPilot`(1122630), 윈도우 학습용 `RingPilot-Windows`(1129540)
