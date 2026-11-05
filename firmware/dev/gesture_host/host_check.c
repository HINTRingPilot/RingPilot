/* PC 검증·측정용(보드에 올리지 않는다). ml/v2_export_c.py와 ml/v2_latency.py가 빌드해 실행한다.
 * 사용: host_check prep 입력 출력    입력 = 창마다 자이로[160][3] + 영점[3], 출력 = 창마다 모델 입력 + 점수
 *       host_check predict 입력 출력 입력 = 창마다 모델 입력, 출력 = 창마다 점수
 *       host_check stream 입력 출력  입력 = 샘플마다 자이로[3], 출력 = 판정마다 샘플 번호, 점수, 발행, 영점
 *       host_check time 입력 출력 N  입력은 prep과 같다. N번 돌며 창마다 입력 처리·추론 시간(ns, uint32)을 쓴다 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gesture_runtime.h"

#ifdef _WIN32
#include <windows.h>
static uint64_t now_ns(void) {
  LARGE_INTEGER counter, frequency;
  QueryPerformanceCounter(&counter);
  QueryPerformanceFrequency(&frequency);
  return (uint64_t)((double)counter.QuadPart * 1e9 / (double)frequency.QuadPart);
}
#else
#include <time.h>
static uint64_t now_ns(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec;
}
#endif

static float g_gyro[GT_WINDOW][3];
static float g_x[GT_WINDOW][GT_CHANNELS];

static int run_stream(FILE *in, FILE *out) {
  float sample[3];
  GrDecision d;
  int32_t index = 0;
  gr_reset();
  while (fread(sample, sizeof sample, 1, in) == 1) {
    if (gr_push(sample, &d)) {
      const int32_t issued = d.issued;
      fwrite(&index, sizeof index, 1, out);
      fwrite(d.scores, sizeof d.scores, 1, out);
      fwrite(&issued, sizeof issued, 1, out);
      fwrite(d.bias, sizeof d.bias, 1, out);
    }
    index++;
  }
  return 0;
}

static int run_time(FILE *in, FILE *out, int passes) {
  static const size_t kRecord = sizeof g_gyro + 3 * sizeof(float);
  fseek(in, 0, SEEK_END);
  const size_t windows = (size_t)ftell(in) / kRecord;
  fseek(in, 0, SEEK_SET);
  unsigned char *data = (unsigned char *)malloc(windows * kRecord);
  if (!data || fread(data, kRecord, windows, in) != windows) return 4;
  volatile float sink = 0.0f;
  float bias[3], scores[GT_CLASSES];
  for (int pass = 0; pass < passes; pass++) {
    for (size_t w = 0; w < windows; w++) {
      memcpy(g_gyro, data + w * kRecord, sizeof g_gyro);
      memcpy(bias, data + w * kRecord + sizeof g_gyro, sizeof bias);
      const uint64_t t0 = now_ns();
      gt_prepare((const float (*)[3])g_gyro, bias, g_x);
      const uint64_t t1 = now_ns();
      gt_predict((const float (*)[GT_CHANNELS])g_x, scores);
      const uint64_t t2 = now_ns();
      sink += scores[0];
      const uint32_t times[2] = {(uint32_t)(t1 - t0), (uint32_t)(t2 - t1)};
      fwrite(times, sizeof times, 1, out);
    }
  }
  free(data);
  return sink < 0.0f ? 5 : 0;
}

int main(int argc, char **argv) {
  if (argc < 4) return 2;
  FILE *in = fopen(argv[2], "rb");
  FILE *out = fopen(argv[3], "wb");
  if (!in || !out) return 3;
  float bias[3], scores[GT_CLASSES];
  int code = 0;
  if (strcmp(argv[1], "prep") == 0) {
    while (fread(g_gyro, sizeof g_gyro, 1, in) == 1) {
      if (fread(bias, sizeof bias, 1, in) != 1) return 4;
      gt_prepare((const float (*)[3])g_gyro, bias, g_x);
      gt_predict((const float (*)[GT_CHANNELS])g_x, scores);
      fwrite(g_x, sizeof g_x, 1, out);
      fwrite(scores, sizeof scores, 1, out);
    }
  } else if (strcmp(argv[1], "predict") == 0) {
    while (fread(g_x, sizeof g_x, 1, in) == 1) {
      gt_predict((const float (*)[GT_CHANNELS])g_x, scores);
      fwrite(scores, sizeof scores, 1, out);
    }
  } else if (strcmp(argv[1], "stream") == 0) {
    code = run_stream(in, out);
  } else if (strcmp(argv[1], "time") == 0 && argc == 5) {
    code = run_time(in, out, atoi(argv[4]));
  } else {
    code = 2;
  }
  fclose(in);
  fclose(out);
  return code;
}
