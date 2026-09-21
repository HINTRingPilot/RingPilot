# RingPilot

침대에서 Android 스마트폰을 조작하기 위한 검지 착용형 스마트링 리모컨 프로토타입.
엄지 스틱으로 포인터와 클릭을 제어하고, 향후 IMU와 TinyML로 손가락 제스처를 인식하는 것을 목표로 합니다.

## 현재 구현

XIAO nRF52840 Sense의 Arduino/Bluefruit 펌웨어로 BLE HID 마우스와 Custom GATT 서비스를 제공합니다.
현재 방향 입력은 USB 시리얼 명령으로 대체하며, 스틱·AI·전용 Android 앱은 아직 구현하지 않았습니다.

```text
PC USB 시리얼 → XIAO → BLE HID → Android 포인터/클릭
                    └→ Custom GATT → nRF Connect 테스트 카운터 수신
```

## 검증 환경 및 결과

- 보드: Seeed XIAO nRF52840 Sense
- 코어: Seeed nRF52 Boards(non-mbed) 1.1.13
- 휴대폰: Galaxy S10 / Android 12
- 확인 완료: 4방향 이동·클릭, HID와 GATT 알림 동시 동작, USB 전원 재연결 및 휴대폰 Bluetooth OFF/ON 후 기능 복구
- nRF Connect 강제 종료·재실행: 수동 CONNECT 후 별도 알림 버튼 조작 없이 수신 복구

짧은 기능 시험 결과이며, 장시간 안정성·복구 시간·패킷 누락률·소비전력은 측정하지 않았습니다.

## 실행

1. [설치 안내](docs/설치안내.md)에 따라 Arduino 환경을 준비합니다.
2. [ble_poc.ino](firmware/ble_poc/ble_poc.ino)를 Sense 보드에 업로드합니다.
3. Android에서 `SmartRing-PoC`를 페어링합니다.
4. USB 시리얼 모니터(115200 baud)에서 WASD로 이동, C로 클릭, ?로 상태를 조회합니다.
5. [BLE 테스트 안내](docs/BLE테스트.md)에 따라 GATT 알림과 복구 동작을 확인합니다.

## 문서

- [기획서 원안](기획서%20원안.txt)
- [진행 기록 및 검증 근거](docs/진행기록.md)
- [시리얼 테스트 로그](docs/logs/)

다음 단계는 입력 스틱, Android 제스처 제어, IMU 데이터 수집 및 TinyML 등으로 확장하는 것입니다.
빌드 산출물 `.build/`는 저장소에서 제외합니다.
