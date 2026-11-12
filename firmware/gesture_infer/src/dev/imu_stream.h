// IMU 원시값 스트림(개발용, RINGPILOT_IMU_STREAM=1일 때만 빌드된다. ../build_config.h).
// 읽기 태스크가 샘플마다 전송 대기열에 넣고, loop가 연속 슬롯을 묶어 BLE 특성 b27a2001로 보낸다.
// 패킷: [첫 샘플 슬롯 uint32 LE][샘플 수 uint8] + 샘플마다 accX,accY,accZ,gyrX,gyrY,gyrZ 원시값 int16 LE.
// 묶음 대기는 최대 약 100 ms(10샘플). 보내기에 실패하면 대기열에 남겨 다음 loop에서 다시 보내고,
// 대기열(2.56초)이 넘치면 새 샘플을 버리고 센다(앱에서는 슬롯 공백 = 누락 샘플로 보인다).
// 원시값 환산: 가속도 1 LSB = 0.122 mg, 자이로 1 LSB = 0.070 dps. 범위를 바꾸면 앱의 환산 계수도 바꿔야 한다.
#pragma once

#include "../build_config.h"

#if RINGPILOT_IMU_STREAM

#include <Print.h>
#include <stdint.h>

void imu_stream_begin();                              // ble_begin이 서비스 안에서 부른다(특성 순서 유지)
void imu_stream_push(uint32_t slot, const int16_t v[6]);  // 읽기 태스크에서 부른다
void imu_stream_poll();                               // loop마다. 구독 중이면 보내고, 아니면 쌓인 샘플을 버린다
void imu_stream_discard();                            // 쌓인 샘플을 버린다(loop에서)
void imu_stream_mark_trigger();                       // 다음 첫 패킷을 보낼 때 "첫 데이터" 상태 알림을 보낸다
bool imu_stream_subscribed();
void imu_stream_print(Print& out);

#endif
