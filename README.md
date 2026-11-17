# RingPilot

**소개 페이지(시연 영상 포함): https://hintringpilot.github.io/RingPilot/**

검지에 끼는 반지로 스마트폰을 조작하는 프로토타입입니다. 침대에 누운 채로 폰을 다루려고 만들었습니다.

반지 안의 IMU가 손가락을 위·아래·좌·우로 까딱이는 동작을 보드에서 직접 인식하고(TinyML), 폰 앱이 그 결과를 받아 화면을 스와이프합니다. 반지에 달린 5방향 스위치로는 화면에 커서를 띄워 탭할 수 있습니다.

연구와 포트폴리오용이라 실제 배포 수준의 검증은 하지 않았습니다.

## 동작 방식

```text
반지 (XIAO nRF52840 Sense)                                     폰 (Android 앱)
IMU 100 Hz → 온라인 영점 → TCN 판정(50 ms마다) → 발행 ──BLE──→ GestureRouter → 접근성 스와이프
                                                  └ LED
5방향 스위치 → 방향 상태·클릭 수 ─────────────────────BLE──→ PointerController → 커서 이동·탭
```

제스처

- 위/아래: 위·아래로 스와이프합니다. 쇼츠 넘길 때 씁니다.
- 좌/우: 상하 모드와 좌우 모드를 바꿉니다. 좌우 모드에서는 위가 왼쪽, 아래가 오른쪽 스와이프입니다.

스위치

- 방향을 누르고 있으면 커서가 일정한 속도로 움직입니다. 커서는 평소 숨어 있다가 마지막 입력 1.5초 뒤 다시 사라집니다.
- 센터를 짧게 누르면 커서 위치를 탭합니다. 일시정지 중일 때는 다시 켜집니다.
- 센터 0.5초는 일시정지, 2초는 전원 끄기입니다. 일시정지는 제스처 인식만 멈추고, 그동안에도 방향 스위치로 커서는 움직일 수 있습니다.

커서 기능은 코드와 빌드까지만 됐고 실제 반지와 폰에서는 아직 확인하지 않았습니다. 방향 핀 매핑도 미확인입니다.

모델은 자이로 3축과 회전각 3축을 입력으로 받는 작은 TCN입니다. 파라미터 4,421개, 입력 길이 1.6초이고, 보드에서 한 번 판정하는 데 약 21 ms가 걸립니다.

## 폴더

| 폴더 | 내용 |
|---|---|
| [firmware/](firmware/README.md) | 반지 펌웨어 `gesture_infer`. 앱과 주고받는 BLE 전송 로직은 `libraries/RingPilotTransport`, 그 PC 테스트는 `tests/`. 수집 펌웨어와 PC 검증 도구는 `dev/` |
| [android/](android/README.md) | 폰 앱(리모컨). 데이터 수집과 실사용 기록 화면은 `dev` 패키지 |
| [ml/](ml/) | Python(TensorFlow) 학습·평가, C 변환, Python과 C 결과 비교. 테스트는 `ml/tests/` |
| [tools/](tools/) | 폰 기록 가져오기(`pull-phone-sessions.js`), 수집 클립 주석 도구(Node.js), 전체 검사 스크립트(`verify-ecc-fixes.ps1`) |
| [data/](data/) | 수집 세션 원본, 동작 시점 주석, 교차검증 분할 |
| [docs/](docs/) | 진행 기록, 실험 결과, 계획, 코드 리뷰, 시행착오 |

## 실행

1. [설치 안내](docs/설치안내.md)를 따라 Arduino, Python, Android 빌드 환경을 준비합니다(`setup.ps1`).
2. [펌웨어 안내](firmware/README.md)대로 `firmware/gesture_infer`를 반지에 올립니다. 공유 라이브러리를 쓰기 때문에 컴파일할 때 `--libraries firmware/libraries`가 필요합니다.
3. [앱 안내](android/README.md)대로 APK를 빌드해 설치합니다. APK는 저장소에 없어서 직접 빌드해야 합니다. 폰에서 `RingPilot-IMU`를 페어링하고 앱에서 스와이프 제어를 켜면 됩니다.
4. 모델을 다시 학습하거나 평가하려면 `ml/v2_return.py`(학습·채점)와 `ml/v2_export_c.py`(C 헤더 내보내기, 일치 확인)를 씁니다.

## 테스트

```powershell
ml/.venv/Scripts/python.exe -m unittest discover -s ml/tests -t ml
.\android\tests\run-sidecar-tests.ps1
.\firmware\tests\run-transport-tests.ps1
```

차례대로 ML, 앱 로직(JDK만 있으면 됨), 펌웨어 전송 로직(g++ 필요) 테스트입니다. ML의 C 비교 테스트는 `RINGPILOT_CC`에 C 컴파일러를 지정해야 돌아갑니다.

`tools/verify-ecc-fixes.ps1 -SpaceCompilerPath <C 컴파일러 경로>`는 위 테스트와 앱 빌드, `-ArduinoCli`를 주면 펌웨어 빌드까지 한 번에 돌리고, 하나라도 실패하면 바로 멈춥니다.

## 확인한 것

- 오프라인: 자세(세션)별로 나눈 교차검증에서 단일 동작 정검출이 평균 약 97%입니다. 클립 단위 결과라 실제 연속 사용 성능과는 다릅니다. 표는 [BLE v2 실험](docs/experiments/ble-v2/README.md)에 있습니다.
- Python과 C: 같은 입력에서 점수 차이가 최대 1e-6 수준이고, 연속 스트림에서 발행도 같습니다(`ml/v2_export_c.py check`).
- 실사용: 사용자 1명이 1~2분씩 두 번 써 봤습니다. 두 번째에는 동작 후보 49개 중 46개가 제대로 발행됐고, 써 본 느낌은 "끊김 없이 잘 됨"이었습니다([field-02](docs/experiments/ble-v2/field-02/README.md)). 정식 연속 인식률과 시간당 오발행은 재지 않았습니다.
- 코드 리뷰 수정(2026-11-12): 리뷰에서 나온 8건을 고쳤습니다. PC 테스트(앱 274개 검사, Python 90개, 펌웨어 전송 8개 시나리오)와 에뮬레이터에서는 확인했지만, 실제 반지와 폰에서는 아직 다시 보지 않았습니다. 자세한 내용은 [수정 결과](docs/reviews/2026-11-12-ecc-fixes-results.md)에 있습니다.
- 재지 않은 것: 배터리 지속 시간, BLE 최대 거리, 소비 전류.

## 문서

처음 보는 분은 진행기록 요약 → 모델 구조 → 시행착오 정리 순서를 권합니다.

| 문서 | 내용 |
|---|---|
| [진행기록 요약](docs/진행기록요약.md) | 전체 과정을 9단계로 간추린 것, 현재 상태 |
| [모델 구조](docs/모델구조.md) | 지금 반지에 들어간 모델, 입력, 학습, 발행 규칙 |
| [시행착오 정리](docs/시행착오정리.md) | 모델 개선 과정의 시도·원인·배운 점 |
| [하드웨어 제작 보고서](docs/HardwareBuild.md) | 배선, 스위치, 배터리, 전원 |
| [데이터 큐레이션 기록](docs/데이터큐레이션기록.md) | 데이터셋에서 뺀 것과 이유 |
| [BLE v2 실험](docs/experiments/ble-v2/README.md) | 실험별 조건과 결과 |
| [Android 앱](android/README.md), [펌웨어](firmware/README.md) | 빌드와 코드 구조 |
| [Windows 개발환경 설치](docs/설치안내.md) | 펌웨어·앱·학습 환경 설치 |
| [남은 할 일](docs/TODO.md) | 다음 작업과 보류 항목 |
| [진행기록](docs/진행기록.md) | 원본 작업 일지(모든 조건·수치·검증 근거) |

과거 기록:

- [기획서 원안](기획서%20원안.txt)
- [보관 문서](docs/archive/README.md): 10-25 회고, 초기 모델 설계·학습 계획, 설계 제안, BLE PoC 시험 기록
- [BLE v1 모델 실험 기록](docs/experiments/ble-v1/README.md), [모델 개발·실험 기록 (조현준)](docs/진행기록_조현준.md)
- [코드 리뷰 (2026-11-12)](docs/reviews/2026-11-12-ecc-code-review.md)
- [시리얼 테스트 로그](docs/logs/)

## 참고

BLE v1 실험(1~7a)은 테스트용 세션으로 진행했고, 2026-10-23에 그 세션과 주석, 분할, 결과 파일을 지웠습니다. 문서는 남아 있습니다. 2026-10-25에 자이로 ±2000 dps에 맞춘 앱으로 자세별 5세션을 새로 모았고, 원본 336개로 기준선 보정, NONE 배분 비교, 발행 시점 진단까지 했습니다. 결과와 한계는 [개발 진행 요약](docs/archive/개발진행요약_2026-10-25.md)에 있습니다.

펌웨어 `.build/`, Android 빌드 결과, 로컬 SDK `.tools/`는 저장소에 올리지 않습니다.
