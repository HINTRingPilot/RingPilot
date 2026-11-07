// IMU 읽기. 우선순위 높은 FreeRTOS 태스크가 10 ms 슬롯마다 6축을 읽어 판정 대기열(GyroItem, deg/s)에 넣고,
// gesture_loop가 loop에서 꺼낸다. 대기열은 태스크만 head를, loop만 tail을 바꿔 잠금이 없다. 가득 차면 새 값을 버리고 센다.
// 개발 빌드(RINGPILOT_IMU_STREAM=1)는 같은 샘플의 6축 원시값을 imu_stream에도 넘긴다.
// I2C는 뮤텍스로 지켜 일시정지·재개 중 센서 설정과 읽기가 겹치지 않게 한다.
// 센서 설정: 104 Hz, ±4 g, ±2000 dps(빠른 동작에서 ±1000 dps 포화를 피하려고 넓혔다). 판정은 자이로만 쓴다.
#pragma once

#include <stdint.h>

struct GyroItem {
  uint32_t slot;        // 부팅 후 10 ms 슬롯 번호
  uint32_t readCycles;  // 읽기를 마친 사이클 시각(판정 지연 측정용)
  float gyro[3];        // deg/s
};

struct ReadStats {
  uint32_t total;        // 직전 읽기가 있는 읽기 수
  uint32_t repeated;     // 6축이 직전 읽기와 모두 같은 횟수(센서가 새 값을 내기 전에 읽음)
  uint32_t maxGapUs;     // 읽기 사이 최대 간격
  uint32_t late;         // 직전 읽기에서 12 ms 넘게 지난 읽기(주기 10 ms)
  uint32_t early;        // 직전 읽기에서 8 ms 안에 온 읽기
  uint32_t maxReadUs;    // I2C 읽기 한 번(6축)에 걸린 최대 시간
  uint32_t gyroDropped;  // 판정 대기열이 가득 차 버린 수
};

bool imu_begin();       // 센서를 켜고 설정한다. 센서가 없으면 false
void sampler_start();   // 읽기 태스크를 시작한다
void sampler_pause();   // 읽기를 멈추고 센서를 끈 뒤 대기열을 비운다
void sampler_resume();  // 센서를 다시 켜고 읽기를 재개한다
void sampler_halt();    // 전원을 끄기 전에 읽기 태스크를 영구히 멈춘다
bool device_paused();  // 일시정지 중인지(센서·판정이 멈춘 상태). 스위치로 바뀐다

bool sampler_pop_gyro(GyroItem* out);  // loop에서만 부른다

const ReadStats& sampler_stats();
void sampler_reset_stats();
