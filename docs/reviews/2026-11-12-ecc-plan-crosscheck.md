# ECC 수정 계획 교차 검증 — 2026-11-12

후속 상태: R2를 구현 기준으로 사용해 8건 수정과 PC·에뮬레이터 검증을 완료했다. [수정 결과](2026-11-12-ecc-fixes-results.md). 아래 판정과 수행 범위는 구현 전 교차 검증 시점의 기록이다.

대상: [ECC 리뷰 8건 수정·검증 계획](../superpowers/plans/2026-11-12-ecc-review-fixes.md).

**판정:** R1의 수정 방향과 8건의 대응 관계는 타당하다. 그대로 실행하기에는 종료 순서·연결 복구·전송 순서·검증 방법에 **7개 보완점**이 있어 R2에 반영했다. R2는 구현에 사용할 수 있는 계획이며 제품 수정의 성공을 검증한 결과는 아니다.

## 방법과 범위

- ECC blueprint의 계획 검토 절차에 따라 Android, 펌웨어, Python·검사 명령을 독립적으로 검토했다.
- 부모 검토에서 지적을 실제 코드와 대조하고 중복을 합쳤다. 수정 후에는 각 검토자에게 담당 범위의 재확인을 요청했다.
- 기존 8개 제품 버그를 다시 세지 않았다. 아래 항목은 그 버그를 고칠 **계획의 빠진 조건**이다.
- 기준 코드는 HEAD `b3abc84`다. 제품 코드 변경·전체 테스트·빌드·학습·업로드·실기기 시험은 하지 않았다.
- 원래 R1 계획은 로컬 `.build/ecc-plan-crosscheck/2026-11-12-ecc-review-fixes-r1.md`에 보존했다. 아래 원래 계획 줄 번호는 그 R1 기준이다.

## 보완점과 R2 반영

### C1. [P1] 마지막 샘플과 파일 저장 등록 사이의 종료 경합

- R1 위치: 116~117행.
- 코드 근거: `MainActivity.java:950~967`은 샘플 완료 후 mainHandler에 done을 보낸다. 실제 저장 등록은 `:1102 → :983~986`에서 한다. `endSession :829~831`은 종료 마커를 등록하며 `onDestroy :1246~1248`은 UI 작업을 제거하고 executor를 닫는다.
- 반례: 마지막 400번째 샘플 수신 → UI 완료 콜백 대기 → 세션/Activity 종료. 이미 fileWriter에 등록된 작업만 기다려서는 아직 등록되지 않은 400행의 저장을 보장하지 못한다. 느린 저장 중 기존의 즉시 guideIndex 증가·다음 회차 예약도 새 FINALIZING과 충돌한다.
- R2 반영: 실제 CaptureCoordinator가 종료 확정 시 불변의 파일 작업을 즉시 등록한다. UI와 저장을 분리하고, 세션별 결과를 확정한 뒤 요약·마커·shutdown을 순서대로 처리한다. 다음 안내 회차는 저장 성공 이후 예약한다.
- 필수 검사: UI 대기열 정지 상태에서 세션/Activity 종료, 느린 파일 쓰기, 쓰기 실패. CSV·sidecar·요약·마커의 순서와 정확히 한 번 처리를 확인한다.

### C2. [P2] 준비 중 단절과 수동 다시 연결의 경계 누락

- R1 위치: 93, 171~175행.
- 코드 근거: `MainActivity.java:1067~1088`은 방향 안내 후 1.2초 뒤 기록을 시작한다. 수동 다시 연결은 `:757~758`의 stop→start다. `ImuBleClient.java:119~124`의 stop은 GATT를 close하며 disconnect 콜백을 기다리지 않는다.
- 반례: 캡처가 생기기 전 ARMING에서 끊겨 token만 취소하면 onTrialDone이 없어 다음 회차 재시도가 사라질 수 있다. 수동 stop에서 disconnect 콜백이 오지 않으면 기존 기록의 종료도 누락될 수 있다.
- R2 반영: 명시적 stop·연결 객체 교체·Activity 종료까지 기존 연결 세대당 경계를 한 번 발행한다. ARMING의 cue와 예약을 취소하면서 같은 index의 재시도 요청을 보존하고, streaming·IDLE·안내 재개 조건을 충족할 때 한 번 실행한다.

### C3. [P2] helper 검사만으로 실제 수집 종료 순서가 검증되지 않음

- R1 위치: 83, 131, 141, 166, 296, 300행.
- 코드 근거: 기존 Java runner는 CaptureSidecar·GestureRouter를 검사한다. R1의 신규 검사도 상태·폴더·슬롯 helper 중심으로, MainActivity의 UI scheduler·fileWriter·종료 조합을 실행하는 대상은 없었다.
- R2 반영: 단순 CaptureLifecycle helper 대신 제품이 사용하는 CaptureCoordinator를 검사 대상으로 지정했다. 실제 제품 조정 계층에 Clock·UiScheduler·WriteQueue를 주입하고 두 대기열의 순서를 바꿔 임시 파일 결과까지 확인한다. MainActivity·BLE는 같은 조정 계층의 어댑터로 연결한다.
- 한계: 이 자동 검사는 실제 Android 생명주기·무선 환경 전체를 증명하지 않는다. 앱·실기기 확인은 계속 별도다.

### C4. [P2] 제스처 구독 해제 이력이 최신값 mailbox에서 사라질 수 있음

- R1 위치: 200~202, 229, 238행.
- 코드 근거: `gesture_infer.ino:637~642`는 상태 특성에만 CCCD 콜백을 등록한다. 코어의 [notifyEnabled](https://github.com/Seeed-Studio/Adafruit_nRF52_Arduino/blob/1.1.13/libraries/Bluefruit52Lib/src/BLECharacteristic.cpp#L701)는 현재 구독 값만 확인한다.
- 반례: 대기 제스처가 있는 동안 한 loop 사이에 gesture CCCD off→on이 일어나면 최신값은 다시 on이다. 상태용 mailbox와 송신 직전 현재 구독 확인만으로는 옛 항목을 폐기할 수 없다.
- R2 반영: 제스처 전용 CCCD 콜백, 구독 세대 또는 sticky revoke, 일관된 연결 snapshot을 추가했다. off→on 회귀 조건을 명시했다.
- 보장 한계: 이미 Bluefruit notify 내부에서 대기하는 호출은 현재 API로 취소하지 못한다. pending과 in-flight를 구분하고, 이미 스택이 수용한 패킷의 취소나 앱 실행 취소를 보장하지 않는다.

### C5. [P2] 상태 1개 제한만으로는 RESUMED→첫 IMU 순서가 보장되지 않음

- R1 위치: 240행.
- 코드 근거: `ImuBleClient.java:265~268`은 RESUMED를 받아야 expectedSlot을 초기화한다. `:311~312`는 먼저 받은 IMU 공백을 missingSamples에 더한다. `gesture_infer.ino:198~204`에서 MTU23이면 IMU 묶음 크기는 1이다.
- 조건: 이전 상태 항목이 남아 이번 loop의 상태 전송 한도를 소비하고, RESUMED는 뒤에 있는데 재개 첫 IMU가 준비된다. MTU23·대기 항목 조건에서 첫 데이터가 RESUMED보다 먼저 전달될 수 있다. MTU247·막힘 없는 정상 조건에서 항상 발생한다는 주장은 하지 않는다.
- R2 반영: 현재 재개 주기의 RESUMED가 스택에 수용될 때까지 IMU만 보류하는 장벽을 추가했다. 해당 RESUMED는 일반 포화 정책으로 버리지 않으며, 상태 구독이 꺼져도 현재 장벽의 payload를 보존해 재구독 후 복구한다. 이전 재개 주기가 무효화되면 장벽도 갱신한다. 샘플링·추론은 계속 수행한다.
- 검증: 간단한 전송 순서 모델에서 기존 순서 `PAUSED → DATA → SUBSCRIBED → RESUMED`는 일시정지 1,000슬롯을 누락에 더했다. 장벽을 두면 `PAUSED → SUBSCRIBED → RESUMED → DATA`, 누락 가산 0이었다. 이는 추상 모델이며 실제 펌웨어 실행 결과가 아니다.

### C6. [P2] 검증 중 실패가 뒤 명령의 성공으로 가려질 수 있음

- R1 위치: 313~325행.
- 근거: 기존 `android/tests/run-sidecar-tests.ps1`은 매 외부 명령 직후 LASTEXITCODE를 검사하지만 R1 상위 검증 명령 목록에는 같은 처리가 없었다.
- 실제 확인: 종료 코드 7인 Python 실행 다음에 성공한 외부 명령을 두면 PowerShell 전체 종료 코드가 0이고 후속 명령도 실행됐다. 실패 직후 throw를 추가하면 전체 종료 코드 1, 후속 명령 미실행이었다.
- R2 반영: Invoke-CheckedNative로 단계별 종료 코드를 즉시 검사하고 첫 실패에서 중단하도록 변경했다. transcript로 검증 로그를 보존한다. 새 transport 검사 runner도 내부 실패를 throw하도록 명시했다.

### C7. [P2] 공백 경로 파싱 검사와 실제 C 빌드 검사의 연결 누락

- R1 위치: 275, 379행.
- 코드 근거: `ml/test_v2_c_infer.py:50~61`은 find_cc가 고른 현재 컴파일러로 host 빌드한다. 일반 gcc 경로의 parity와 공백 경로 Python 실행기 검사만 통과해도, 인용부호 있는 실제 C 컴파일러 경로가 작동했다는 증거는 아니다.
- R2 반영: 실제로 링크 가능한 공백 경로 툴체인을 큰따옴표로 감싼 RINGPILOT_CC로 설정하고 같은 설정에서 host 빌드·parity를 실행하는 단계를 필수로 추가했다. 환경변수는 종료 후 복구한다.
- 현재 확인 범위: `C:/Program Files/LLVM/bin/clang.exe` 파일은 존재한다. 이 경로의 링크·parity는 실행하지 않았으며 툴체인 준비가 필요하다. gcc 툴체인을 사용할 경우 exe 하나의 복사본이 아닌 전체 툴체인 경로의 별칭을 사용하도록 했다.

## 유지해도 되는 판단

- 8개 리뷰 항목과 S1~S8의 대응, 데이터 손실부터 수정하는 우선순위는 맞다.
- 모델 가중치·발행 규칙·CSV 열·BLE 패킷 형식을 보존하는 범위는 맞다.
- 연결 종료 시 연속 기록을 저장 후 종료하는 정책은 시간축을 보존하는 일관된 기본안이다. 자동 재개를 제공하는 동작은 아니다.
- 큐 4개·250ms·100ms 대기 예산+20ms 여유는 보수적인 초기 제안으로 논리적 모순은 없다. 성능 최적값이나 종단 지연 보장으로 쓰면 안 된다.
- IMU 1패킷/loop는 기존 pollSending과 같아 그 제한 자체를 새로운 유량 저하라고 볼 근거는 없다.
- 수집 전용 imu_ble_stream의 loop 샘플링에서 블로킹 전송이 끼치는 영향은 기존에도 있는 조건이다. 새 결함으로 집계하지 않고 동일 조건의 전후 관찰로 남긴다.
- 공통 라이브러리와 프로젝트 --libraries 경로는 타당한 구조다. 실제 빌드는 아직 수행하지 않았다.

## 수정 후 독립 재확인

Android 검토자는 C1~C3, 펌웨어 검토자는 C4~C5, Python 검토자는 C6~C7이 R2 문서에서 해소됐음을 재확인했다. 새로 확정할 논리적 모순은 보고되지 않았다. 펌웨어 검토자의 추가 주의사항인 상태 미구독 시 RESUMED payload 보존도 명시했다. 이 재확인은 설계 문서에 대한 것이며 아직 없는 구현의 성공을 뜻하지 않는다.

## 이번 확인의 산출물·한계

- `.build/ecc-plan-crosscheck/probe.py` — 실제 PowerShell 실패 전파 확인과 재개 순서 추상 모델.
- `.build/ecc-plan-crosscheck/probe-results.json` — 관찰 출력. PowerShell 무보호 종료 코드 0/계속 실행, 보호 적용 종료 코드 1/후속 실행 없음. 순서 모델 누락 가산 1000→0.
- `.build/ecc-plan-crosscheck/powershell-syntax.json` — 계획 S9 PowerShell 코드 블록 1개의 parser 오류 0개. 명령 블록 자체는 실행하지 않았고, 아직 없는 신규 제품 클래스·검사 runner의 실행 결과로 취급하지 않는다.
- 전체 검사 재실행, 현재 코어의 새 펌웨어 컴파일, 실제 BLE·보드·휴대폰 시험은 이번 검토에 포함하지 않는다.

다음 작업은 R2를 기준으로 구현하는 것이다. S1~S3의 완료·종료 경합과 S4~S5의 구독·재개 순서 검사를 먼저 고정해야 한다. 실제 구현 후 같은 실패 조건과 기존 검사가 통과해야 수정 완료로 표시할 수 있다.
