# RingPilot Android 수집 앱

링(`firmware/imu_ble_stream`)이 BLE로 보내는 IMU 6축 원시값을 받아, 제스처 학습용 데이터를 세션 단위로 기록하는 앱이다.

## 준비

1. 링에 `firmware/imu_ble_stream/imu_ble_stream.ino`를 업로드한다.
2. 휴대폰 Bluetooth 설정에서 `RingPilot-IMU`를 페어링한다. 설정 화면에서 "연결 안 됨"으로 보이는 것은 정상이다. 앱이 직접 연결한다.
3. 앱을 열면 자동으로 연결한다. 맨 위 줄이 `수신 중 · 100 Hz`이면 준비 완료다.

## 수집 방법

### 방향 안내 수집 (주 수집 방식)

방향별 횟수(기본 10)를 정하고 **방향 안내 수집 시작**을 누른다. 위·아래·왼쪽·오른쪽이 섞인 순서로 한 회씩 진행된다. 화면을 보지 않아도 소리만 듣고 따라 할 수 있다.

1. 방향을 음성으로 알려준다("위" 등).
2. **삑**: 기록이 시작된다. 가만히 있는다.
3. **삐빅**(1초 뒤): 이때 동작한다. 이동 후 자연스럽게 원위치로 돌아온다.
4. 4초가 지나면 자동으로 저장하고 다음 회차로 넘어간다.

- 동작을 잘못했으면 **방금 것 다시**를 누른다. 방금 파일을 지우고 같은 방향을 다시 한다.
- 샘플이 하나라도 빠진 회차는 저장하지 않고 자동으로 다시 한다.
- 링이 일시정지 상태이거나 연결이 끊기면 안내가 멈춰서 기다린다.

### 그 밖의 기록

- **idle 10초**: 가만히 있는 상태
- **other 10초**: 손가락 굽힘, 자세 조정처럼 명령이 아닌 움직임
- **연속 기록**: 길이 제한 없이 다시 누를 때까지 기록한다. 실제 사용처럼 이것저것 섞인 긴 기록(오작동률 평가용)에 쓴다. 중간에 샘플이 빠지면 timestamp 간격으로 남는다.

### 세션

- 첫 기록을 시작하면 세션이 자동으로 생긴다. 착용 손가락, 자세, 장소 등은 **세션 메모**에 적어 두면 함께 저장된다.
- 조건(착용 위치, 자세, 날짜)이 바뀌면 **세션 종료** 후 새로 시작한다. 세션 단위로 학습/평가를 나눌 수 있다.
- 앱을 닫으면 진행 중인 세션은 자동으로 종료된다.

## PC로 옮기기

휴대폰을 USB로 연결(USB 디버깅 허용)하고 저장소 루트에서 실행한다.

```powershell
node tools/pull-phone-sessions.js
```

- 종료된 세션만 `data/sessions/phone-<세션>/`으로 옮긴다.
- 모든 파일의 md5가 휴대폰과 같을 때만 휴대폰에서 지운다.
- 연결 기록은 `data/sessions/phone-connection-logs/`로 옮긴다.
- 지우지 않고 복사만 하려면 `--keep`, 목록만 보려면 `--dry-run`을 붙인다.

## 저장 형식

세션 폴더 `files/sessions/<yyyyMMdd-HHmmss>/`에 다음 파일이 생긴다.

- `raw_up.N.csv`, `raw_down.N.csv`, `raw_left.N.csv`, `raw_right.N.csv`: 4초, 400행
- `idle.N.csv`, `other.N.csv`: 10초, 1000행
- `continuous.N.csv`: 길이 제한 없음
- `session_info.txt`: 시작·종료 시각, 메모, 라벨별 개수, 자이로 범위(`gyro_range_dps`), 클립 길이(`gesture_samples`), 동작 신호 시각(`pre_roll_cue_ms`). 분석 도구가 이 값을 읽는다.
- `SESSION_DONE`: 세션 종료 표시

CSV 열은 `timestamp,accX,accY,accZ,gyrX,gyrY,gyrZ`(ms, m/s², deg/s)로, 분석 도구(`tools/suggest-gesture-completions.js --local-dir`)가 그대로 읽을 수 있다. 펌웨어는 센서 원시값을 보내고, 앱이 가속도 0.122 mg/LSB(±4 g), 자이로 0.070 dps/LSB(±2000 dps)로 환산한다. 환산 계수는 펌웨어 범위와 맞아야 하므로 **펌웨어와 앱은 함께 업데이트한다.** 옛 펌웨어(±1000 dps)에 새 앱을 쓰면 자이로 값이 2배로, 새 펌웨어에 옛 앱(0.035 dps/LSB)을 쓰면 절반으로 기록된다. 새 앱으로 기록한 세션은 `session_info.txt`에 `gyro_range_dps=2000` 줄이 있으므로, 수집 뒤 이 줄로 앱 버전을 확인한다.

디버그 APK는 PC마다 서명 키가 달라서, 다른 PC에서 설치한 앱 위에는 덮어쓸 수 없다(`INSTALL_FAILED_UPDATE_INCOMPATIBLE`). 이때는 앱을 지우고 다시 설치해야 하며, 휴대폰에 남은 세션도 함께 지워지므로 먼저 `node tools/pull-phone-sessions.js`로 옮긴다.

연결·일시정지·재개 이벤트와 재연결 시간은 `files/connection_log.csv`에 남는다.

## 빌드

요구 환경은 Android SDK Platform 35, Build-Tools 36.0.0, JDK 17 이상(Android Studio 동봉 JBR 사용 가능)이다.

```powershell
cd android
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
.\gradlew.bat :app:assembleDebug
```

Android Studio 없이 빌드할 때는 JDK 17(예: Temurin 17)을 `JAVA_HOME`으로 두고, 명령줄 SDK를 `.tools/android-sdk`에 설치한 뒤 `android/local.properties`에 `sdk.dir=C:/<저장소 경로>/.tools/android-sdk`를 적는다(경로는 `/`로 쓴다. `\`를 쓰면 `\u`가 유니코드 이스케이프로 읽혀 빌드가 실패한다).

## 보존한 기능

보드가 `firmware/gesture_infer`면 앱은 발행 알림(`b27a2003`)을 받아 화면에 표시하고, "스와이프 제어 켜기"를 누르면 접근성 서비스로 스와이프를 주입한다(기본은 꺼짐). 좌우 제스처는 구분 없이 상하·좌우 모드를 바꾸고 화면 위쪽에 모드를 1.2초 표시한다. 상하 모드는 위·아래 제스처가 위·아래 스와이프, 좌우 모드는 위 = 왼쪽, 아래 = 오른쪽 스와이프다. 앱을 다시 시작하면 상하 모드로 돌아간다. 수집 펌웨어에는 이 특성이 없어 건너뛴다. 전용 백그라운드 서비스는 없어 앱이 정리되면 끊긴다.

제스처 처리는 연결 기록(`connection_log.csv`)에 남는다. `gesture`는 보드에서 받은 값(seq·dir·score·slot), `app_gesture`는 앱 판단(제어·접근성 서비스 상태, 전환 전후 모드 `V`·`H`, 동작, 스와이프), `swipe_result`는 요청 결과(`completed`·`cancelled`·`not_dispatched`), `swipe_control`은 제어 켜기·끄기다. `completed`는 시스템이 주입을 마쳤다는 뜻이고 앱 화면이 원하는 대로 움직였다는 뜻은 아니다. 제스처를 인식하지 못하면 행이 없으므로 무발행은 이 기록만으로 알 수 없다. 연속 기록과 메모를 함께 본다. seq는 1바이트라 한 바퀴 돌면 겹치니 시각과 함께 맞춘다.

`SwipeAccessibilityService`(화면 스와이프 주입)는 제스처 인식 결과를 화면 조작으로 바꾸는 출력 경로로 코드만 남겨 두었다. 현재 화면에서는 호출하지 않는다.

## 캡처 시각 sidecar (영상 동기화 준비용)

각 캡처가 완료·실패·취소되면 같은 폴더에 `<CSV 이름>.capture.json`을 별도로 저장한다. CSV 열·행·환산은 그대로다. JSON은 기존 파일을 덮어쓰지 않고 CSV와 같은 단일 저장 대기열에서 기록한다.

- `first_board_slot`, `last_board_slot`: 실제 CSV 행으로 받아들인 첫/마지막 보드 슬롯. `sample_count`는 받아들인 행 수이며, 연속 기록의 공백을 포함한 시간 길이가 아니다. `sample_interval_ms=10`은 슬롯 간격 규칙이고 실제 샘플 시계 정확도를 측정한 값은 아니다.
- `start_call_elapsed_realtime_ms`: `startCapture` 진입 직후(세션 준비 전)의 휴대폰 부팅 기준 시각. `first_callback_arrival_elapsed_realtime_ms`: 첫 행이 속한 BLE listener 콜백 진입 시각. **물리적인 센서 샘플 시각이 아니며** BLE 배칭·전송 지연이 포함된다. `end_elapsed_realtime_ms`는 캡처를 끝내기로 결정한 시각이며 파일 저장 완료 시각이 아니다.
- `mode`: `finite`(목표 행 수 있음) 또는 `continuous`. `end_status`: `completed`, `stopped`, `sample_gap`, `timeout`, `aborted`, 또는 CSV 쓰기 오류가 있으면 `csv_write_failed`. 실패한 고정 길이 캡처는 CSV를 만들지 않지만 sidecar에는 실패를 남긴다.
- `intended_csv`는 예정 이름이다. `source_csv`는 최종 저장 시점에 파일이 존재할 때만 이름이 있고, 없으면 null이다. `csv_exists_at_finalization`은 그 시점의 존재 여부이며 무결성 보장이 아니다. `csv_write_failed=true`이면 일부만 기록된 CSV일 수도 있어 분석에 사용하면 안 된다.
- `session_directory`, `activity_instance_id`는 앱이 확실히 아는 문맥이다. Activity가 새로 만들어지면 ID가 바뀐다. 보드 부팅 ID·재시작 여부·펌웨어/앱 커밋·협상 MTU는 이 경로에서 확인할 수 없으므로 null이다. 같은 세션이나 Activity ID가 같다고 보드 부팅이 같다는 뜻은 아니다.

첫 슬롯만으로 영상 동기화가 완성되지 않는다. 별도의 영상 표식과 파일럿으로 대응 관계·오차를 확인해야 한다. 앱 비정상 종료/강제 종료에는 최종 sidecar가 없을 수 있다. 저장 오류는 화면 이벤트에 표시한다. **방금 것 다시**는 기존처럼 CSV를 삭제하며, sidecar는 당시 캡처 기록으로 보존되므로 CSV의 현재 존재 여부를 별도로 확인한다.

Android SDK 없이 순수 Java sidecar 검사를 실행할 수 있다(JDK 17 이상).

```powershell
.\android\tests\run-sidecar-tests.ps1
```

이 검사는 null/실패 메타데이터, 슬롯·도착 시각·행 수·연속 기록 구분, JSON 이스케이프와 덮어쓰기 거부를 확인한다. 실제 Android 수집·BLE·파일럿 동기화 검증을 대신하지 않는다.

같은 명령으로 `GestureRouter` 시험도 돈다(초기 모드, 전환, 방향 매핑, 제어·접근성 서비스 꺼짐, 기록 형식). 실제 스와이프·BLE·화면 표시를 대신하지 않는다.
