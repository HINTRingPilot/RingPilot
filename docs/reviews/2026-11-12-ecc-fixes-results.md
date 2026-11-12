# ECC 리뷰 8건 수정 결과

작성: 2026-11-12. 기준 HEAD `b3abc84`, 작업 브랜치 `codex/ecc-review-fixes`. **8건 구현·PC 회귀 검사·APK와 두 보드용 빌드 완료. 실제 링·휴대폰 BLE 시험은 미확인**이다. 변경은 커밋·푸시하지 않았다.

[원래 리뷰](2026-11-12-ecc-code-review.md), [R2 계획](../superpowers/plans/2026-11-12-ecc-review-fixes.md), [계획 교차 검증](2026-11-12-ecc-plan-crosscheck.md)을 기준으로 구현했다. 원래 리뷰의 재현 결과는 수정 전 기록으로 보존한다.

## 8건 대응

| 번호 | 수정 | 회귀 근거 | 상태 |
| --- | --- | --- | --- |
| 1 / P1 | 제품 `CaptureCoordinator`가 ARMING→RECORDING→FINALIZING을 단독 소유한다. 세션·연결·예약 token이 다르면 시작·GO·timeout을 무시한다. 버튼도 같은 guard를 사용한다 | 중복 시작, 일시정지 안내 중 수동 기록→계속 거절, 준비 취소, 오래된 콜백, UI 정지 상태의 마지막 400행 저장 | 구현·PC 통과 |
| 2 / P2 | GATT 시도마다 세대를 부여하고 stop도 명시적 경계로 전달한다. 연속 기록은 저장·종료하고 재시작을 기다리며, 안내 회차는 같은 index로 재시도한다 | 슬롯 100000대→새 연결 0, ARMING 단절, handle 재사용·옛 콜백 거절, 중복/역행/공백, 정확한 sidecar status/reason | 구현·PC 통과 |
| 3 / P2 | 원자적 새 세션 폴더와 CREATE_NEW를 사용한다. 실패 자료·절대경로를 보존하고 초기 metadata 실패는 종료 후 새 세션으로 복구한다 | 같은 시각 폴더 분리·기존 파일 보존, mkdir/header/metadata/summary/marker 실패, 생성 후 marker 실패 정리·기존 marker 보존 | 구현·PC 통과 |
| 4 / P2 | 두 스케치가 공통 `RingPilotTransport`를 사용한다. BLE 콜백은 짧은 임계 구역의 mailbox만 갱신하고 loop만 큐를 변경한다 | 빈 큐·포화·notify 실패/성공, notify 도중 callback, 빠른 연결 교체, 실제 mailbox 어댑터 검사 | 구현·PC 및 보드 빌드 통과 |
| 5 / P2 | 4항목 FIFO에 동일 bytes/seq를 보존한다. TTL 250ms, 새 시도에 필요한 남은 예산 120ms, 연결/구독 세대·pause 폐기를 적용한다 | false→true 동일 패킷 1회 수용, FIFO/포화/만료/시각 wrap, off→on, RESUMED→첫 IMU→FIRST_DATA, MTU23 모사 | 구현·PC 및 보드 빌드 통과 |
| 6 / P2 | 요약 전 필요한 모든 split/seed 결과와 JSON 구조를 검사한다. 누락·손상 경로를 표시하고 기존 출력도 보존한다 | 전부/일부 누락, 빈 splits, 잘못된 JSON/metadata/count/event/delay, 완비 후 같은 출력 이름으로 성공 | 구현·PC 통과 |
| 7 / P2 | 전체 실행 경로를 먼저 확인하고 추가 인수는 Windows CommandLineToArgvW / POSIX shlex로 분해한다. shell은 사용하지 않는다 | 따옴표·공백 경로·역슬래시·추가 인수·빈 명령, 실제 공백 GCC 경로로 host C parity 7개 통과 | 구현·실제 C 컴파일 통과 |
| 8 / P2 | argparse와 직접 함수 호출 모두 parallel≥1을 검증한다. 파일·keep_awake·Popen보다 먼저 실패한다 | 0/-1/비정수 exit 2, 직접 호출 ValueError·부작용 0, 유효 값·실패 자식·로그 종료 | 구현·PC 통과 |

## 교차 검증과 구현 중 추가 보완

- 마지막 샘플의 terminal 저장 작업은 같은 lock에서 먼저 접수한다. 파일 writer는 UI 완료 콜백 없이 CSV/sidecar→집계→세션 요약→DONE→shutdown을 진행한다. 느린 저장 중 안내 index가 먼저 늘지 않는다.
- 파일 준비가 끝나도 실제 UI의 STILL 안내 작업이 실행될 때까지 ARMING을 유지한다. 이 시점에 기록을 활성화하고 GO를 1000ms 뒤에 예약한다. 반면 terminal 저장은 UI 정지에 의존하지 않는다.
- 연속 ARMING 취소는 해당 예약이 CREATE_NEW로 만든 헤더만 직렬 writer에서 정리한다. 기존 파일과 즉시 재시작한 다른 예약 파일은 삭제하지 않는다.
- 초기 session_info 생성 후 오류는 partial 파일을 보존한다. 같은 폴더 초기화를 반복하지 않고 세션 종료 후 새 폴더 시작을 안내한다. SESSION_DONE도 생성 소유권을 추적해 후속 오류에서 자기 마커만 정리하며, 삭제 실패 시 잔존 경고와 절대경로를 남긴다.
- 제스처 CCCD off→on은 별도 세대로 보존한다. 현재 RESUMED는 포화·상태 미구독 중에도 유지하며 수용 전 IMU 전송을 보류한다. 상태 notify가 대기했으면 그 뒤 시각으로 제스처 예산을 재검사한다.
- 통합 `tools/verify-ecc-fixes.ps1`은 첫 실패에서 중단하고 단계별 결과를 저장한다. Windows PowerShell 5.1의 null 인수 splat을 피하며 로그 정리 실패에도 환경·작업경로를 복원한다. native exit 7과 읽기 전용 stages.json을 주입해 원래 실패 보존·후속 미실행을 확인했다.
- Android·펌웨어·Python은 구현자와 별도의 사양/품질 검토를 거쳤다. 발견한 경계 조건을 고친 뒤 모두 PASS/APPROVE를 받았다.

## 실행 결과

| 검사 | 최종 결과 |
| --- | --- |
| Java runner | CaptureSidecar·GestureRouter 통과, 제품 Coordinator **274 checks 통과** |
| Python 전체 | **90 tests 통과, 31.620초**, skip 없음. 수정 전 같은 환경은 73개 통과 |
| 펌웨어 host | 실제 공통 큐·dispatcher·mailbox 어댑터의 **8 scenario groups 통과** |
| 공백 경로 C parity | 큰따옴표로 감싼 실제 GCC로 **7 tests 통과, 2.221초**, skip 없음 |
| Android | `:app:assembleDebug --offline --console=plain` 성공, 최종 증분 검사도 up-to-date |
| gesture_infer | Seeed 보드 대상 컴파일 성공, program **158936 B**, globals **51364 B** |
| imu_ble_stream | 동일 대상 컴파일 성공, program **127980 B**, globals **18868 B** |
| 에뮬레이터 | Android 12/API31: APK 덮어 설치·실행, 안내 대기/일시정지, 홈 복귀 후 세션 유지, 연결 전 수동 버튼 비활성, 세션 종료·DONE 저장, 앱 crash 없음 |
| PC 이동·분석 도구 | 같은 초 기본/`-001` 합성 세션 6파일 복사·MD5 동일, 미완료 세션 제외, 원본 보존. 실제 에뮬레이터 세션도 `--keep`으로 복사·검증. 접미사 폴더의 합성 400행 1클립을 완료시각 분석 CLI로 정상 읽음 |
| 보존 확인 | `data/`, 원본 기획서, `ml/model.py`, 추론 C·가중치에 기준 HEAD 대비 diff 없음. 기존 사용자 문서 보존 |

같은 CLI·코어로 수정 전 보드 빌드도 확보했다. gesture_infer는 program 155792→158936 B(+3144), globals 51180→51364 B(+184), imu_ble_stream은 program 125708→127980 B(+2272), globals 18676→18868 B(+192)다. 실행 시간·전력·인식률 변화의 측정치는 아니다.

도구: Windows PowerShell 7.6.9(별도 실패 주입은 5.1.26100.9711), Python 3.12.10, JDK 21.0.9, Gradle 9.6.0, MSYS2 GCC/g++ 16.1.0, Arduino CLI 1.6.0(`50a0e80da`), Seeed nRF52 Boards 1.1.13, ARM GCC 9-2019q4, Seeed Arduino LSM6DS3 2.0.7. Android 빌드 SDK와 로컬 도구 설정은 기존 `.tools`/`android/local.properties`를 사용했다.

TensorFlow의 Windows GPU 미지원·기존 deprecated 경고, ImuBleClient의 Android API deprecated 안내, Gradle 10 호환성 안내는 남아 있다. 검사·현재 빌드를 실패시키지는 않았다. Clang/MSVC 환경은 기존 host 링크 옵션 `-lm`과 맞지 않아 실패했으며, 공백 GCC 경로로 바꿔 실제 C parity를 통과했다. 첫 ARM 실행의 샌드박스 DLL relocation 문제는 실행 권한을 확보한 뒤 해결했으며 제품 실패로 집계하지 않았다.

재실행(프로젝트 루트, 공백 경로 GCC 파일이 필요):

```powershell
.\tools\verify-ecc-fixes.ps1 -SpaceCompilerPath 'C:\Users\zoonc\Desktop\RingPilot\.build\ecc-fixes-2026-11-12\GCC toolchain\bin\gcc.exe'
```

이 PC의 `GCC toolchain`은 설치된 `C:/msys64/mingw64`를 가리키는 git 제외 junction이다. 일반 사용자는 자신의 공백 포함 컴파일러 경로를 지정한다. 스크립트는 도구 설치·보드 업로드를 수행하지 않는다.

## 로그와 전달 파일

루트 `C:/Users/zoonc/Desktop/RingPilot/.build/ecc-fixes-2026-11-12/` 아래 산출물은 git 제외다.

- `final-validation/validation.log`, `stages.json`: 8개 PC 검증 단계 모두 exit 0.
- `python-cli-red.log`, `compiler-red.log`, `transport-red.log`: 수정 전 실패 근거. Android 원본 반례는 기존 `.build/review-repros/android/`에 보존했다.
- `baseline-python.log`, `baseline-gesture.log`, `baseline-stream.log`, `baseline-artifacts.json`: 수정 전 기준·펌웨어 해시. 두 baseline 빌드 폴더도 보존했다. APK 수정 전 해시는 원래 리뷰 보고서에 있다.
- `quoted-gcc-parity.log`: 별도 공백 경로 C parity 최초 통과. 최종 실행은 통합 로그에 있다.
- `pull-fixture-msEYqa/result.json`: 실제 PC 도구를 fake adb와 합성 디스크 자료로 실행한 목록·복사·해시 결과.
- `analysis-fixture-2R79VO/result.json`: 접미사 세션의 실제 완료시각 분석 CLI 결과. 합성 동작이며 인식 성능 측정이 아니다.
- `emulator-smoke-result.json`, `emulator-*.xml`, `emulator-session-closed.png`, `emulator-crash-log.txt`: 링 없는 UI 관찰.
- `emulator-pulled/phone-20261112-083338/`: 이번 앱에서 생성·종료한 빈 시험 세션의 session_info와 DONE. 기존 에뮬레이터 시험 세션도 보존 옵션으로 복사됐으며 삭제하지 않았다.
- `deliverables/`: 날짜를 붙인 APK, 두 펌웨어 HEX/DFU ZIP, SHA256SUMS, artifacts.json과 사용 범위 설명.
- `RingPilot-ecc-fixes-20261112.zip`: 위 전달 파일 묶음, **2159872 bytes**, SHA-256 `77f72ef00ac029d314aae4ece093e2ff6b214a0da0e39dd46dd4f4ec70ae8520`. 개별 5개 바이너리의 크기·해시를 다시 대조했다.

| 파일 | bytes | SHA-256 |
| --- | ---: | --- |
| RingPilot-ecc-fixes-20261112-debug.apk | 3499192 | `a26c1199bdaca994dca08f46f4f01b3d25c5d541a88d24b6b4cb46de8a740c5d` |
| gesture-infer-ecc-fixes-20261112.hex | 447128 | `25e729145619c05de82266aa2ca12fa68e413e48b0ba3f5fee0966db9f24a7c3` |
| gesture-infer-ecc-fixes-20261112-dfu.zip | 159818 | `10ab16686d5aa667efe7e6bd813f4db533b280c8b967e3ff935264a3c1d64bdc` |
| imu-ble-stream-ecc-fixes-20261112.hex | 360074 | `390b59845dac3cf8ac09138e584d36ce4e03b5a0593f1118607d3b1e5b63aa11` |
| imu-ble-stream-ecc-fixes-20261112-dfu.zip | 128868 | `42671552555ebf20bc0c163d7df424a5ba78ff65478ba341f0a78c6bdc0a8668` |

## 남은 실제 기기 확인

R2 계획 S9의 실제 링 연결·송신 혼잡·전원 재시작·물리 버튼 pause/resume·실제 스와이프·백그라운드 수집 시험은 실행하지 않았다. 에뮬레이터 홈 복귀가 실제 BLE 수신 유지의 증거는 아니다. 보드 업로드·새 자료 수집·전체 모델 재학습도 수행하지 않았다.

notify true는 BLE 스택의 수용이며 앱 실행 ACK가 아니다. 이미 SDK notify에 들어간 호출을 취소할 수 없는 한계, loop 기반 수집 펌웨어의 샘플 간격과 최대 100ms 대기 영향, TTL/큐 크기의 실제 사용 적합성은 보드 로그와 휴대폰 자료로 확인해야 한다. 실제 관찰을 확보하면 계획의 실기기 표와 진행기록에 별도로 추가한다.
