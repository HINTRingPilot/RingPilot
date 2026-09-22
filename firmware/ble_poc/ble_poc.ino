#include <Adafruit_TinyUSB.h>
#include <bluefruit.h>

// Smart Ring prototype: one peripheral connection, HID + custom GATT.
BLEHidAdafruit hid;
BLEService telemetry("b27a1000-8c5e-4b62-9a21-33dd714e9001");
BLECharacteristic counter("b27a1001-8c5e-4b62-9a21-33dd714e9001");
uint32_t sequence = 0;
uint32_t lastTick = 0;
bool releasePending = false;
uint32_t pressedAt = 0;

void help() {
  Serial.println("SmartRing-PoC: W/A/S/D move, C click, U/J/L/R swipe, ? status (115200 baud)");
  Serial.print("Connected: "); Serial.println(Bluefruit.connected());
  Serial.print("Notify subscribed: "); Serial.println(counter.notifyEnabled());
}

void sendGesture(const char* command) {
  counter.write(command);
  bool sent = counter.notify(command);
  Serial.print(command);
  Serial.println(sent ? " notify queued" : " notify failed");
}

void setup() {
  Serial.begin(115200); // Do not wait for Serial: reconnect also works without monitor.
  Bluefruit.begin(1, 0);
  Bluefruit.setName("SmartRing-PoC");
  Bluefruit.setTxPower(4);
  Bluefruit.Periph.setConnInterval(9, 16);
  hid.begin();
  telemetry.begin();
  counter.setProperties(CHR_PROPS_READ | CHR_PROPS_NOTIFY);
  counter.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  counter.setMaxLen(20);
  counter.begin();
  counter.write("seq=0");

  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addAppearance(BLE_APPEARANCE_HID_MOUSE);
  Bluefruit.Advertising.addService(hid);
  Bluefruit.ScanResponse.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.setInterval(32, 244);
  Bluefruit.Advertising.setFastTimeout(30);
  Bluefruit.Advertising.start(0);
}

void loop() {
  const uint32_t now = millis();
  if (releasePending && now - pressedAt >= 40) {
    // Retry a failed release while connected, so a click cannot remain held.
    if (!Bluefruit.connected() || hid.mouseButtonRelease()) releasePending = false;
  }
  if (Serial.available()) {
    char command = Serial.read();
    if (command >= 'a' && command <= 'z') command -= 'a' - 'A';
    if (command == '?') help();
    else if (command == 'U' || command == 'J' || command == 'L' || command == 'R') {
      if (!Bluefruit.connected()) Serial.println("Not connected: pair in phone Bluetooth settings.");
      else if (!counter.notifyEnabled()) Serial.println("GATT notify not subscribed: connect the RingPilot app.");
      else {
        switch (command) {
          case 'U': sendGesture("SWIPE_UP"); break;
          case 'J': sendGesture("SWIPE_DOWN"); break;
          case 'L': sendGesture("SWIPE_LEFT"); break;
          case 'R': sendGesture("SWIPE_RIGHT"); break;
        }
      }
    }
    else if (command == 'W' || command == 'A' || command == 'S' || command == 'D' || command == 'C') {
      if (!Bluefruit.connected()) Serial.println("Not connected: pair in phone Bluetooth settings.");
      else if (releasePending) Serial.println("Click release pending; retry command.");
      else {
        bool sent = false;
        switch (command) {
          case 'W': sent = hid.mouseMove(0, -20); break;
          case 'A': sent = hid.mouseMove(-20, 0); break;
          case 'S': sent = hid.mouseMove(0, 20); break;
          case 'D': sent = hid.mouseMove(20, 0); break;
          case 'C':
            sent = hid.mouseButtonPress(MOUSE_BUTTON_LEFT);
            releasePending = true;
            pressedAt = now;
            break;
        }
        Serial.println(sent ? "HID queued (verify on phone)" : "HID send failed (check pairing)");
      }
    }
  }
  if (now - lastTick >= 1000) {
    lastTick = now;
    char payload[20];
    snprintf(payload, sizeof(payload), "seq=%lu", (unsigned long) ++sequence);
    counter.write(payload);
    if (Bluefruit.connected() && counter.notifyEnabled()) {
      bool sent = counter.notify(payload);
      if (Serial) {
        Serial.print(payload);
        Serial.println(sent ? " notify queued" : " notify failed");
      }
    }
  }
  delay(1);
}
