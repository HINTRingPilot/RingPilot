/* 연속 스트림 판정: 샘플을 넣으면 온라인 영점, 입력 처리, TCN 추론, 발행 규칙을 수행한다.
 * 발행 3판정(150 ms) 뒤 그때까지의 자이로를 영점으로 바꿔, 앞 동작이 다음 판정 창에 남지 않게 한다.
 * 발행 없이 끝난 큰 움직임(300 dps 초과 뒤 150 ms 동안 30 dps 미만)도 같이 지운다(실험 field-01).
 * 파이썬 기준은 ml/v2_stream.py(still_estimates, stream_inputs)와 ml/v2_erase.py(replay)다. */
#ifndef GESTURE_RUNTIME_H
#define GESTURE_RUNTIME_H

#include <stdint.h>

#include "gesture_tcn.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
  float scores[GT_CLASSES];
  float bias[3];
  int8_t issued;  /* 발행된 클래스 번호(1~4). 발행이 없으면 -1 */
} GrDecision;

void gr_reset(void);

/* 자이로 한 샘플(deg/s)을 넣는다. 이번 샘플에서 판정했으면 1을 돌려주고 out을 채운다(100 Hz에서 50 ms마다). */
int gr_push(const float gyro[3], GrDecision *out);

#ifdef __cplusplus
}
#endif

#endif
