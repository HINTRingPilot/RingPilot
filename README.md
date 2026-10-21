# RingPilot

침대에서 Android 스마트폰을 조작하기 위한 검지 착용형 스마트링 리모컨 프로토타입.
엄지 스틱으로 포인터와 클릭을 제어하고, 향후 IMU와 TinyML로 손가락 제스처를 인식하는 것을 목표로 합니다.

## 현재 구현

XIAO nRF52840 Sense의 Arduino/Bluefruit 펌웨어로 BLE HID 마우스와 Custom GATT 서비스를 제공합니다.
Android 최소 앱은 AccessibilityService로 다른 앱 위에 스와이프를 전달하고, Custom GATT의 `SWIPE_UP` / `SWIPE_DOWN` 명령을 수신합니다.
현재 스와이프 입력은 USB 시리얼 명령으로 대체합니다. Edge Impulse용 100 Hz IMU 6축 출력과 Studio 장치 연결까지 검증했으며, 라벨 데이터 수집·학습·TinyML 통합은 아직 진행 전입니다.

```text
PC USB 시리얼 → XIAO → BLE HID → Android 포인터/클릭
                    └→ Custom GATT → RingPilot 앱 → 화면 스와이프
```

## 검증 환경 및 결과

- 보드: Seeed XIAO nRF52840 Sense
- 코어: Seeed nRF52 Boards(non-mbed) 1.1.13
- 휴대폰: Galaxy S10 / Android 12
- 확인 완료: 4방향 이동·클릭, HID와 GATT 알림 동시 동작, USB 전원 재연결 및 휴대폰 Bluetooth OFF/ON 후 기능 복구
- nRF Connect 강제 종료·재실행: 수동 CONNECT 후 별도 알림 버튼 조작 없이 수신 복구
- Android 앱: Galaxy S10에서 접근성 앱 자체 스와이프와 BLE 상하좌우 스와이프 명령을 실동작 확인

짧은 기능 시험 결과이며, 장시간 안정성·복구 시간·패킷 누락률·소비전력은 측정하지 않았습니다.

## 실행

1. [설치 안내](docs/설치안내.md)에 따라 Arduino 환경을 준비합니다.
2. [ble_poc.ino](firmware/ble_poc/ble_poc.ino)를 Sense 보드에 업로드합니다.
3. Android에서 `SmartRing-PoC`를 페어링합니다.
4. USB 시리얼 모니터(115200 baud)에서 WASD로 이동, C로 클릭, U/J/L/R로 위·아래·왼쪽·오른쪽 스와이프 명령, ?로 상태를 조회합니다.
5. 전체 통신 시험은 [BLE 테스트 안내](docs/BLE테스트.md)를 따릅니다. 당시의 스와이프 시험 화면은 현재 앱에서 제거됐습니다.

제스처 데이터를 무선으로 모을 때는 [imu_ble_stream.ino](firmware/imu_ble_stream/imu_ble_stream.ino)를 업로드하고 [Android 수집 앱](android/README.md)을 사용합니다.

모델 학습·평가는 로컬 Python(`ml/`)에서 진행합니다. 계획은 [학습 계획](docs/TrainingPlan.md), 실험 기록은 [BLE v1 실험](docs/experiments/ble-v1/README.md)에 있습니다.

## 문서

- [기획서 원안](기획서%20원안.txt)
- [진행 기록 및 검증 근거](docs/진행기록.md)
- [Windows 개발환경 설치](docs/설치안내.md)
- [Android 수집 앱](android/README.md)
- [BLE 테스트 안내](docs/BLE테스트.md)
- [제스처 인식 구조 제안](docs/제스처인식구조안.md)
- [모델 아키텍처](docs/ModelArchitecture.md)
- [학습·평가 계획](docs/TrainingPlan.md)
- [BLE v1 모델 실험 기록](docs/experiments/ble-v1/README.md)
- [모델 개발·실험 기록 (조현준)](docs/진행기록_조현준.md)
- [하드웨어 제작 보고서](docs/HardwareBuild.md)
- [시리얼 테스트 로그](docs/logs/)

현재 개발 후보는 2층 CNN+증강(B)이며 최종 선정 전입니다. 남은 단계는 연속 자료 검증(실험 7b)과 int8·보드 검증(실험 8)입니다.
펌웨어 `.build/`, Android 빌드 결과와 로컬 SDK `.tools/`는 저장소에서 제외합니다.
