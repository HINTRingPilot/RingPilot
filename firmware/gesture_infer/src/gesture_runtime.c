#include "gesture_runtime.h"

#include <string.h>

#define GR_STRIDE 5
#define GR_STILL_SAMPLES 50
#define GR_STILL_VARIANCE 9.0f    /* 정지 판정: 축별 표준편차 3 dps 미만 */
#define GR_SCORE_THRESHOLD 0.8f
#define GR_MARGIN_THRESHOLD 0.2f
#define GR_CONSECUTIVE 2
#define GR_NONE_REARM 2
#define GR_ERASE_AFTER_DECISIONS 3  /* 발행 뒤 입력을 지울 때까지의 판정 수(150 ms) */
#define GR_QUIET_SAMPLES 15         /* 발행 없이 끝난 움직임: 이만큼(150 ms) 정지하면 지운다 */
#define GR_QUIET_BIG_DPS 300.0f
#define GR_QUIET_STILL_DPS 30.0f

static float g_ring[GT_WINDOW][3];
static float g_window[GT_WINDOW][3];
static float g_x[GT_WINDOW][GT_CHANNELS];
static float g_bias[3];
static uint32_t g_count;
static int g_locked, g_candidate, g_candidate_count, g_none_count;
static int g_erase_in;          /* 입력을 지울 때까지 남은 판정 수. 예약이 없으면 음수 */
static uint32_t g_erased_until; /* 이 샘플 번호 앞은 g_erase_bias로 본다. 온라인 영점은 원래 값을 쓴다 */
static float g_erase_bias[3];
static int g_moved;             /* 마지막 발행·지우기 뒤 큰 움직임이 있었다 */

void gr_reset(void) {
  g_count = 0;
  memset(g_bias, 0, sizeof g_bias);
  g_locked = 0;
  g_candidate = -1;
  g_candidate_count = 0;
  g_none_count = 0;
  g_erase_in = -1;
  g_erased_until = 0;
  g_moved = 0;
}

static float median_of_recent(int axis) {
  float v[GR_STILL_SAMPLES];
  for (int i = 0; i < GR_STILL_SAMPLES; i++) {
    const float value = g_ring[(g_count - 1 - i) % GT_WINDOW][axis];
    int j = i;
    while (j > 0 && v[j - 1] > value) {
      v[j] = v[j - 1];
      j--;
    }
    v[j] = value;
  }
  return (v[GR_STILL_SAMPLES / 2 - 1] + v[GR_STILL_SAMPLES / 2]) * 0.5f;
}

static int recent_is_still(void) {
  for (int a = 0; a < 3; a++) {
    float sum = 0.0f, square = 0.0f;
    for (int i = 0; i < GR_STILL_SAMPLES; i++) sum += g_ring[(g_count - 1 - i) % GT_WINDOW][a];
    const float mean = sum / GR_STILL_SAMPLES;
    for (int i = 0; i < GR_STILL_SAMPLES; i++) {
      const float d = g_ring[(g_count - 1 - i) % GT_WINDOW][a] - mean;
      square += d * d;
    }
    if (square / GR_STILL_SAMPLES >= GR_STILL_VARIANCE) return 0;
  }
  return 1;
}

static void update_bias(void) {
  /* 켤 때는 정지해 있다고 보고 처음 구간을 쓴다. 그 뒤로는 정지 구간에서만 갱신한다 */
  if (g_count < GR_STILL_SAMPLES) return;
  if (g_count == GR_STILL_SAMPLES || recent_is_still()) {
    for (int a = 0; a < 3; a++) g_bias[a] = median_of_recent(a);
  }
}

/* 창 끝 n샘플의 영점 뺀 |자이로| 최댓값(지운 값 포함, 파이썬 replay와 같다) */
static float recent_peak(int n) {
  float peak = 0.0f;
  for (int t = GT_WINDOW - n; t < GT_WINDOW; t++) {
    for (int a = 0; a < 3; a++) {
      const float v = g_window[t][a] - g_bias[a];
      if (v > peak) peak = v;
      if (-v > peak) peak = -v;
    }
  }
  return peak;
}

static int issue_rule(const float scores[GT_CLASSES]) {
  int top = 0;
  for (int n = 1; n < GT_CLASSES; n++) {
    if (scores[n] > scores[top]) top = n;
  }
  if (g_locked) {
    g_none_count = (top == 0 && scores[0] >= GR_SCORE_THRESHOLD) ? g_none_count + 1 : 0;
    if (g_none_count >= GR_NONE_REARM) {
      g_locked = 0;
      g_candidate = -1;
      g_candidate_count = 0;
      g_none_count = 0;
    }
    return -1;
  }
  float second = -1.0f;
  for (int n = 0; n < GT_CLASSES; n++) {
    if (n != top && scores[n] > second) second = scores[n];
  }
  if (top != 0 && scores[top] >= GR_SCORE_THRESHOLD && scores[top] - second >= GR_MARGIN_THRESHOLD) {
    g_candidate_count = top == g_candidate ? g_candidate_count + 1 : 1;
    g_candidate = top;
    if (g_candidate_count >= GR_CONSECUTIVE) {
      g_locked = 1;
      g_candidate = -1;
      g_candidate_count = 0;
      g_none_count = 0;
      g_moved = 0;
      g_erase_in = GR_ERASE_AFTER_DECISIONS;
      return top;
    }
  } else {
    g_candidate = -1;
    g_candidate_count = 0;
  }
  return -1;
}

int gr_push(const float gyro[3], GrDecision *out) {
  memcpy(g_ring[g_count % GT_WINDOW], gyro, sizeof g_ring[0]);
  g_count++;
  update_bias();
  if (g_count < GT_WINDOW || (g_count - GT_WINDOW) % GR_STRIDE != 0) return 0;

  for (int t = 0; t < GT_WINDOW; t++) {
    const uint32_t sample = g_count - GT_WINDOW + t;
    memcpy(g_window[t], sample < g_erased_until ? g_erase_bias : g_ring[sample % GT_WINDOW], sizeof g_window[0]);
  }
  gt_prepare((const float (*)[3])g_window, g_bias, g_x);
  gt_predict((const float (*)[GT_CHANNELS])g_x, out->scores);
  memcpy(out->bias, g_bias, sizeof g_bias);
  out->issued = (int8_t)issue_rule(out->scores);
  int erase = 0;
  if (!g_locked && g_erase_in < 0) {
    if (recent_peak(GR_STRIDE) > GR_QUIET_BIG_DPS) g_moved = 1;
    if (g_moved && recent_peak(GR_QUIET_SAMPLES) < GR_QUIET_STILL_DPS) {
      erase = 1;
      g_moved = 0;
    }
  }
  if (g_erase_in >= 0 && g_erase_in-- == 0) erase = 1;
  if (erase) {
    g_erased_until = g_count;
    memcpy(g_erase_bias, g_bias, sizeof g_bias);
  }
  return 1;
}
