// 판정·읽기 시간 측정용 사이클 카운터(DWT). 이 코어의 micros()는 약 1 ms 단위라 쓰지 않는다.
#pragma once

#include <Arduino.h>

static const uint32_t kCyclesPerUs = F_CPU / 1000000;

inline void cycle_timer_start() {
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  DWT->CYCCNT = 0;
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

inline uint32_t cycle_now() {
  return DWT->CYCCNT;
}

inline uint32_t cycles_to_us(uint32_t cycles) {
  return cycles / kCyclesPerUs;
}
