// 센터 스위치(D1)와 LED, 일시정지·재개·전원 끄기.
// 스위치: 0.5초 미만 = 클릭(일시정지 중이면 재개), 0.5~2초 = 일시정지, 2초 이상 = System OFF(누르는 중 2초가 되면 바로).
//   누르는 동안 0.5초가 지나면 파란 LED로 "지금 떼면 일시정지"를 알린다. System OFF에서는 센터를 누르면 재부팅한다.
//   일시정지는 BLE 연결을 유지한 채 IMU를 끄고 연결 간격을 늘린다.
// LED(이 보드는 LOW에서 켜짐):
//   발행 0.7초: 위 빨강, 아래 파랑, 왼쪽 흰색, 오른쪽 노랑(상태 깜빡임과 헷갈리지 않게 초록은 쓰지 않는다).
//   상태 2초마다 짧게: 연결 대기 파랑, 앱이 제스처를 받는 중 초록, 일시정지 청록. 센서가 없으면 빨강이 계속 깜빡인다.
#pragma once

#include <Print.h>
#include <stdint.h>

void controls_begin();         // 핀 설정. 깨우는 데 쓴 누름이 남아 있으면 뗄 때까지 기다린다
void controls_poll(uint32_t nowMs);
void controls_fail_forever();  // 센서가 없을 때. 빨간 LED를 계속 깜빡이고 돌아오지 않는다

void led_show_gesture(int8_t cls);
void controls_print_status(Print& out);  // 상태와 클릭 수
