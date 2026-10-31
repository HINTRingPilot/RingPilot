/* 제스처 TCN 추론(float32). Keras 모델(ml/model.py build_tcn)과 출력이 같고, 마지막 시점에 필요한 칸만 계산한다.
 * 가중치와 계산 칸 표는 ml/v2_export_c.py가 만든 gesture_weights.h에 있다. 동적 메모리를 쓰지 않는다. */
#ifndef GESTURE_TCN_H
#define GESTURE_TCN_H

#include "gesture_weights.h"

#ifdef __cplusplus
extern "C" {
#endif

/* 창 하나(오래된 샘플 먼저)의 원시 자이로(deg/s)와 영점으로 모델 입력(자이로 3 + 회전각 3)을 만든다. */
void gt_prepare(const float gyro[GT_WINDOW][3], const float bias[3], float x[GT_WINDOW][GT_CHANNELS]);

/* 모델 입력으로 클래스 점수(NONE, UP, DOWN, LEFT, RIGHT)를 계산한다. 정적 버퍼를 쓰므로 재진입할 수 없다. */
void gt_predict(const float x[GT_WINDOW][GT_CHANNELS], float scores[GT_CLASSES]);

#ifdef __cplusplus
}
#endif

#endif
