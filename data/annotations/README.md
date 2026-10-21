# 제스처 완료 시점 주석

세션별 방향 샘플(`raw_*.N.csv`, 3초)에 대한 자연 복귀 완료 시점 후보표다. 원시 센서 값이나 인증 정보는 저장하지 않는다.

| 파일 | 대상 |
|---|---|
| `gesture-completions-session-2026-10-21-phone.csv` | `data/sessions/phone-20261021-091621/` (휴대폰 앱 수집, 20개) |

2026-10-21에 이전 데이터(Edge Impulse 1차 세션 46개, USB 2차 세션 40개, 학습 윈도우)와 그 주석을 사용자 요청으로 모두 삭제했다. 경과는 `docs/진행기록.md`에 있다.

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
- `no_180ms_settle`, `second_motion_cluster`, `near_gyro_limit`: 안정 구간 없음, 두 번째 동작 덩어리, 자이로 한계 근접
- `return_pose_offset`은 2026-10-19부터 판정에 쓰지 않는다(최종 자세가 시작 자세와 같을 필요가 없음). 각도 값은 `return_angle_deg`로 참고용 기록만 한다.

`REVIEW`를 삭제한다는 뜻은 아니며, 어려운 사례 및 연속 replay 평가 자료로 보존한다.

## 다시 계산

```powershell
node tools/suggest-gesture-completions.js --local-dir data/sessions/<세션> --format csv > data/annotations/gesture-completions-session-<세션>.csv
```

출력 결과를 검토하지 않고 기존 CSV 위에 자동 반영하지 않는다. 윈도우를 만들 때는 `tools/export-gesture-windows.js --annotations <주석 CSV들>`로 사용할 주석을 명시한다(기본값 `gesture-completions.csv`는 삭제됐다).
