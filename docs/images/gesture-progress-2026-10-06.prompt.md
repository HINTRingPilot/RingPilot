# 인포그래픽 생성 프롬프트

생성 방식: 내장 image_gen. 아래는 실제 전달한 프롬프트다.

Use case: infographic-diagram. Create a polished Korean infographic for IT-literate project teammates with little AI expertise. Portrait large high-resolution poster about 2:3 aspect ratio, crisp Korean typography, white/off-white background, navy text, teal completed status, blue ongoing, amber caveats, spacious modern editorial layout. Clear minimal line icons of ring/IMU waveform/neural network/phone; no photo, no invented hardware design. Render exact Korean copy below clearly and accurately. Strong hierarchy, do not overcrowd. Six blocks flowing top to bottom. No extra statistics. Graph bars must start at zero and be proportional.

HEADER:
"RingPilot"
"제스처 인식 개발 현황"
"2026.10.06 · 팀 공유"
"센서 수집과 모델 실험 완료, 실시간 통합은 다음 단계"

BLOCK 1 title "01  무엇을 만들고 있나"
Flow with 4 nodes:
"손가락 움직임" → "6축 센서 기록" → "AI 방향 판정" → "스마트폰 스와이프"
Under node 2: "가속도 + 회전 · 초당 100회"
Under node 3: "상·하·좌·우·명령 없음"
Status strip: "완료: BLE → Android 4방향 스와이프" / "진행 중: 움직임 → AI → BLE 연결"

BLOCK 2 title "02  동작을 어떻게 읽나"
Show simple waveform with outgoing and return lobes, labeled "방향 이동 → 자연 복귀".
A bracket over past signal reads "최근 1.6초를 보고, 0.05초마다 판단"
At completion marker label "복귀 완료"; highlight short following interval labeled "완료 후 0.15초: 방향 라벨"
Rest caption "그 외: NONE = 지금 새 명령 없음"
Small note "1.6초는 과거 입력 길이이며, 고정 대기시간이 아님"

BLOCK 3 title "03  데이터 준비"
Three stat cards:
"80회" / "2회 수집 세션의 원시 동작"
"54개" / "자동 주석 기준 통과 원본"
"145 → 725개" / "학습 창 5배 증강"
Caption "작은 회전·잡음으로 변형 · 테스트 36개는 원본 유지"
Small note "증강은 새 동작을 실제로 수집한 것과 다름"

BLOCK 4 title "04  모델 구조를 바꾸며 비교"
Subtitle "같은 증강 데이터 · 같은 테스트 36개 · 창 단위 정확도"
Three horizontal zero-based bars:
"1층 CNN" "44.44% · 16/36"
"2층 CNN + Dropout" "63.89% · 23/36"
"3층 CNN + Dropout" "66.67% · 24/36"
Caption "CNN: 시간 패턴을 찾는 신경망"
"Dropout: 특정 특징에만 의존하지 않도록 학습"
Amber note "2층 → 3층 개선은 1개 차이 · 우열 확정은 어려움"

BLOCK 5 title "05  숫자보다 중요한 발견"
Two side-by-side cards:
"검증 방식 점검"
"1층 증강 모델: 내부 검증 98.6% / 테스트 44.44%"
"유사한 증강본이 내부 검증에 섞였을 가능성"
and
"현재 약점"
"RIGHT ↔ NONE 구분"
"일상 움직임 데이터 보완 필요"
Below small full-width caution:
"증강 자체의 효과는 미확정 · 동일 테스트로 증강 전후 비교 필요"
"테스트 36개를 반복 사용 중 · 최종 확인용 새 데이터 필요"

BLOCK 6 title "06  다음 확인"
Numbered compact horizontal/vertical steps:
"1  NONE 구성 보완" / "정지·일상 움직임 반영"
"2  새 세션으로 평가" / "원본·증강본을 함께 분리"
"3  연속 동작 + 보드 검증" / "오작동·중복·지연·메모리 측정"
Footer:
"현재 66.67%는 실제 스와이프 성공률이 아닌, 작은 데이터셋의 창 분류 결과"
"근거: docs/ModelExperiments.md · docs/진행기록.md"
Do not claim real-time gesture control works, do not describe 725 as independent gestures, do not say augmentation improved test accuracy. All percentages refer to recorded experiment results, not new experiments.
