// 빌드 설정.
//
// RINGPILOT_IMU_STREAM: IMU 원시값 스트림(BLE 특성 b27a2001, src/dev/imu_stream).
//   0(기본, 사용자 빌드) = 스트림 없음. 앱은 상태·제스처 알림만 받는다.
//   1(개발 빌드) = 원시값을 100 Hz로 보낸다. 앱 개발용 빌드의 연속 기록·수집·Hz 표시에 쓴다.
//   바꾸려면 아래 값을 고치거나, arduino-cli에 다음을 붙인다:
//   --build-property "compiler.cpp.extra_flags=-DRINGPILOT_IMU_STREAM=1"
//   학습 데이터만 모을 때는 추론 없는 firmware/dev/imu_ble_stream도 쓸 수 있다.
#pragma once

#ifndef RINGPILOT_IMU_STREAM
#define RINGPILOT_IMU_STREAM 0
#endif
