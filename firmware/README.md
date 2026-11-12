# RingPilot 현재 펌웨어 빌드와 전송

현재 제스처 펌웨어는 `gesture_infer`, 수집 전용 펌웨어는 `imu_ble_stream`이다. Seeed nRF52 Boards **1.1.13**, Seeed Arduino LSM6DS3 **2.0.7**을 사용한다. 제스처 모델·환산 계수·UUID·기존 8/10-byte 이벤트와 IMU 패킷 형식은 유지한다.

## 공통 전송 라이브러리

두 스케치는 프로젝트의 `firmware/libraries/RingPilotTransport`를 사용한다. CLI에서 프로젝트 루트 기준으로 `--libraries firmware/libraries`를 지정한다. Arduino IDE에서는 `RingPilotTransport` 폴더를 스케치북의 `libraries` 폴더에 설치한다.

```powershell
arduino-cli compile --fqbn Seeeduino:nrf52:xiaonRF52840Sense --libraries firmware/libraries --build-path .build/gesture_infer firmware/gesture_infer
arduino-cli compile --fqbn Seeeduino:nrf52:xiaonRF52840Sense --libraries firmware/libraries --build-path .build/imu_ble_stream firmware/imu_ble_stream
```

이 작업 PC의 CLI·코어는 git 제외인 `.tools`에 설치했다. 로컬 환경에서는 명령의 `arduino-cli`를 `.tools/arduino-cli/arduino-cli.exe --config-file .tools/arduino-cli.yaml`로 바꿔 실행한다. 업로드는 위 컴파일 명령에 포함되지 않는다.

## 상태와 제스처 전송

- BLE 콜백은 짧은 임계 구역에서 연결·특성 구독 상태만 게시한다. 고정 크기 큐의 추가·제거·전송은 loop만 담당한다.
- 제스처는 최대 4개를 FIFO로 보관한다. notify false면 같은 순번·점수·슬롯의 패킷을 유지하고 다음 loop에서 재시도한다. 가득 차면 새 항목을 거절한다.
- 발행 뒤 유효 기간은 250ms이며 남은 시간이 코어 대기 100ms+여유 20ms보다 짧으면 새 시도를 하지 않고 폐기한다. 이 수치는 초기 정책값이며 최적값이나 앱 응답 지연 측정치가 아니다.
- 연결 세대·제스처 구독 세대가 바뀌거나 일시정지하면 이전 대기 제스처를 폐기한다. 구독 off→on이 한 loop 사이에 발생해도 세대 변경을 보존한다.
- 현재 재개의 RESUMED는 큐 포화·일시적 상태 미구독에서도 보존한다. 스택이 RESUMED를 수용한 뒤 첫 IMU를 보내며, 첫 데이터 수용 후 FIRST_DATA를 기록한다.
- 한 loop에서 상태·제스처·IMU를 각각 최대 한 번 시도하고 실패 뒤의 전송은 다음 loop로 넘긴다. 대기열·mailbox·전송 순서의 공통 코드는 호스트 검사와 실제 스케치가 공유한다.

notify true는 BLE 스택이 수용했다는 뜻이다. 휴대폰 앱의 동작 완료 확인은 아니다. 이미 notify 내부에 들어간 호출은 현재 API로 취소할 수 없으며, 그 사이 연결/구독이 바뀌면 진단하고 추가 재시도를 막는다. 기존 수집 전용 스케치는 loop에서 샘플링하므로 블로킹 알림이 샘플 간격에 미치는 영향은 실기기에서 별도로 확인해야 한다.

`gesture_infer`의 시리얼 `l`은 기존 판정·샘플 통계에 TX 수용/재시도/실패/만료/포화와 연결·구독·일시정지 폐기, 전송 도중 경계를 더해 출력한다. `r`은 통계만 초기화하며 대기 패킷은 변경하지 않는다. LED·Issued는 모델이 발행한 횟수로, TX accepted와 구분한다.

## PC 검사

```powershell
.\firmware\tests\run-transport-tests.ps1
```

C++11 컴파일러(`g++`, 또는 `-Compiler`로 실행 경로 지정)가 필요하다. 실제 전송 큐·dispatcher·mailbox 어댑터를 사용하고 알림과 임계 구역만 모사한다. 재시도 bytes, FIFO, 만료·시각 순환, 연결 세대, 구독 off→on, notify 도중 경계, RESUMED→IMU→FIRST_DATA와 실패 뒤 전송 중단을 검사한다. 실제 무선 전송·보드 타이밍 확인을 대체하지 않는다.
