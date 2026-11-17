// 판정 대기열을 비우며 gesture_runtime에 100 Hz 자이로를 넣고, 발행을 BLE·LED로 내보낸다.
// 판정 입력은 끊기지 않은 100 Hz여야 하므로 빈 슬롯은 직전 값으로 채운다(20슬롯 넘게 비면 판정 상태를 초기화).
// 판정 시간과 "판정에 쓴 마지막 샘플을 읽은 순간부터 판정 완료까지"를 사이클 카운터로 잰다.
#pragma once

#include <Print.h>

void gesture_begin();
void gesture_request_reset();  // 다음 poll에서 판정 상태를 초기화한다(일시정지 뒤 이전 이력을 쓰지 않게)
void gesture_poll();           // loop마다. 추론은 BLE 구독과 상관없이 돈다

void gesture_print_stats(Print& out);  // 판정 수·시간, 채운 슬롯, 발행 수
void gesture_reset_stats();
