// BLE 주변기기(이름 RingPilot-IMU). 서비스 b27a2000 아래 특성을 둔다.
//  - b27a2001 IMU 스트림(notify): 개발 빌드(RINGPILOT_IMU_STREAM=1)에만 있다. 형식은 dev/imu_stream.h.
//  - b27a2002 상태(read, notify): [상태 uint8(0 스트리밍, 1 일시정지)][이벤트 uint8][부팅 후 ms uint32 LE][트리거 후 ms uint32 LE].
//    트리거는 부팅이나 재개 클릭을 뗀 시각이다. "첫 데이터" 이벤트는 스트림이 있을 때만 보낸다(앱의 재개·재연결 지연 측정용).
//  - b27a2003 제스처(notify): [순번 uint8][클래스 uint8(1 UP, 2 DOWN, 3 LEFT, 4 RIGHT)][점수×1000 uint16 LE][슬롯 uint32 LE].
//    송신 버퍼가 차 실패하면 대기열(4개)에 두고 다음 loop에서 먼저 다시 보낸다.
//  - b27a2004 포인터(notify): 5방향 스위치 상태와 클릭. 형식은 pointer.h.
// 연결은 스트림이 없어도 유지된다. 연결 이벤트(약 11~50 ms마다)에 빈 패킷을 주고받으며, 감시 시간(2초) 동안 응답이 없으면 끊긴 것으로 본다.
#pragma once

#include <Print.h>
#include <stdint.h>

enum StatusEvent : uint8_t { EVENT_SUBSCRIBED = 0, EVENT_PAUSED = 1, EVENT_RESUMED = 2, EVENT_FIRST_DATA = 3 };

void ble_begin();  // 서비스를 만들고 광고를 시작한다. 트리거 시각은 부팅(0)이다
bool ble_connected();
bool ble_ready();             // 앱이 제스처 알림을 구독했는지(상태 LED 초록)
uint16_t ble_conn_handle();

void ble_poll();   // loop마다: 밀린 제스처·상태 알림을 보내고, 개발 빌드면 IMU 스트림을 보낸다
void ble_send_status(StatusEvent event);
void ble_send_gesture(int8_t cls, float score, uint32_t slot);  // 바로 보내고, 실패하면 다음 poll에서 다시 보낸다

void ble_on_pause();                    // 연결 간격을 늘리고 일시정지를 알린다
void ble_on_resume(uint32_t releaseMs); // 짧은 연결 간격으로 돌리고 재개를 알린다. 트리거는 클릭을 뗀 시각
void ble_shutdown();                    // 전원을 끄기 전에 광고를 멈추고 연결을 끊는다

void ble_print_status(Print& out);      // MTU·간격 등 연결 정보, 스트림 정보
void ble_print_link(Print& out);        // 제스처 재전송·버림 수, 연결·구독 여부, 연결 간격
