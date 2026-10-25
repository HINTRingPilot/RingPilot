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

**완료(2026-10-25):** 코드 `54115ef`를 보존하고 protocol을 학습 전에 저장·커밋(`f5dc8ee`)한 뒤 6개 분할의 5 seed, 125회 보정 학습을 모두 실행했다. 새 최종 학습·평가·영상 촬영·보드 추론은 하지 않았다. 원격 푸시도 하지 않았다.

## 결과

주 비교는 각 전략에 같은 E 선택 원칙을 적용한 결과다. **NONE의 세션 편중은 해소했지만 정검출률 개선은 확인하지 못했다.** 선택 점수는 6개 중 5개에서 올랐으나 선택 E의 평균 정검출률은 6개 모두 낮아졌다. 이는 통계적 악화 판정이 아니라 저장된 개발 보정 값의 기술이다.

| 분할 | 기존 E→새 E | 정검출률 기존→새 | 선택 점수 기존→새 |
|---|---|---|---|
| S-P5 | 60→1 | 34.4%→13.0% | −0.0734→−0.0177 |
| C | 1→1 | 17.8%→15.5% | −0.0729→−0.0576 |
| S-P1 | 1→1 | 12.3%→12.2% | −0.0462→−0.0361 |
| S-P2 | 1→1 | 11.4%→9.1% | −0.0381→−0.0254 |
| S-P3 | 5→1 | 26.8%→10.5% | +0.0017→−0.0017 |
| S-P4 | 1→1 | 9.6%→8.4% | −0.0102→+0.0017 |

**새 선택 E는 모든 분할에서 1**이다. S-P5·S-P3의 큰 정검출률 감소에는 선택 E가 달라진 영향이 섞이므로 같은 E 비교도 봐야 한다. 같은 E=60에서는 C 36.95%→39.07%, S-P5 34.43%→31.81%로 방향이 다르다. 공통 E 전체, seed별 대응 차이와 상승/하락/동일 개수, 세션별 결과는 [comparison.md](comparison.md)와 [comparison.json](comparison.json)에 있다. 모든 주 비교는 사전 기술 규칙상 '지표 간 교환관계'다.

선택 점수는 정검출에서 미매칭 발행을 빼므로, 덜 발행해 미매칭이 줄면 정검출이 감소해도 점수가 오를 수 있다. 새 S-P5는 무발행 클립 72.2%, C는 63.2%다. 점수 상승을 사용 가능한 성능이나 무발행 문제의 해결로 쓰지 않는다. 기본 `v2.choose_training()`은 변경하지 않았다.

## 검증과 보존

- 전체 테스트 144개 통과(43.901초). 새 경로에 원래 선택기를 넣으면 학습·검증 배열과 정규화가 기존과 정확히 같다. 새 입력의 1 epoch 점검 학습은 protocol 이전 코드 점검용이며 선택에 쓰지 않았다.
- 초기화 25개 fold에서 양성·총 NONE·종류별 개수·정규화가 기준선 config와 일치했다. 학습 manifest의 별도 재집계도 25/25 통과([selection-audit.json](selection-audit.json)). 각 종류의 세션별 선택 개수 차이는 최대 1이며, 예를 들어 C fold 0은 각 세션에 진행 중 28개·완료 후 28개씩 배분됐다.
- 학습 30 seed 실행 모두 성공. seed당 전체 fold 학습 시간 최소/중앙값/최대 42.62/43.41/63.92초. 모든 실행에서 실제 intra/inter 스레드 1/1·결정성 True·oneDNN off를 기록했다.
- `verify-all` 재집계와 저장 summary 일치. NPZ를 별도로 읽어 125개 fold·56,350개 원본×epoch에서 창 시각·정답 라벨·발행·분류·지연·누락 일치 확인([verification.json](verification.json), 점수 배열별 raw SHA-256 포함). 이것은 56,350개의 독립 동작을 시험했다는 뜻이 아니다.
- 기존 보호 manifest 702개 추가·삭제·변경 0. 기존 protocol/config/summary/예측을 수정하지 않았다. 새 결과는 이 폴더와 `ml/runs/NONE-BAL-01-*`에 분리했다. 코드 변경은 현재 실험의 새 모듈뿐이다.

## 다음

이번 결과만으로 NONE 배분이 조기 발행의 주원인이라고 결론 내리거나 기본 선택기를 교체하지 않는다. 자동 e의 타당성은 여전히 미확인이다. 영상 독립 관찰을 위한 실제 동기화 파일럿, 또는 발행·잠금 상태의 별도 개발용 비교 중 다음 요인을 정하고 새 protocol로 수행한다. 기존 336개와 이번 결과는 개발 자료이며 독립 최종 평가에는 별도 자료가 필요하다.
