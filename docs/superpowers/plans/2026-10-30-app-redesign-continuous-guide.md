# Android 앱 디자인 개편과 연속 안내 모드 계획

작성: 2026-10-30. 상태: **계획만, 미실행.** 관련 설계: `docs/superpowers/specs/2026-10-30-v2-continuous-ground-truth-design.md`(5절 앱 변경). 남은 일: `docs/TODO.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**목표:** 기존 수집 앱(`android/`)을 카드 보드 감성의 화면으로 바꾸고, Task 8에 필요한 연속 안내 수집과 안내 기록을 더한다. 실기기가 없어도 개발·확인할 수 있게 개발용 가짜 링을 둔다.

**접근:** 데이터의 정확성이 화면보다 먼저다. 기록 시각·파일 형식·기존 수집 동작은 바꾸지 않는다. 시각과 파일을 다루는 새 로직(`GuidedStream`, `CueLog`)은 화면과 분리한 순수 Java로 만들어 PC에서 시험한다. 화면은 단계별로 만들고, 에뮬레이터와 가짜 링으로 스크린샷을 보며 다듬는다.

**기술:** Java 17, Android SDK 35(minSdk 31), 외부 라이브러리 없음(지금처럼 프레임워크 View만, 코드로 화면 구성). 테스트는 기존 방식(`android/tests/*.java`를 `javac`·`java`로 직접 실행).

## 0. 현재 상태(2026-10-30 확인)

- 화면: `MainActivity.createContentView()`가 `LinearLayout`·`Button`·`TextView`를 코드로 쌓는다. XML 레이아웃·테마·외부 의존성이 없다(`app/build.gradle`에 플러그인만). `MainActivity` 798줄에 화면·세션·기록·안내 수집이 모두 들어 있다.
- 기록: 정해진 길이(방향 4 s, idle/other 10 s)와 길이 제한 없는 연속 기록. CSV `timestamp` = (보드 슬롯 − 첫 슬롯) × 10 ms. 사이드카 `.capture.json`(`CaptureSidecar`).
- 안내 수집: 음성 → 1.2 s → 삑(기록 시작) → 1.0 s → 삐빅(동작) → 4 s 저장. `postGuide`·`guideGeneration`으로 단계 예약.
- 그 밖: `ImuBleClient`(BLE 수신, MTU 247, 자동 재연결), `SwipeAccessibilityService`(제어용 스와이프, 아직 수집 화면과 연결 안 됨).
- 테스트: `android/tests/CaptureSidecarTest.java` + `run-sidecar-tests.ps1`(JDK의 `javac`·`java`).
- 빌드 환경: 진행기록에는 Android Studio 동봉 JBR과 저장소 `.tools`의 Gradle/SDK로 `assembleDebug`에 성공한 기록이 있다. **zoon_computer에는 `.tools` 폴더가 없다.** 이 PC에서 빌드하려면 환경 확인·설치가 먼저다(Task 0).

## 1. 디자인 방향: "Soft Pinboard"(카드 보드 감성)

Pinterest 같은 핀보드의 **일반적인 느낌**(카드가 엇갈려 쌓인 2열 보드, 둥근 모서리, 넉넉한 여백, 따뜻한 바탕)을 빌린다. **Pinterest의 이름·로고·대표 빨간색 등 상표 요소는 쓰지 않는다.** 색과 글꼴은 이 앱만의 것으로 정한다.

| 요소 | 결정(기본값, 0단계에서 확인) |
|---|---|
| 첫인상 | 종이 위에 메모 카드를 핀으로 꽂아 둔 보드. 각 수집 모드가 한 장의 카드다 |
| 배치 | 홈은 **엇갈린 2열 카드 보드**(카드 높이가 내용에 따라 다름). 기록 중에는 **한 장짜리 집중 화면**으로 전환 |
| 바탕·면 | 밝은 테마: 따뜻한 종이색 바탕 `#F6F1EA`, 카드 `#FFFDF9`, 글자 `#231F1A`, 보조 글자 `#7A7064`. 어두운 테마(누워서 기록할 때 눈부심 줄이기): 바탕 `#15120F`, 카드 `#211D18`, 글자 `#F3ECE2` |
| 방향 색(색만으로 구분하지 않고 화살표·글자 함께) | 위 `#D9734E`(테라코타), 아래 `#3E5C8A`(깊은 파랑), 왼쪽 `#6F9E84`(세이지), 오른쪽 `#C9A35A`(머스터드) |
| 모양 | 카드 모서리 20 dp, 버튼은 알약 모양(높이 48 dp 이상), 카드 그림자는 아주 옅게(elevation 2~4 dp) |
| 글꼴 | 제목: **고운돋움(Gowun Dodum)** — 둥글고 따뜻한 한글 제목체. 본문·숫자: **IBM Plex Sans KR** — 읽기 쉽고 숫자가 또렷함. 둘 다 SIL OFL(앱에 넣어 배포 가능). `res/font/`에 넣는다 |
| 움직임 | 홈 첫 표시 때 카드가 위에서 아래로 차례로 나타남(지연 40 ms씩, 1회만). 카드 누르면 0.97배로 살짝 눌림. 집중 화면에서 "삐빅" 순간 방향 화살표가 커지며 나타나고 원형 진행 표시가 돈다. 녹화 중 화면 효과는 안내 시각 기록보다 늦게 실행되어도 되지만, **안내 시각 기록을 늦추면 안 된다** |
| 기억에 남을 한 가지 | 집중 화면의 **커다란 방향 카드**: 화면 2/3를 채우는 방향 색 카드와 화살표. 반지 낀 손을 보면서 곁눈으로도 알아볼 수 있게 |
| 접근성 | 글자 대비 4.5:1 이상, 터치 영역 48 dp 이상, 색 + 화살표 + 글자 함께, TalkBack 설명(`contentDescription`) |

### 화면 구성

**홈(카드 보드, 2열 엇갈림)**

| 카드 | 내용 | 높이 |
|---|---|---|
| 링 상태 | 연결·수신 Hz·일시정지 여부, "다시 연결" | 짧음 |
| 세션 | 세션 이름, 메모 입력, 지금까지 저장한 개수, "세션 종료" | 중간 |
| 방향 안내 수집(기존) | 방향별 횟수, 시작 | 중간 |
| **연속 안내 수집(새)** | 블록 A~E 작은 칩, 블록별 예상 시간, 시작 | 김 |
| idle / other 10초(기존) | 버튼 두 개 | 짧음 |
| 연속 기록(기존) | 시작·중지, 경과 시간 | 짧음 |
| 최근 기록 | 최근 이벤트 몇 줄 | 김 |
| 도움말 | 접어 두는 사용법 | 짧음 |
| (나중) 제어 모드 | 보드가 판정 결과를 보낼 수 있게 된 뒤 | — |

**집중 화면(기록 중)**: 위쪽에 블록 이름과 진행(예: "A 단일 방향 · 12/32"), 가운데 큰 방향 카드(대기 중에는 "가만히…", 삐빅 순간 방향), 아래 알약 버튼(일시정지 / 방금 안내 취소 / 방금 실수(블록 D) / 끝내기). 기존 방향 안내 수집도 같은 집중 화면을 쓴다.

## 2. 지킬 것(전역 제약)

- 기존 수집 동작·시각·파일 이름과 형식(`raw_*.N.csv`, `idle.N.csv`, `other.N.csv`, `continuous.N.csv`, `.capture.json`, `session_info.txt`, `SESSION_DONE`)을 바꾸지 않는다. 학습 데이터 도구가 이 형식에 기대고 있다.
- 펌웨어는 바꾸지 않는다(`imu_ble_stream` 그대로).
- 안내 시각은 신호음을 내는 호출 직전에 `SystemClock.elapsedRealtime()`으로 읽고, 같은 순간의 마지막 슬롯·도착 시각을 `captureLock` 안에서 읽는다. 화면 애니메이션은 그 뒤에 실행한다.
- 가짜 링은 **디버그 빌드에서만** 켤 수 있고, 가짜 링으로 만든 세션 폴더는 이름과 `session_info.txt`에 `fake=true`를 남겨 학습 데이터와 섞이지 않게 한다.
- 화면 구현은 단계마다 에뮬레이터 스크린샷으로 확인한다. 실기기 동작은 사용자가 확인했을 때만 "검증 완료"로 쓴다(AGENTS.md).
- 커밋은 사용자 확인 후.

## 3. 파일 구조(계획)

| 파일 | 역할 | 새/수정 |
|---|---|---|
| `app/src/main/java/.../GuidedStream.java` | 블록 A~E 정의와 안내 순서·간격 생성(시드 고정, 순수 Java) | 새 |
| `app/src/main/java/.../CueLog.java` | 안내 기록 CSV 한 줄 만들기와 센서 시각 추정(순수 Java) | 새 |
| `app/src/main/java/.../FakeImuSource.java` | 디버그용 가짜 링: 100 Hz 슬롯·패킷을 만들고, 안내가 나면 0.5~0.9 s 뒤 그 방향의 합성 동작을 넣는다 | 새 |
| `app/src/main/java/.../ui/PinTheme.java` | 색·크기·글꼴·모양 토큰, 밝은/어두운 테마 | 새 |
| `app/src/main/java/.../ui/Cards.java` | 카드·알약 버튼·칩 만드는 함수(둥근 모서리 `GradientDrawable`, 그림자, 눌림 효과) | 새 |
| `app/src/main/java/.../ui/BoardLayout.java` | 2열 엇갈림 배치(두 열 중 낮은 쪽에 다음 카드를 넣는 단순 방식) | 새 |
| `app/src/main/java/.../ui/HomeScreen.java`, `ui/FocusScreen.java` | 홈·집중 화면 구성. 버튼은 `MainActivity`의 기존 메서드를 부른다 | 새 |
| `app/src/main/java/.../MainActivity.java` | 화면 만들기를 `ui/`로 옮기고 연결만 남김. 연속 안내 수집 로직 추가 | 수정 |
| `app/src/main/res/font/gowun_dodum.ttf`, `ibm_plex_sans_kr_*.ttf` + 라이선스 파일 | 글꼴 | 새 |
| `app/src/main/res/values/themes.xml`, `values-night/themes.xml` | 창 배경·상태 표시줄 색 | 새 |
| `android/tests/GuidedStreamTest.java`, `CueLogTest.java` | 순수 Java 시험 | 새 |
| `android/tests/run-sidecar-tests.ps1` → `run-java-tests.ps1` | 새 시험도 함께 컴파일·실행 | 수정 |
| `tools/pull-phone-sessions.js` | `guided_*.csv`, `*.cues.csv`를 가져오는지 확인, 필요하면 수정 | 확인/수정 |

## Task 0: 결정과 빌드 환경 확인(약 20분 + 설치 시간)

- [ ] 🙋 디자인 방향 확인: 1절 표(색·글꼴·밝은/어두운 테마 기본값)를 그대로 갈지. 바꿀 점이 있으면 표를 고친다.
- [ ] 🙋 정답 표시 설계 9절 결정(블록 구성·분량). `GuidedStream`의 기본값이 된다.
- [ ] 🤖 zoon_computer 빌드 환경 확인: `java -version`(JDK 17+), Android Studio 설치 여부와 동봉 JBR 경로, Android SDK(Platform 35, Build-Tools)와 `ANDROID_HOME`, 에뮬레이터 이미지(API 34 이상) 유무. 없으면 설치 목록을 사용자에게 알리고 설치는 사용자 확인 뒤에 한다(내려받기 필요).
- [ ] 🤖 지금 앱이 그대로 빌드되는지 확인: `android/gradlew.bat assembleDebug`(JAVA_HOME 설정 후). 실패하면 원인을 기록하고 Task 1로 넘어가지 않는다.

## Task 1: 안내 순서 만들기 `GuidedStream`(순수 Java, 약 30분)

**인터페이스:**
```java
final class GuidedStream {
    enum Block { A, B, C, D, E }
    static final class Step {
        final int cueId;            // 블록 안 1부터
        final String intended;      // "UP" | "DOWN" | "LEFT" | "RIGHT" | 쌍이면 "UP+DOWN" | D·E는 null
        final long gapBeforeMs;     // 직전 안내(또는 블록 시작)부터 이번 신호음까지
    }
    /** 블록 안 안내 목록. 같은 seed면 같은 순서·간격이다. D·E는 빈 목록(시작·끝만 기록). */
    static List<Step> schedule(Block block, long seed);
    /** D·E의 길이(ms). A·C는 마지막 안내 뒤 4 s, B는 6 s를 더한 예상 길이. */
    static long expectedDurationMs(Block block, List<Step> steps);
}
```
- 기본값(설계 4절): A = 4방향 × 8, 간격 3,000~5,000 ms. B = 쌍 16개(반대 8: 위아래·아래위·좌우·우좌 각 2, 같은 방향 4, 직각 4), 간격 4,000~6,000 ms. C = 단일 16개, 간격 1,000~1,500 ms. D = 10분(활동별로 블록을 다시 시작), E = 2분.
- 섞을 때 같은 방향이 3번 넘게 이어지지 않게 한다(A·C).

- [ ] **시험 먼저**(`android/tests/GuidedStreamTest.java`): 같은 seed → 같은 결과, 다른 seed → 다른 순서; A는 방향별 정확히 8개; B는 반대 8·같은 4·직각 4; 간격이 블록 범위 안; 같은 방향 4연속 없음; D·E는 빈 목록.
- [ ] 실패 확인 → 구현 → `android/tests/run-java-tests.ps1` 통과.

## Task 2: 안내 기록 `CueLog`(순수 Java, 약 20분)

**인터페이스:**
```java
final class CueLog {
    static final String HEADER = "cue_id,kind,intended,target_cue_id,tone_elapsed_ms,last_slot,last_arrival_elapsed_ms,first_slot,est_data_ms";
    /** 안내의 센서 시각 추정 = (lastSlot - firstSlot) * 10 + (toneElapsedMs - lastArrivalMs). 아직 샘플이 없으면 -1. */
    static long estDataMs(long toneElapsedMs, long lastSlot, long lastArrivalMs, long firstSlot);
    /** 한 줄(줄바꿈 포함). kind: cue | block_start | block_end | void | mistake. 쉼표가 든 값은 거부한다. */
    static String row(int cueId, String kind, String intended, Integer targetCueId,
                      long toneElapsedMs, long lastSlot, long lastArrivalMs, long firstSlot);
}
```
- [ ] **시험 먼저**(`android/tests/CueLogTest.java`): 계산식(예: lastSlot 1,250, firstSlot 1,000, tone 50,030, arrival 50,000 → 2,530 ms); 샘플 전(-1); 줄 형식과 열 수; void 줄에 target_cue_id; 쉼표 든 intended 거부.
- [ ] 실패 확인 → 구현 → 통과. 시험 스크립트를 `run-java-tests.ps1`로 넓혀 세 시험을 모두 돌린다.

## Task 3: 개발용 가짜 링 `FakeImuSource`(약 40분)

- 목적: 실기기 없이 에뮬레이터에서 화면·기록·안내 기록·파일 저장을 끝까지 돌려 본다.
- 동작: 10 ms마다 슬롯을 하나씩 늘리며 6축 값(정지: 중력 + 작은 잡음 + 자이로 치우침)을 만들고, 실제처럼 여러 샘플을 묶어 `Listener.onSamples(firstSlot, raw, count)`로 넘긴다. 안내 신호음 뒤 0.5~0.9 s(무작위)에 그 방향의 합성 동작(주축 자이로가 가는 쪽으로 약 300 dps, 0.3 s 뒤 반대로 돌아옴)을 넣는다. 가끔 슬롯을 일부러 빠뜨리는 옵션으로 공백 처리도 확인한다.
- 켜는 방법: 디버그 빌드에서만 홈의 "링 상태" 카드를 길게 누르면 "가짜 링" 전환. 켜지면 세션 이름 뒤에 `-fake`, `session_info.txt`에 `fake=true`.
- `ImuBleClient`와 같은 `Listener`를 쓰므로 `MainActivity`는 원천만 바꿔 끼운다(기록 로직은 그대로).
- [ ] 🤖 구현, 에뮬레이터에서 방향 안내 수집 4회와 연속 기록 10초를 돌려 파일이 기존 형식대로 생기는지 확인(adb로 꺼내 `v2.read_sensor`·`v2_stream.read_stream`으로 읽기).

## Task 4: 디자인 토큰과 카드 부품(약 1시간)

- [ ] 🤖 글꼴 파일과 라이선스(OFL) 추가: `res/font/`, `docs/` 또는 `android/` 아래 `THIRD_PARTY_LICENSES.md`에 출처·라이선스 기록. 내려받기는 사용자 확인 뒤.
- [ ] 🤖 `PinTheme`: 1절 색·크기·글꼴. 시스템 어두운 테마를 따르고, 홈에서 수동 전환도 가능.
- [ ] 🤖 `Cards`: 카드(둥근 20 dp, 옅은 그림자, 안쪽 여백 16 dp), 알약 버튼(기본·강조·위험), 칩(블록 선택), 방향 카드(색 + 화살표 + 글자), 눌림 효과.
- [ ] 🤖 `BoardLayout`: 화면 폭에 맞춰 2열, 다음 카드를 더 낮은 열에 놓는다. 폭이 좁으면(가로 360 dp 미만) 1열.
- [ ] 확인: 에뮬레이터에서 부품 견본 화면 스크린샷(밝은·어두운 테마) → 대비·크기 점검.

## Task 5: 홈·집중 화면으로 바꾸기(동작 그대로, 약 1.5시간)

- [ ] 🤖 `MainActivity.createContentView()`의 화면 구성을 `HomeScreen`·`FocusScreen`으로 옮긴다. 버튼은 기존 메서드(`startGuide`, `togglePause`, `redoLast`, `startFixedLong`, `toggleContinuous`, `endSession`, `connectRing`)를 그대로 부른다. `prompt()`·`event()`·`updateProgress()`는 새 화면에 같은 정보를 그린다.
- [ ] 🤖 기존 방향 안내 수집이 집중 화면을 쓰게 연결(대기 "가만히…" → 삐빅 순간 방향 카드).
- [ ] 확인(동작 불변): 가짜 링으로 방향 안내 수집·idle·other·연속 기록·세션 종료를 한 번씩 하고, 만들어진 파일 이름·행 수·사이드카 내용이 바꾸기 전 빌드와 같은지 비교(바꾸기 전에 같은 시나리오로 기준 파일을 먼저 만들어 둔다). 스크린샷으로 화면 확인.

## Task 6: 연속 안내 수집(약 1.5시간)

- [ ] 🤖 홈의 "연속 안내 수집" 카드: 블록 칩 A~E, 예상 시간, 시작.
- [ ] 🤖 시작하면: 연속 기록(`startCapture("guided_<블록>", 0, ...)`) + 같은 번호의 `guided_<블록>.<N>.cues.csv` 생성(첫 줄 `block_start`, `GuidedStream` seed와 순서 기록) → `GuidedStream.schedule` 순서대로 음성 → 짧은 대기(약 700 ms) → 신호음, 신호음 직전에 `CueLog.row(...)` 한 줄(`fileWriter`로 순서대로 씀) → 끝나면 `block_end` 줄 후 기록 마무리.
- [ ] 🤖 `acceptSamples` 안에서 마지막 슬롯·도착 시각을 저장(이미 있는 `captureLock` 안), 안내 기록이 같은 잠금으로 읽는다.
- [ ] 🤖 집중 화면 버튼: 일시정지(안내만 멈춤, 기록은 계속하고 `block_end`/`block_start`로 구간 표시), 방금 안내 취소(`void`), 방금 실수(블록 D, `mistake`), 끝내기.
- [ ] 🤖 링이 끊기면 안내를 멈추고, 다시 이어지면 `block_start`를 새로 쓰고 계속(설계 5절).
- [ ] 확인: 가짜 링으로 블록 A를 짧게(안내 8개로 줄인 디버그 설정) 돌려 `.cues.csv`의 `est_data_ms`와 CSV 안 합성 동작 시작 시각의 차이가 가짜 링이 넣은 지연(0.5~0.9 s) 범위인지 PC에서 확인. 이게 실제 시험 녹화 전에 시각 맞추기 계산이 맞는지 보는 첫 확인이다.

## Task 7: PC로 옮기기와 문서(약 30분)

- [ ] 🤖 `tools/pull-phone-sessions.js`가 `guided_*.csv`·`*.cues.csv`·`.capture.json`을 가져오는지 확인하고, 아니면 고친다(`node --check`).
- [ ] 🤖 `android/README.md`에 새 화면·연속 안내 수집·가짜 링 사용법 추가.
- [ ] 🤖 `docs/진행기록.md` 기록, `docs/TODO.md` 갱신.

## Task 8: 실기기 확인(🙋 사용자, 실기기 생긴 뒤)

- [ ] 휴대폰에 설치(`adb install -r app-debug.apk`), 링 연결, 기존 방향 안내 수집 몇 회로 예전과 같게 저장되는지 확인.
- [ ] 연속 안내 수집 블록 A 5분 시험 녹화 → PC로 옮기기 → 안내 → 움직임 지연 분포 확인(설계 3절). 이후 본 녹화.

## 하지 않는 것(이 계획 범위 밖)

- 제어 모드(실제 스와이프)와 보드 판정 결과 수신: 보드 추론(Task 7a)과 GATT 메시지 형식이 정해진 뒤 별도 설계.
- 외부 UI 라이브러리(Material Components, RecyclerView 등) 도입: 카드가 열 장 안팎이라 필요 없다. 늘어나면 그때 다시 본다.
- 학습·평가 코드 변경.

## 시간 합계(대략)

Task 0 약 20분(+설치), 1 약 30분, 2 약 20분, 3 약 40분, 4 약 1시간, 5 약 1.5시간, 6 약 1.5시간, 7 약 30분. **합계 약 6시간**(에뮬레이터 스크린샷을 보며 다듬는 시간 포함, 빌드 환경 설치 시간 제외). 실기기 확인(Task 8)은 별도.

## 결정이 필요한 것(사용자)

1. 디자인 방향(1절 표)과 글꼴 두 가지, 기본 테마(밝은/어두운/시스템 따라감).
2. 정답 표시 설계 9절(블록 구성·분량).
3. zoon_computer에 빌드 환경(Android Studio·SDK·에뮬레이터)을 설치할지, 빌드 환경이 있는 다른 PC에서 할지.
