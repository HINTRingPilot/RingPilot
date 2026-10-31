#include "gesture_tcn.h"

#include <math.h>
#include <string.h>

/* 블록 출력 저장(블록마다 계산하는 칸 수 × 필터). 블록 입력은 앞 블록 출력이다. */
static float g_outputs[GT_TOTAL_POSITIONS * GT_FILTERS];

void gt_prepare(const float gyro[GT_WINDOW][3], const float bias[3], float x[GT_WINDOW][GT_CHANNELS]) {
  float sum[3] = {0.0f, 0.0f, 0.0f};
  for (int t = 0; t < GT_WINDOW; t++) {
    for (int a = 0; a < 3; a++) {
      /* 회전각은 창 첫 값이 0이 되도록 둘째 샘플부터 누적한다 */
      if (t > 0) sum[a] += (gyro[t][a] - bias[a]) * GT_SAMPLE_S;
      x[t][a] = (gyro[t][a] - gt_gyro_mean[a]) / gt_gyro_std[a];
      x[t][a + 3] = (sum[a] / GT_ANGLE_SCALE_DEG - gt_angle_mean[a]) / gt_angle_std[a];
    }
  }
}

void gt_predict(const float x[GT_WINDOW][GT_CHANNELS], float scores[GT_CLASSES]) {
  const float *prev = &x[0][0];
  int inputs = GT_CHANNELS;
  float *cur = g_outputs;
  const int16_t *src = gt_sources;
  const float *conv = gt_conv_kernels;
  const float *conv_bias = gt_conv_biases;

  for (int b = 0; b < GT_BLOCKS; b++) {
    for (int p = 0; p < gt_block_positions[b]; p++, src += 3) {
      float *out = cur + p * GT_FILTERS;
      memset(out, 0, GT_FILTERS * sizeof(float));
      const float *kernel = conv;
      for (int k = 0; k < 3; k++) {
        if (src[k] < 0) {  /* 창 앞으로 넘어간 칸은 0(인과 패딩)이다 */
          kernel += inputs * GT_FILTERS;
          continue;
        }
        const float *row = prev + src[k] * inputs;
        for (int c = 0; c < inputs; c++) {
          const float v = row[c];
          for (int f = 0; f < GT_FILTERS; f++) out[f] += v * kernel[f];
          kernel += GT_FILTERS;
        }
      }
      for (int f = 0; f < GT_FILTERS; f++) {
        const float h = out[f] + conv_bias[f];
        out[f] = h > 0.0f ? h : 0.0f;
      }
      /* 잔차: 같은 시점(src[2]) 입력을 더한다. 채널이 다른 첫 블록은 1×1 합성곱으로 맞춘다 */
      const float *same = prev + src[2] * inputs;
      if (b == 0) {
        const float *match = gt_match_kernel;
        for (int c = 0; c < inputs; c++) {
          const float v = same[c];
          for (int f = 0; f < GT_FILTERS; f++) out[f] += v * match[f];
          match += GT_FILTERS;
        }
        for (int f = 0; f < GT_FILTERS; f++) out[f] += gt_match_bias[f];
      } else {
        for (int f = 0; f < GT_FILTERS; f++) out[f] += same[f];
      }
    }
    conv += 3 * inputs * GT_FILTERS;
    conv_bias += GT_FILTERS;
    prev = cur;
    cur += gt_block_positions[b] * GT_FILTERS;
    inputs = GT_FILTERS;
  }

  /* 마지막 블록은 마지막 시점 한 칸만 계산한다 */
  float logits[GT_CLASSES];
  float top = -INFINITY;
  for (int n = 0; n < GT_CLASSES; n++) {
    float v = gt_dense_bias[n];
    for (int f = 0; f < GT_FILTERS; f++) v += prev[f] * gt_dense_kernel[f * GT_CLASSES + n];
    logits[n] = v;
    if (v > top) top = v;
  }
  float total = 0.0f;
  for (int n = 0; n < GT_CLASSES; n++) {
    scores[n] = expf(logits[n] - top);
    total += scores[n];
  }
  for (int n = 0; n < GT_CLASSES; n++) scores[n] /= total;
}
