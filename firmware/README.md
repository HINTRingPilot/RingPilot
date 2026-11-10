# 펌웨어

보드: Seeed XIAO nRF52840 Sense(Seeed nRF52 Boards non-mbed 1.1.13, FQBN `Seeeduino:nrf52:xiaonRF52840Sense`). 설치는 [설치 안내](../docs/설치안내.md).

개발용은 `dev/` 아래에 둔다. 사용자에게 들어가는 것은 `gesture_infer`(스트림을 끈 기본 빌드)뿐이다.

| 스케치 | 용도 |
|---|---|
| [gesture_infer/](gesture_infer/) | **지금 쓰는 펌웨어.** 보드 안 제스처 판정·발행. 개발 빌드는 IMU 원시값 스트림도 보낸다 |
| [dev/imu_ble_stream/](dev/imu_ble_stream/) | (개발용) 학습 데이터 수집용. 추론 없이 IMU만 보낸다(BLE 형식이 같아 같은 앱이 붙는다) |
| [dev/gesture_host/](dev/gesture_host/) | (개발용) 보드에 올리지 않는다. 판정 코어를 PC에서 빌드해 Python과 비교·시간 측정(`ml/v2_export_c.py`, `ml/v2_latency.py`가 쓴다) |

초기 하드웨어 확인용 시험 스케치(`ble_poc`, `battery_test`, `power_off_test`, `switch_test`)는 2026-11-05에 지웠다. 커밋 `05c4cb3` 이전 이력에 있다.

## gesture_infer 구조

```text
imu_sampler(읽기 태스크, 10 ms) → 판정 대기열 → gesture_loop → gesture_runtime → 발행 → ble_link(제스처 알림), controls(LED)
                                └(개발 빌드만) dev/imu_stream: 전송 대기열 → IMU 스트림
controls: 센터 스위치(클릭·일시정지·전원 끄기)와 LED → pointer: 방향 스위치 상태·클릭 알림(커서는 앱이 그린다)
```

| 파일 | 맡는 일 |
|---|---|
| `gesture_infer.ino` | setup·loop, 시리얼 명령(`?` 상태, `l` 통계, `r` 초기화) |
| `src/imu_sampler` | IMU 설정, FreeRTOS 읽기 태스크, 잠금 없는 판정 대기열, 읽기 통계 |
| `src/gesture_loop` | 대기열에서 자이로를 꺼내 판정 코어에 넣기(빈 슬롯 채우기), 발행 내보내기, 판정 시간 측정 |
| `src/ble_link` | BLE 서비스·특성, 연결 파라미터, 상태·제스처 알림 대기열 |
| `src/dev/imu_stream` | (개발 빌드만) 전송 대기열과 IMU 원시값 스트림 패킷 |
| `src/build_config.h` | 빌드 설정. `RINGPILOT_IMU_STREAM`(기본 0 = 사용자 빌드) |
| `src/controls` | 센터 스위치·LED, 일시정지·재개·System OFF |
| `src/pointer` | 5방향 스위치 포인터. 방향 상태와 클릭 수를 알림(b27a2004)으로 보내고, 커서 그리기·탭은 앱이 한다. 방향 핀 매핑은 미확인 |
| `src/gesture_runtime.c` | **판정 코어.** 온라인 영점, 50 ms마다 판정, 발행 규칙(0.8·차이 0.2·2회 연속, 잠금·재무장), 입력 지우기 |
| `src/gesture_tcn.c` | 입력 처리(자이로 + 회전각)와 TCN 추론. 마지막 시점에 필요한 칸만 계산 |
| `src/gesture_weights.h` | 모델 가중치. `ml/v2_export_c.py export`가 만든다(직접 고치지 않는다) |
| `src/cycle_timer.h` | 시간 측정용 사이클 카운터 |

판정 코어(`gesture_runtime.c`, `gesture_tcn.c`)는 Arduino에 의존하지 않는 C99라 PC에서도 빌드된다. Python 기준(`ml/v2_erase.py replay`)과 같은 발행을 내는지 `ml/v2_export_c.py check`로 확인한다.

빌드·업로드(arduino-cli):

```powershell
arduino-cli compile --fqbn Seeeduino:nrf52:xiaonRF52840Sense firmware/gesture_infer
arduino-cli upload --fqbn Seeeduino:nrf52:xiaonRF52840Sense -p COM6 firmware/gesture_infer
```

개발 빌드(IMU 스트림 켬, 앱 개발용 빌드의 연속 기록·수집용)는 compile에 `--build-property "compiler.cpp.extra_flags=-DRINGPILOT_IMU_STREAM=1"`을 붙인다.
사용자 빌드는 스트림 특성이 없어서, 앱의 재개·재연결 지연 기록(`RESULT_pause_resume`, `RESULT_boot_reconnect`)이 남지 않는다(첫 데이터 기준이라서).

제스처 시험은 USB를 빼고 배터리로 한다(케이블 무게가 동작을 바꾼다).
