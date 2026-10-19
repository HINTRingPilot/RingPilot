package com.hintringpilot.ringpilot;

import android.Manifest;
import android.app.Activity;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.nio.charset.StandardCharsets;
import java.util.Set;
import java.util.UUID;

public final class MainActivity extends Activity {
    private static final int REQUEST_BLUETOOTH_CONNECT = 100;
    private static final String DEVICE_NAME = "SmartRing-PoC";
    private static final UUID SERVICE_UUID = UUID.fromString("b27a1000-8c5e-4b62-9a21-33dd714e9001");
    private static final UUID COMMAND_UUID = UUID.fromString("b27a1001-8c5e-4b62-9a21-33dd714e9001");
    private static final UUID CCCD_UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");

    private TextView status;
    private BluetoothGatt bluetoothGatt;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(createContentView());
    }

    private LinearLayout createContentView() {
        int padding = Math.round(20 * getResources().getDisplayMetrics().density);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(padding, padding, padding, padding);
        layout.setLayoutParams(new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        status = new TextView(this);
        status.setText("접근성 서비스와 BLE 연결을 준비하세요.");
        status.setTextSize(17);
        layout.addView(status, matchWidth());

        layout.addView(button("1. 접근성 설정 열기", view ->
                startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))), matchWidth());
        layout.addView(button("2. 3초 후 위로 스와이프 시험", view -> scheduleSwipe("UP")), matchWidth());
        layout.addView(button("3. 3초 후 아래로 스와이프 시험", view -> scheduleSwipe("DOWN")), matchWidth());
        layout.addView(button("4. 3초 후 왼쪽으로 스와이프 시험", view -> scheduleSwipe("LEFT")), matchWidth());
        layout.addView(button("5. 3초 후 오른쪽으로 스와이프 시험", view -> scheduleSwipe("RIGHT")), matchWidth());
        layout.addView(button("6. SmartRing-PoC BLE 연결", view -> connectRing()), matchWidth());
        layout.addView(button("7. RingPilot-IMU 수신·재연결 측정", view ->
                startActivity(new Intent(this, ImuMonitorActivity.class))), matchWidth());

        TextView help = new TextView(this);
        help.setText("BLE 연결 후 PC 시리얼에서 U/J/L/R=위/아래/왼쪽/오른쪽 스와이프입니다.\n" +
                "시험 중에는 앱을 열어 둡니다. seq 알림은 무시합니다.");
        help.setTextSize(15);
        help.setPadding(0, padding, 0, 0);
        layout.addView(help, matchWidth());
        return layout;
    }

    private LinearLayout.LayoutParams matchWidth() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        params.setMargins(0, 12, 0, 0);
        return params;
    }

    private Button button(String text, android.view.View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(text);
        button.setOnClickListener(listener);
        return button;
    }

    private void dispatchSwipe(String direction) {
        SwipeAccessibilityService service = SwipeAccessibilityService.getCurrent();
        if (service == null) {
            showStatus("접근성 설정에서 'RingPilot 스와이프'를 먼저 켜세요.");
            return;
        }
        boolean queued = service.swipe(direction);
        showStatus(directionLabel(direction) + " 스와이프 " + (queued ? "요청 성공" : "요청 실패"));
    }

    private void scheduleSwipe(String direction) {
        showStatus("3초 뒤 " + directionLabel(direction) + " 스와이프를 실행합니다. 대상 앱으로 전환하세요.");
        new Handler(Looper.getMainLooper()).postDelayed(() -> dispatchSwipe(direction), 3000);
    }

    private String directionLabel(String direction) {
        switch (direction) {
            case "UP": return "위";
            case "DOWN": return "아래";
            case "LEFT": return "왼쪽";
            case "RIGHT": return "오른쪽";
            default: return direction;
        }
    }

    private void connectRing() {
        if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.BLUETOOTH_CONNECT}, REQUEST_BLUETOOTH_CONNECT);
            return;
        }

        BluetoothManager manager = getSystemService(BluetoothManager.class);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) {
            showStatus("Bluetooth를 켜세요.");
            return;
        }

        Set<BluetoothDevice> bondedDevices = adapter.getBondedDevices();
        BluetoothDevice ring = null;
        for (BluetoothDevice device : bondedDevices) {
            if (DEVICE_NAME.equals(device.getName())) {
                ring = device;
                break;
            }
        }
        if (ring == null) {
            showStatus("Bluetooth 설정에서 SmartRing-PoC를 먼저 페어링하세요.");
            return;
        }

        if (bluetoothGatt != null) {
            bluetoothGatt.close();
        }
        showStatus("SmartRing-PoC 연결 중...");
        bluetoothGatt = ring.connectGatt(this, false, gattCallback, BluetoothDevice.TRANSPORT_LE);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_BLUETOOTH_CONNECT && grantResults.length > 0
                && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            connectRing();
        } else if (requestCode == REQUEST_BLUETOOTH_CONNECT) {
            showStatus("주변 기기 권한이 필요합니다.");
        }
    }

    private final BluetoothGattCallback gattCallback = new BluetoothGattCallback() {
        @Override
        public void onConnectionStateChange(BluetoothGatt gatt, int statusCode, int newState) {
            if (statusCode == BluetoothGatt.GATT_SUCCESS && newState == BluetoothProfile.STATE_CONNECTED) {
                showStatus("BLE 연결됨. 서비스 검색 중...");
                gatt.discoverServices();
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                showStatus("BLE 연결 해제됨 (status=" + statusCode + ")");
            }
        }

        @Override
        public void onServicesDiscovered(BluetoothGatt gatt, int statusCode) {
            if (statusCode != BluetoothGatt.GATT_SUCCESS) {
                showStatus("서비스 검색 실패 (status=" + statusCode + ")");
                return;
            }
            BluetoothGattService service = gatt.getService(SERVICE_UUID);
            BluetoothGattCharacteristic characteristic = service == null ? null : service.getCharacteristic(COMMAND_UUID);
            if (characteristic == null) {
                showStatus("RingPilot 명령 특성을 찾지 못했습니다.");
                return;
            }
            if (!gatt.setCharacteristicNotification(characteristic, true)) {
                showStatus("알림 설정 실패");
                return;
            }
            BluetoothGattDescriptor cccd = characteristic.getDescriptor(CCCD_UUID);
            if (cccd == null) {
                showStatus("알림 설정자(CCCD)를 찾지 못했습니다.");
                return;
            }
            cccd.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
            if (!gatt.writeDescriptor(cccd)) {
                showStatus("알림 설정 쓰기 실패");
            }
        }

        @Override
        public void onDescriptorWrite(BluetoothGatt gatt, BluetoothGattDescriptor descriptor, int statusCode) {
            if (CCCD_UUID.equals(descriptor.getUuid()) && statusCode == BluetoothGatt.GATT_SUCCESS) {
                showStatus("BLE 연결 및 명령 알림 설정 완료");
            } else if (CCCD_UUID.equals(descriptor.getUuid())) {
                showStatus("알림 설정 실패 (status=" + statusCode + ")");
            }
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic) {
            handleNotification(characteristic.getValue());
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, byte[] value) {
            handleNotification(value);
        }
    };

    private void handleNotification(byte[] value) {
        String command = new String(value, StandardCharsets.UTF_8).trim();
        if ("SWIPE_UP".equals(command)) {
            runOnUiThread(() -> dispatchSwipe("UP"));
        } else if ("SWIPE_DOWN".equals(command)) {
            runOnUiThread(() -> dispatchSwipe("DOWN"));
        } else if ("SWIPE_LEFT".equals(command)) {
            runOnUiThread(() -> dispatchSwipe("LEFT"));
        } else if ("SWIPE_RIGHT".equals(command)) {
            runOnUiThread(() -> dispatchSwipe("RIGHT"));
        }
    }

    private void showStatus(String message) {
        runOnUiThread(() -> {
            status.setText(message);
            Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
        });
    }

    @Override
    protected void onDestroy() {
        if (bluetoothGatt != null) {
            bluetoothGatt.close();
            bluetoothGatt = null;
        }
        super.onDestroy();
    }
}
