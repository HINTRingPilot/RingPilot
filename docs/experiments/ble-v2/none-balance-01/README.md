# NONE 세션·클립 배분 비교

작성: 2026-10-25. 사용자 요청으로 [제안 1](../diagnostics/completion-review-01/decision.md)을 먼저 진행한다. 기존 336개 원본의 개발용 보정 비교이며 독립 최종 평가가 아니다.

## 실행 전 고정한 내용

- 바꾸는 요인은 NONE 종류 안의 세션·클립별 할당뿐이다. 양성 창, NONE 총수·종류별 수, 클립 안 창의 기존 shuffle/pop 우선순위, e·양성 폭, 정규화, 모델·optimizer·배치, seed·fold·후처리·선택 점수는 유지한다.
- 세션과 클립 순서는 고정 NONE seed 20261021로 섞는다. 각 종류에서 세션을 한 개씩 돌고, 각 세션 안에서 클립을 한 개씩 돈다. 부족한 용량만 남은 곳으로 재분배한다. 세션당 클립 수가 조금 다르므로 '창 수 비례'가 아니라 '세션 균형'을 비교하는 실험이다.
- 원래 선택기는 그대로 두고 새 모듈에서 실행한다. 기존 config/protocol/summary/예측을 수정하지 않는다.
- 각 전략에 원래 E 선택 원칙을 각각 적용한 대응 비교가 주 비교다. 같은 E 대응 비교도 전부 보고한다. 구체 규칙은 [spec.json](spec.json), 절차는 [plan.md](plan.md)에 있다.
- 개선·악화 표시는 사전에 정한 기술 보고 분류이며 통계적 유의성·동등성 판정이 아니다. 결과를 보고 기본 선택기를 자동 교체하지 않는다.

## 실행 순서

프로젝트 루트에서 기존 `ml/.venv/Scripts/python.exe`를 사용한다.

```powershell
& .\ml\.venv\Scripts\python.exe ml/v2_protocol.py --spec docs/experiments/ble-v2/none-balance-01/spec.json --out docs/experiments/ble-v2/none-balance-01/protocol.json
& .\ml\.venv\Scripts\python.exe ml/v2_none_cal.py init-all --protocol docs/experiments/ble-v2/none-balance-01/protocol.json
& .\ml\.venv\Scripts\python.exe ml/v2_none_cal.py run-all --protocol docs/experiments/ble-v2/none-balance-01/protocol.json --parallel 5
& .\ml\.venv\Scripts\python.exe ml/v2_none_cal.py verify-all --protocol docs/experiments/ble-v2/none-balance-01/protocol.json
& .\ml\.venv\Scripts\python.exe ml/v2_none_compare.py --protocol docs/experiments/ble-v2/none-balance-01/protocol.json
```

S-P5 → C → S-P1~P4 순서로 실행한다. 분할당 5 seed를 최대 5개 프로세스로 병렬 실행하며 전체 125회 학습이다. 재실행 시 기존 결과는 덮어쓰지 않는다. 중간 실패 파일이 있으면 로그와 입력 해시를 확인한 뒤 복구 계획을 기록한다.

새 결과·학습 선택 manifest는 이 폴더의 `results/`, 검증 점수 배열은 `ml/runs/NONE-BAL-01-<분할>/`에 저장한다. 각 실행은 학습용 내부 fold만 입력으로 사용한다. 입력 무결성 검사는 전체 원본의 해시를 읽으며 '평가용 원본 파일을 전혀 읽지 않음'이라는 뜻은 아니다.

## 영상 관찰 준비

영상 갈래의 준비 내용은 [video-preparation.md](video-preparation.md)에 있다. 촬영·사람 주석·실측 동기화·앱/펌웨어 변경은 이번 실행에 포함하지 않는다.

## 현재 상태

구현·테스트 후 protocol을 고정하고 실행할 예정이다. 이 문장은 결과를 보기 전의 계획이다. 실제 실행 결과와 해시 검증은 완료 후 아래에 추가한다.
