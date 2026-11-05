# RingPilot

침대에 누워 스마트폰을 조작하기 위한 검지 반지형 제스처 리모컨 프로토타입이다. 반지 안 IMU로 손가락의 위·아래·좌·우 까딱임을 보드에서 직접 인식하고(TinyML), 휴대폰 앱이 그 결과를 화면 스와이프로 바꾼다. 연구·포트폴리오 목적이며 실배포 검증은 범위 밖이다.

## 동작 구조

```text
반지(XIAO nRF52840 Sense)                                   휴대폰(Android 앱)
IMU 100 Hz → 온라인 영점 → TCN 판정(50 ms마다) → 발행 ──BLE──→ GestureRouter → 접근성 스와이프
                                                  └ LED
```

- 위·아래 제스처는 위·아래 스와이프(쇼츠 넘기기 등), 좌우 제스처는 상하·좌우 모드 전환이다. 좌우 모드에서는 위 = 왼쪽, 아래 = 오른쪽 스와이프다.
- 반지 스위치: 짧게 누르면 일시정지 해제, 0.5초 누르면 일시정지, 2초 누르면 전원 끄기.
- 모델: 자이로 3 + 회전각 3채널을 받는 TCN(4,421 파라미터, 1.6초 창). 판정 한 번 약 21 ms(보드 측정).

## 폴더

| 폴더 | 내용 |
|---|---|
| [firmware/](firmware/README.md) | 반지 펌웨어. 지금 쓰는 것은 `gesture_infer`, 데이터 수집용은 `imu_ble_stream` |
| [android/](android/README.md) | 휴대폰 앱(리모컨, 개발용 빌드는 데이터 수집·실사용 기록 포함) |
| [ml/](ml/) | 학습·평가(Python, TensorFlow), C 변환과 Python·C 일치 확인 |
| [tools/](tools/) | 폰 기록 가져오기(`pull-phone-sessions.js`), 수집 클립 주석 도구(Node.js) |
| [data/](data/) | 수집 세션 원본, 동작 시점 주석, 교차검증 분할 |
| [docs/](docs/) | 진행기록, 실험 결과, 계획서, 시행착오 정리 |

## 실행

1. [설치 안내](docs/설치안내.md)에 따라 Arduino·Python·Android 빌드 환경을 준비한다(`setup.ps1`).
2. [펌웨어 안내](firmware/README.md)대로 `firmware/gesture_infer`를 반지에 올린다.
3. [앱 안내](android/README.md)대로 APK를 빌드·설치하고, `RingPilot-IMU`를 페어링한 뒤 앱에서 스와이프 제어를 켠다.
4. 모델을 다시 학습하거나 평가할 때는 `ml/v2_return.py`(학습·채점), `ml/v2_export_c.py`(C 헤더 내보내기·일치 확인)를 쓴다. 테스트는 `ml/.venv/Scripts/python.exe -m unittest discover -s ml`.

## 확인한 것

- 오프라인: 세션(자세)을 나눈 교차검증에서 단일 동작 정검출 평균 약 97%(클립 단위, 실제 연속 사용 성능 아님). 자세한 표는 [BLE v2 실험](docs/experiments/ble-v2/README.md).
- Python과 C: 같은 입력에서 점수 최대 오차 1e-6 수준, 연속 스트림 발행 동일(`ml/v2_export_c.py check`).
- 실사용(사용자 1명, 약 1~2분 기록 2회): 두 번째 시험에서 동작 후보 49개 중 46개 정상 발행, 체감 "끊김 없이 잘 됨". [field-02](docs/experiments/ble-v2/field-02/README.md). 정식 연속 인식률·시간당 오발행은 측정하지 않았다.
- 미측정: 배터리 지속 시간, BLE 최대 거리, 소비 전류.

## 문서

- [개발 진행 요약 및 실험 회고 — 2026-10-25](docs/개발진행요약_2026-10-25.md)
- [기획서 원안](기획서%20원안.txt)
- [남은 할 일](docs/TODO.md)
- [시행착오 정리](docs/시행착오정리.md)
- [진행 기록 및 검증 근거](docs/진행기록.md)
- [Windows 개발환경 설치](docs/설치안내.md)
- [Android 앱](android/README.md)
- [BLE 테스트 안내(초기 ble_poc)](docs/BLE테스트.md)
- [제스처 인식 구조 제안](docs/제스처인식구조안.md)
- [모델 아키텍처](docs/ModelArchitecture.md)
- [학습·평가 계획](docs/TrainingPlan.md)
- [BLE v1 모델 실험 기록](docs/experiments/ble-v1/README.md)
- [모델 개발·실험 기록 (조현준)](docs/진행기록_조현준.md)
- [하드웨어 제작 보고서](docs/HardwareBuild.md)
- [시리얼 테스트 로그](docs/logs/)

BLE v1 실험(1~7a)은 테스트용 세션으로 진행했고, 2026-10-23에 그 세션과 주석·분할·결과 파일을 삭제했습니다(문서는 보존). 2026-10-25에는 자이로 ±2000 dps에 맞춘 앱으로 자세별 5세션을 다시 수집했고, 사용 원본 336개로 기준선 보정·NONE 배분 비교·발행 시점 진단까지 진행했습니다. 결과와 한계는 [개발 진행 요약](docs/개발진행요약_2026-10-25.md)에 정리했습니다. 현재 목적은 연구·포트폴리오이며 실배포 검증은 필수 범위가 아닙니다.
펌웨어 `.build/`, Android 빌드 결과와 로컬 SDK `.tools/`는 저장소에서 제외합니다.
