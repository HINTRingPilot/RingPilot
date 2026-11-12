#ifndef RINGPILOT_BLE_MAILBOX_H
#define RINGPILOT_BLE_MAILBOX_H

#include <Arduino.h>
#include <bluefruit.h>
#include <stdint.h>

namespace ringpilot {

// The only callback-owned state. No notification or queue operation under this lock.
class BleMailbox {
 public:
  enum Channel { Status, Gesture, Data };
  struct Snapshot {
    uint16_t handle;
    uint32_t linkEpoch, gestureEpoch;
    bool statusEnabled, gestureEnabled, statusSubscribed;
  };
  BleMailbox() : value_() { value_.handle = BLE_CONN_HANDLE_INVALID; }
  void onConnect(uint16_t handle) {
    taskENTER_CRITICAL();
    value_.handle = handle;
    ++value_.linkEpoch;
    ++value_.gestureEpoch;
    value_.statusEnabled = value_.gestureEnabled = value_.statusSubscribed = false;
    taskEXIT_CRITICAL();
  }
  void onDisconnect(uint16_t handle) {
    taskENTER_CRITICAL();
    if (value_.handle == handle) {
      value_.handle = BLE_CONN_HANDLE_INVALID;
      ++value_.linkEpoch;
      ++value_.gestureEpoch;
      value_.statusEnabled = value_.gestureEnabled = value_.statusSubscribed = false;
    }
    taskEXIT_CRITICAL();
  }
  void onStatusCccd(uint16_t handle, uint16_t value) {
    taskENTER_CRITICAL();
    if (value_.handle == handle) {
      value_.statusEnabled = (value & BLE_GATT_HVX_NOTIFICATION) != 0;
      value_.statusSubscribed = value_.statusEnabled;
    }
    taskEXIT_CRITICAL();
  }
  void onGestureCccd(uint16_t handle, uint16_t value) {
    taskENTER_CRITICAL();
    if (value_.handle == handle) {
      const bool enabled = (value & BLE_GATT_HVX_NOTIFICATION) != 0;
      if (!enabled || value_.gestureEnabled != enabled) ++value_.gestureEpoch;
      value_.gestureEnabled = enabled;
    }
    taskEXIT_CRITICAL();
  }
  Snapshot snapshot(bool consumeStatus = false) {
    taskENTER_CRITICAL();
    const Snapshot result = value_;
    if (consumeStatus) value_.statusSubscribed = false;
    taskEXIT_CRITICAL();
    return result;
  }
  bool current(const Snapshot& expected, bool gesture = false) {
    const Snapshot now = snapshot();
    return now.handle != BLE_CONN_HANDLE_INVALID && now.handle == expected.handle
        && now.linkEpoch == expected.linkEpoch
        && (!gesture || (now.gestureEnabled && now.gestureEpoch == expected.gestureEpoch));
  }
  template<typename Characteristic>
  bool notifyCurrent(const Snapshot& expected, Channel channel, Characteristic& characteristic,
                     const uint8_t* packet, uint8_t length, bool& inFlightBoundary) {
    inFlightBoundary = false;
    if (!current(expected, channel == Gesture)) return false;
    if (channel == Status && !snapshot().statusEnabled) return false;
    const bool accepted = characteristic.notify(expected.handle, packet, length);
    inFlightBoundary = !current(expected, channel == Gesture);
    return accepted;
  }
 private:
  Snapshot value_;
};

} // namespace ringpilot
#endif
