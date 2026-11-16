// RingPilot 반지 펌웨어(XIAO nRF52840 Sense). IMU를 100 Hz로 읽어 보드 안에서 제스처를 판정하고, 발행을 BLE 알림으로 보낸다.
//
// 흐름: imu_sampler(읽기 태스크, 10 ms) → 판정 대기열 → loop
//         └ gesture_loop: gesture_runtime(영점·입력 처리·TCN·발행 규칙·입력 지우기) → 발행을 ble_link(제스처 알림)·LED로
//       ble_link: 연결, 상태·제스처 알림
//       controls: 센터 스위치(클릭·일시정지·전원 끄기)와 LED, pointer: 방향 스위치·클릭 → 포인터 알림(커서는 앱이 그린다)
//       dev/imu_stream: 개발 빌드에서만 IMU 원시값 스트림(src/build_config.h의 RINGPILOT_IMU_STREAM)
// 각 모듈의 규칙과 패킷 형식은 src/의 헤더 주석에 있다. 판정 코어(gesture_runtime.c, gesture_tcn.c)는 PC에서 ml/v2_export_c.py로 Keras와 같은지 확인한다.
// 데이터 수집용(추론 없음)은 firmware/dev/imu_ble_stream이다. 스트림 형식이 같아 같은 앱이 붙는다.
//
// 시리얼(115200) 명령: ? = 상태, l = 판정·읽기 통계, r = 통계 초기화. 측정 조건·기록은 docs/experiments/ble-v2/latency-01/README.md.

#include <Adafruit_TinyUSB.h>  // 업로드 시 자동 리셋(1200bps)을 유지하려고 포함

#include "src/ble_link.h"
#include "src/controls.h"
#include "src/cycle_timer.h"
#include "src/gesture_loop.h"
#include "src/imu_sampler.h"

static const uint32_t kLoopWaitMs = 20;  // 샘플이 없어도 이 간격으로 깨어 스위치·LED·시리얼을 본다(일시정지 중에는 이것만)

static void printStatus() {
  Serial.println("RingPilot-IMU: ? 상태 | 센터 <0.5s 왼쪽 클릭(일시정지 중이면 재개), 0.5~2s 일시정지, 2s+ System OFF | 방향 = 커서");
  controls_print_status(Serial);
  ble_print_status(Serial);
}

static void printStats() {
  gesture_print_stats(Serial);
  const ReadStats& s = sampler_stats();
  Serial.print("Reads/repeated: "); Serial.print(s.total); Serial.print(" / "); Serial.println(s.repeated);
  Serial.print("Read gap max us, >12ms, <8ms: ");
  Serial.print(s.maxGapUs); Serial.print(", "); Serial.print(s.late); Serial.print(", "); Serial.println(s.early);
  Serial.print("Read avg/max us: "); Serial.print(s.reads ? s.sumReadUs / s.reads : 0); Serial.print(" / "); Serial.println(s.maxReadUs);
  Serial.print("Gyro queue dropped / read errors: "); Serial.print(s.gyroDropped); Serial.print(" / "); Serial.println(s.readErrors);
  ble_print_link(Serial);
}

static void pollSerial() {
  while (Serial.available()) {
    const int command = Serial.read();
    if (command == '?') printStatus();
    else if (command == 'l') printStats();
    else if (command == 'r') {
      gesture_reset_stats();
      sampler_reset_stats();
      ble_reset_stats();
    }
  }
}

void setup() {
  Serial.begin(115200);  // 시리얼을 기다리지 않는다. USB 없이 배터리만으로도 시작해야 한다
  controls_begin();
  if (!imu_begin()) controls_fail_forever();  // 센서가 없으면 BLE를 시작하지 않는다
  ble_begin();
  gesture_begin();
  cycle_timer_start();
  sampler_start();
}

void loop() {
  ble_apply_link();
  controls_poll(millis());
  pollSerial();
  if (!device_paused()) gesture_poll();  // 추론은 구독과 상관없이 돈다
  ble_poll();
  sampler_wait(kLoopWaitMs);  // 새 샘플이 오면 바로, 없으면 20 ms 뒤 깨어난다. 그동안 CPU는 저전력 대기
}
