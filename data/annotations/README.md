# 제스처 완료 시점 주석

`gesture-completions.csv`는 Edge Impulse 프로젝트 `1122630`의 방향별 3초 원시 샘플에 대한 자연 복귀 완료 시점 후보표다. 원시 센서 값이나 Edge Impulse 인증 정보는 저장하지 않는다.

## 현재 계약

- 이벤트 완료 `completion_ms`: 방향 이동과 자연 복귀의 자이로 에너지 99%가 지난 뒤, 최종 자세 부근에서 IMU가 180 ms 안정되기 시작한 시점
- 방향 양성 목표: `completion_ms <= t < positive_target_end_ms`
- 현재 양성 폭: 150 ms
- 그 밖의 시점: `NONE`
- 3초 `raw_*` 파일 라벨을 그대로 전체 window에 상속하지 않는다.

끝점에서 잠깐 멈췄다가 복귀하는 동작을 조기 완료로 오인하지 않도록 안정 구간 검색은 전체 자이로 에너지 99% 이후에만 시작한다. 이 정의는 초기 보수안이다. 연속 replay에서 지연이 과도하면 별도의 조기 이벤트 모델과 비교한다.

## 상태와 플래그

- `AUTO`: 현재 자동 기준을 통과한 완료 시점 후보
- `REVIEW`: 완료 시점 후보는 기록했지만 파형을 다시 확인해야 하는 샘플. 첫 모델의 기본 학습 목록에서는 제외한다.
- `early_motion`: 첫 0.5초 안에 유의미한 동작 에너지가 존재
- `late_completion`: 완료 시점이 2.5초 이후
- `return_pose_offset`: 처음과 끝의 중력 방향 차이가 12도 이상

현재 40개 중 `AUTO` 30개, `REVIEW` 10개다. `REVIEW`를 삭제한다는 뜻은 아니며, 어려운 사례 및 연속 replay 평가 자료로 보존한다.

## 다시 계산

Edge Impulse CLI 로그인이 유지된 환경에서 다음을 실행한다.

```powershell
node tools/suggest-gesture-completions.js --project-id 1122630 --format csv
```

이 명령은 원격 데이터를 읽기만 하며 샘플과 라벨을 수정하지 않는다. 출력 결과를 검토하지 않고 기존 CSV 위에 자동 반영하지 않는다.
