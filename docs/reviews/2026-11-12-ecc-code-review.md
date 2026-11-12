# 2026-11-12 ECC 코드 리뷰

후속 상태: 사용자 실행 요청으로 아래 **8건 모두 구현·PC 회귀 검사·APK/두 펌웨어 빌드를 완료**했다. [수정 결과와 검증 증거](2026-11-12-ecc-fixes-results.md). 실제 링·휴대폰 BLE 시험은 미확인이다. 아래 본문은 수정 전 코드의 리뷰 기록으로 보존한다.

- 요청: 현재 RingPilot 코드를 ECC 기준으로 리뷰한다.
- 기준: HEAD `b3abc84`, 최근 앱 변경 `c2cb497`. 시작 시 미커밋 변경은 진행기록과 프로젝트 설명 문서뿐이었다.
- 범위: Android 연결·수집·제스처·화면, 현재 보드 추론 펌웨어, Python 학습·평가·C 내보내기의 주요 실행 경로와 관련 테스트.
- 방법: ECC `review-pr`의 전문 관점별 검토, `code-reviewer`의 정확한 위치·구체적인 실패 조건·80% 이상 확신 기준, `python-reviewer`/`python-patterns`를 적용했다. 전체 파일의 완전성·보안 감사를 의미하지 않는다.
- 판정: **수정 권고 — P1 1건, P2 7건.** P1은 우선 해결할 수집 데이터 손실, P2는 특정 조건에서 발생하는 기능 오류다. 아래 문제의 유입 커밋은 추적하지 않았다.
- 앱·펌웨어·모델 소스는 수정하지 않았다. 재현 파일은 git 제외 경로 `.build/`에 만들었다.

## 발견 사항

### 1. [P1] 수집 예약·안내 재개가 진행 중 캡처를 덮어쓴다

- 위치: `android/app/src/main/java/com/hintringpilot/ringpilot/MainActivity.java:1171`, `:1112`, `:888`.
- 조건 A: IDLE/OTHER를 누른 뒤 1.2초 준비 시간 안에 연속 기록을 시작한다. 예약 당시에는 `capture`가 없으며, 준비 상태도 따로 잡지 않는다. 지연 콜백이 실행될 때 기존 캡처 여부를 다시 검사하지 않는다.
- 조건 B: 방향 안내를 일시정지하고 연속 기록을 시작한 뒤 **계속**을 누른다. 안내 재개에는 `captureActive()` 검사가 없다.
- 결과: `startCapture()`의 `capture = c`가 기존 연속 캡처를 교체한다. 이전 캡처는 완료 처리되지 않고 아직 메모리에 있는 행과 최종 sidecar를 저장하지 못한다. 이후 중지 버튼도 이전 캡처를 되찾지 못한다.
- 기존 보호의 한계: 버튼 진입 시 `captureActive()` 검사만으로는 예약 구간을 보호하지 못하며, 안내 재개·`startCapture()`에는 같은 보호가 없다.
- 수정 방향: 준비 중 상태도 수집 소유권에 포함한다. 수집 시작을 한 곳에서 배타적으로 처리하고, 안내 재개와 예약 콜백에서 세션·세대·현재 캡처를 확인한다.
- 재현: 원본 메서드 9개를 추출하고 Android/UI/파일 I/O만 스텁한 Java harness. 두 조건 모두 이전 캡처 `finished=false`, 버퍼 10행을 남긴 채 `raw_up` 또는 `idle`로 교체됨을 확인했다.

### 2. [P2] 보드 재부팅 후 연속 기록이 새 샘플을 장시간 버린다

- 위치: `MainActivity.java:931`, `ImuBleClient.java:146`, `firmware/gesture_infer/gesture_infer.ino:392`.
- 조건: 연속 기록 도중 링 전원을 껐다 켜거나 리셋한다. 펌웨어 슬롯은 부팅 기준으로 다시 시작한다.
- 결과: BLE 클라이언트의 `expectedSlot`은 초기화되지만 캡처의 `nextSlot`은 이전 부팅 값을 유지한다. `if (slot < c.nextSlot) continue`가 새 샘플을 모두 버린다. 이전 슬롯이 100010이면 새 부팅에서 약 1000초가 지날 때까지 기록이 진행되지 않는다. 이후 시간축도 실제 재부팅 공백을 반영하지 못한다.
- 수정 방향: 연결 종료 또는 슬롯 역행 시 현재 기록을 종료하고 새 구간으로 분리한다. 여러 부팅을 연결하려면 부팅 식별자와 구간별 시간 대응을 명시한다.
- 재현: 실제 `acceptSamples()`를 사용해 슬롯 100000~100009 다음에 0~9를 입력했다. 수신 행 수는 10으로 유지되었고 `nextSlot=100010`이었다. 실제 보드 재부팅 시험은 하지 않았다.

### 3. [P2] 같은 초에 새 세션을 시작하면 이전 CSV를 덮어쓴다

- 위치: `MainActivity.java:796`~`:802`, `:840`, `:885`.
- 조건: 연속 기록을 시작·종료한 뒤 같은 초에 새 연속 기록을 시작한다.
- 결과: 초 단위 세션 이름이 같아 `mkdirs()`가 실패해도 진행하며 `nextIndex`를 초기화한다. `continuous.1.csv`를 다시 선택하고 헤더를 append=false로 쓰므로 이전 행이 사라진다. 이전 `SESSION_DONE`도 남아 새 활성 세션을 PC 이동 도구가 종료된 세션으로 취급할 수 있다.
- 수정 방향: 충돌 없는 세션 디렉터리를 생성하고, 생성 실패 시 수집을 중단한다. 디렉터리 확보 전에 상태·파일 번호를 초기화하지 않는다.
- 재현: 원본 메서드 10개를 추출하고 날짜를 같은 초로 고정했다. 실제 임시 파일 I/O에서 폴더·CSV 경로 재사용, 이전 행 소실, 활성 기록 중 `SESSION_DONE` 잔존을 확인했다.

### 4. [P2] 펌웨어 상태 큐를 두 태스크가 동시에 비운다

- 위치: `firmware/gesture_infer/gesture_infer.ino:148`~`:150`, `:170`, `:195`, `:663`. `firmware/imu_ble_stream/imu_ble_stream.ino`에도 같은 큐 구현이 있다.
- 조건: CCCD 콜백의 `sendStatus → flushStatus`와 `loop → flushStatus`가 겹친다. notify가 송신 버퍼를 기다리는 동안 다른 태스크가 같은 큐 항목을 보낼 수 있다.
- 결과: 같은 항목을 두 번 제거하며 `uint8_t statusQueueCount`가 0에서 255로 언더플로할 수 있다. 오래된 상태 패킷을 반복 전송하고 그동안 loop의 다른 처리를 지연시킨다.
- 기존 보호의 한계: 큐의 head/count를 두 경로에서 잠금 없이 수정한다. 코어 1.1.13에서 CCCD 콜백은 기본적으로 별도 NORMAL 우선순위 Callback 태스크이며 loop는 LOW 우선순위 태스크다.
- 수정 방향: 콜백은 이벤트만 전달하고 큐 추가·송신·제거는 loop 한 곳에서 처리한다. 동기화가 필요하면 블로킹 notify를 포함한 임계 구역 설계를 확인한다.
- 재현: 원본 `flushStatus()`를 추출하고 송신 대기 중 교차 실행을 모사했다. `notify calls=3, pending queue count=255 (expected 0), head=2`를 확인했다. 이 순서가 실보드에서 발생하는 빈도는 측정하지 않았다.
- 공식 근거: [CCCD 콜백 기본 설정](https://github.com/Seeed-Studio/Adafruit_nRF52_Arduino/blob/1.1.13/libraries/Bluefruit52Lib/src/BLECharacteristic.h#L109), [Callback 태스크 생성](https://github.com/Seeed-Studio/Adafruit_nRF52_Arduino/blob/1.1.13/cores/nRF5/utility/AdaCallback.c#L147), [loop 태스크 생성](https://github.com/Seeed-Studio/Adafruit_nRF52_Arduino/blob/1.1.13/cores/nRF5/main.cpp#L112).

### 5. [P2] 제스처 알림 전송 실패를 복구하지 않는다

- 위치: `firmware/gesture_infer/gesture_infer.ino:260`, `firmware/gesture_infer/src/gesture_runtime.c:112`.
- 조건: 연결·알림 구독은 유지되지만 BLE 송신 버퍼 확보나 알림 전송이 실패한다.
- 결과: `gestureEvent.notify(...)`의 false 반환을 버린다. 런타임은 이미 발행 잠금과 입력 지우기를 예약했으므로 해당 명령은 재전송되지 않는다. LED·발행 카운터·순번은 증가하지만 앱 동작은 누락된다.
- 수정 방향: 보낼 패킷을 보존하고 성공 또는 명시적 만료까지 재시도한다. 지연된 명령이 뒤늦게 실행되지 않도록 만료 정책도 정한다.
- 재현: 원본 `sendGesture()`의 notify에 실패를 주입했다. `notify attempts=1, delivered=0, issuedCount=1, gestureSeq=1`이었다. 실제 무선 환경의 실패율은 측정하지 않았다.
- 공식 근거: 코어 1.1.13의 [송신 버퍼 확보 실패 시 false 반환](https://github.com/Seeed-Studio/Adafruit_nRF52_Arduino/blob/1.1.13/libraries/Bluefruit52Lib/src/BLECharacteristic.cpp#L728).

### 6. [P2] 불완전한 학습 결과로 빈 요약을 성공 저장한다

- 위치: `ml/v2_return.py:557`, `:580`.
- 조건: 요청한 split·seed 결과 중 하나라도 없는 tag로 `summarize`를 실행한다.
- 결과: `labels=[]`, `panels={}`인 파일을 오류 없이 저장한다. 이후 결과를 갖춰 다시 실행하면 기존 파일 보호 때문에 `FileExistsError`로 막힌다.
- 수정 방향: 누락 결과를 저장 전에 검사하고 목록과 함께 실패시킨다. 부분 요약을 지원한다면 포함·누락 범위를 명시한다.
- 재현: 출력 위치만 임시 폴더로 변경하고 실제 데이터·약한 동작 목록 검증을 유지했다. 빈 요약 생성 및 재실행 거부를 확인했다. 학습은 실행하지 않았다.

### 7. [P2] 따옴표로 감싼 Windows 컴파일러 경로를 실행하지 못한다

- 위치: `ml/v2_export_c.py:150`.
- 조건: `RINGPILOT_CC`에 공백이 있는 실행 파일 경로를 따옴표로 감싸 넣는다.
- 결과: `shlex.split(env, posix=False)`가 따옴표를 토큰에 남긴다. 실행 인수 목록에 이 값이 그대로 전달되어 실제 파일이 있어도 `FileNotFoundError`가 발생한다. 사용자 지정 컴파일러를 쓰는 host 검증·지연 측정 경로에 영향을 준다.
- 수정 방향: 실행 파일 경로와 추가 인수를 구분하거나, Windows 파싱 결과에서 외곽 따옴표를 올바르게 처리한다.
- 재현: 실제 존재하는 venv Python 실행 파일 경로를 따옴표로 감싼 환경변수로 `find_cc → subprocess.run`을 호출해 `FileNotFoundError`를 확인했다. 이 검사는 경로 처리만 검증하며 C 컴파일을 수행하지 않는다.

### 8. [P2] `--parallel 0` 또는 음수에서 무한 대기한다

- 위치: `ml/v2_return.py:448`, CLI 인수 `:605`.
- 조건: `run-all --parallel 0` 또는 음수를 전달한다. argparse는 정수 여부만 확인한다.
- 결과: 첫 작업이 종료되어 활성 작업이 0이어도 `0 >= parallel`이 계속 참이므로 대기에서 벗어나지 못한다.
- 수정 방향: 실행 전 `parallel >= 1`을 검사하고 잘못된 값에는 명확한 인수 오류를 반환한다.
- 재현: 실제 `cmd_run_all()`에 완료된 Popen과 sleep 감시를 주입했다. 활성 작업 0개인데도 sleep에 진입했다. 자식 실행·학습은 모사했으며 실제 학습은 하지 않았다.

## 검증 결과와 한계

| 검사 | 결과 |
| --- | --- |
| Python `ml/.venv/Scripts/python.exe -m unittest discover -s ml -p 'test_*.py'` | **73개 통과**, 19.213초 |
| `android/tests/run-sidecar-tests.ps1` | **CaptureSidecar·GestureRouter 모두 통과** |
| `android/gradlew.bat :app:assembleDebug --offline --console=plain` | **BUILD SUCCESSFUL**, Gradle 9.6.0, 8초 |
| Android 추출 로직 재현 | 캡처 충돌 2조건, 슬롯 역행, 세션 파일 덮어쓰기 확인 |
| 펌웨어 추출 로직 재현 | notify 실패 유실, 큐 교차 실행 언더플로 확인 |
| Python 실제 함수 재현 | 빈 요약, 경로 따옴표, parallel=0 대기 확인 |
| 실제 링·BLE·휴대폰·소비전력 | 실행하지 않음 |
| ruff·mypy·pylint·black | 설치되어 있지 않아 실행하지 않음 |

환경: Windows, Python 3.12.10, Java/JDK 21.0.9, MSYS2 g++ 16.1.0. 기존 테스트 통과는 이번에 재현한 상태 전이·실패 조건을 검증했다는 뜻이 아니다. 기본 모델 계산 경로에서는 추가로 확정할 오류를 발견하지 못했다.

최초 Python 검사는 샌드박스 임시 폴더의 파일 접근 권한 때문에 실패했다. TEMP/TMP를 저장소 `.build/ecc-review-2026-11-12/tmp`로 옮겨 전체 검사를 다시 실행해 통과했다. Android 빌드도 Gradle 캐시 접근 권한을 확보한 뒤 오프라인으로 통과했다. 환경 권한 오류를 제품 버그로 집계하지 않았다.

빌드 산출물은 `android/app/build/outputs/apk/debug/app-debug.apk`, 3,477,292 bytes, SHA-256 `a6dfdd75a6aa5a3cf86bb47ae17f5428a5986a6ec084d93b1409cee8d28caf12`다. 기존 동일 경로 APK가 이번 빌드 결과로 갱신되었으며 새 전달용 ZIP은 만들지 않았다.

## 재현 산출물

아래 경로는 로컬 `.build/` 안에 있으며 git 추적 대상이 아니다.

- `.build/ecc-review-2026-11-12/python-tests.log`
- `.build/ecc-review-2026-11-12/python_repro.py`, `python-repro.log`
- `.build/review-repros/android/AndroidCaptureReviewRepro.java`
- `.build/review-repros/android/AndroidSessionCollisionReviewRepro.java`
- `.build/review-repros/android/session-collision-15730370843031244730/` — 실제 파일 I/O 재현 증거
- `.build/ecc-firmware-review/queue_fault.cpp`, `gesture_fault.cpp`

## 다음 작업 제안

우선 수집 준비·실행·중지·안내 재개 상태를 배타적으로 관리해 캡처 손실을 막는다. 이어 세션 이름 충돌과 재부팅 구간을 처리하고, 펌웨어 큐 소유권과 명령 재전송을 보강한다. 수정 시 이번 재현을 정식 회귀 검사로 옮기고, 실제 링에서 수집·재연결·전원 재시작을 별도 확인한다. Python CLI 세 항목은 학습을 돌리지 않는 입력·파일 상태 검사로 검증할 수 있다.
