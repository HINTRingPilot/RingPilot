# RingPilot Android swipe PoC

최소 검증 범위:

1. 접근성 서비스의 `dispatchGesture()`로 위/아래 스와이프 실행
2. 본딩된 `SmartRing-PoC`에 GATT 연결
3. `SWIPE_UP` / `SWIPE_DOWN` 알림을 동일한 스와이프 함수로 전달

## 휴대폰 시험 순서

1. `app/build/outputs/apk/debug/app-debug.apk`를 설치하고 실행한다.
2. `접근성 설정 열기`를 눌러 `RingPilot 스와이프`를 허용한다.
3. 3초 지연 상하좌우 시험 버튼을 누르고 대상 앱으로 전환해 실제 화면 스와이프를 확인한다.
4. Bluetooth 권한을 허용하고 `SmartRing-PoC BLE 연결`을 누른다.
5. 연결 완료 메시지를 확인하고 대상 앱을 연다. RingPilot 앱은 강제 종료하지 않는다.
6. PC의 보드 시리얼 포트(115200 baud)에 `U` 또는 `J`를 보낸다.

명령:

- `U`: `SWIPE_UP`
- `J`: `SWIPE_DOWN`
- `L`: `SWIPE_LEFT`
- `R`: `SWIPE_RIGHT`

초당 `seq=숫자` 알림은 연결 상태 확인용이며 앱에서 무시한다.

현재 PoC는 앱 화면이 살아 있는 동안만 GATT 연결을 유지한다. 백그라운드 서비스와 자동 재연결은 후속 범위다.

## 빌드

요구 환경은 Android Studio, Android SDK Platform 35, Build-Tools 36.0.0이다. 저장소에 Gradle Wrapper가 포함되어 있다.

```powershell
cd android
.\gradlew.bat :app:assembleDebug
```

현재 상태:

- Android 12 이상 대상 최소 Java 앱
- 별도 외부 라이브러리 없음
- 디버그 APK 빌드 성공
- Galaxy S10 / Android 12에서 앱 자체 스와이프 검증 완료
- BLE 상하좌우 스와이프 실동작 검증 완료
- 앱이 종료돼도 연결을 유지하는 Foreground Service와 자동 재연결은 미구현

보드를 재부팅하거나 새 펌웨어를 업로드하면 기존 GATT 연결이 끊긴다. 현재 버전에서는 앱을 다시 열어 `SmartRing-PoC BLE 연결`을 눌러야 한다.
