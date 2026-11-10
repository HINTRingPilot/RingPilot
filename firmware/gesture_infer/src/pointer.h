// 5방향 스위치 포인터(BLE HID 마우스). 폰에 마우스 커서가 생긴다.
//  - 방향 스위치를 누르는 동안 일정 속도로 커서를 옮긴다(20 ms마다 10 px, 두 방향을 함께 누르면 대각선).
//  - 센터 짧게 누르기 = 왼쪽 클릭(controls가 부른다). 일시정지 중에도 포인터는 동작한다(일시정지는 제스처 인식만 멈춘다).
// HID는 암호화 연결이 필요해 폰과 본딩해야 한다. HID를 더하기 전에 페어링한 폰은 반지를 지우고 다시 페어링해야 커서가 생길 수 있다.
// 방향 핀 매핑(D0·D2·D3·D6)은 아직 보드에서 확인하지 않았다(docs/HardwareBuild.md는 센터=D1만 확인).
// 시리얼이 연결돼 있으면 방향 스위치를 누를 때 핀과 방향을 찍으니, 눌러 보고 pointer.cpp의 kDirections를 고친다.
#pragma once

#include <stdint.h>

class BLEService;

void pointer_begin();            // 핀 설정과 HID 서비스 시작. ble_begin이 광고 전에 부른다
BLEService& pointer_service();   // 광고에 넣을 HID 서비스
void pointer_poll(uint32_t nowMs);  // loop마다: 방향 스위치로 이동, 클릭 떼기
void pointer_click();            // 왼쪽 클릭(누름. 40 ms 뒤 poll에서 뗀다)
