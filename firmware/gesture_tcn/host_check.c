/* PC 검증용(보드에 올리지 않는다). ml/v2_export_c.py가 빌드해 실행하고 Keras 출력과 비교한다.
 * 사용: host_check prep 입력 출력    입력 = 창마다 자이로[160][3] + 영점[3], 출력 = 창마다 모델 입력 + 점수
 *       host_check predict 입력 출력 입력 = 창마다 모델 입력, 출력 = 창마다 점수 */
#include <stdio.h>
#include <string.h>

#include "gesture_tcn.h"

int main(int argc, char **argv) {
  if (argc != 4) return 2;
  FILE *in = fopen(argv[2], "rb");
  FILE *out = fopen(argv[3], "wb");
  if (!in || !out) return 3;
  static float gyro[GT_WINDOW][3];
  static float x[GT_WINDOW][GT_CHANNELS];
  float bias[3], scores[GT_CLASSES];
  if (strcmp(argv[1], "prep") == 0) {
    while (fread(gyro, sizeof gyro, 1, in) == 1) {
      if (fread(bias, sizeof bias, 1, in) != 1) return 4;
      gt_prepare((const float (*)[3])gyro, bias, x);
      gt_predict((const float (*)[GT_CHANNELS])x, scores);
      fwrite(x, sizeof x, 1, out);
      fwrite(scores, sizeof scores, 1, out);
    }
  } else {
    while (fread(x, sizeof x, 1, in) == 1) {
      gt_predict((const float (*)[GT_CHANNELS])x, scores);
      fwrite(scores, sizeof scores, 1, out);
    }
  }
  fclose(in);
  fclose(out);
  return 0;
}
