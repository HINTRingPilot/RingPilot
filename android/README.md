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

`SwipeAccessibilityService`(화면 스와이프 주입)는 제스처 인식 결과를 화면 조작으로 바꾸는 출력 경로로 코드만 남겨 두었다. 현재 화면에서는 호출하지 않는다.
