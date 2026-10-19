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
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.UUID;

/**
 * RingPilot-IMU(firmware/imu_ble_stream)의 IMU 알림을 받아 재연결·재개 시간과 샘플 누락을 기록한다.
 * 끊기면 자동으로 다시 연결하며, 측정 결과는 화면과 앱 전용 폴더의 CSV 파일에 남긴다.
 */
public final class ImuMonitorActivity extends Activity {
    private static final int REQUEST_BLUETOOTH_CONNECT = 101;
    private static final String DEVICE_NAME = "RingPilot-IMU";
    private static final UUID SERVICE_UUID = UUID.fromString("b27a2000-8c5e-4b62-9a21-33dd714e9001");
    private static final UUID DATA_UUID = UUID.fromString("b27a2001-8c5e-4b62-9a21-33dd714e9001");
    private static final UUID STATUS_UUID = UUID.fromString("b27a2002-8c5e-4b62-9a21-33dd714e9001");
    private static final UUID CCCD_UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
    private static final long RETRY_DELAY_MS = 300;

    // 펌웨어 상태 패킷의 이벤트 번호
    private static final int EVENT_SUBSCRIBED = 0;
    private static final int EVENT_PAUSED = 1;
    private static final int EVENT_RESUMED = 2;
    private static final int EVENT_FIRST_DATA = 3;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private TextView statusView;
    private TextView statsView;
    private TextView logView;
    private BluetoothDevice ring;
    private BluetoothGatt gatt;
    private boolean monitoring = false;
    private File logFile;

    // 측정 상태. 시각은 모두 휴대폰 SystemClock.elapsedRealtime() 기준 ms.
    private long disconnectedAt = -1;
    private long connectedAt = -1;
    private long subscribedAt = -1;
    private long resumedStatusAt = -1;
    private boolean resumePending = false;
    private boolean firstDataPending = false;

    // 데이터 통계
    private long packets = 0;
    private long samples = 0;
    private long missingSamples = 0;
    private long expectedSlot = -1;
    private long rateWindowStart = -1;
    private long rateWindowSamples = 0;
    private double recentRate = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);  // 측정 중 화면 꺼짐 방지
        setContentView(createContentView());
        File dir = getExternalFilesDir(null);
        logFile = new File(dir, "imu_reconnect_log.csv");
        appendLogFile("wall_time,phone_ms,event,detail");
        showStatus("RingPilot-IMU를 Bluetooth 설정에서 먼저 페어링한 뒤 측정을 시작하세요.");
        updateStats();
    }

    private LinearLayout createContentView() {
        int padding = Math.round(16 * getResources().getDisplayMetrics().density);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(padding, padding, padding, padding);

        statusView = new TextView(this);
        statusView.setTextSize(16);
        layout.addView(statusView, matchWidth());

        statsView = new TextView(this);
        statsView.setTextSize(14);
        layout.addView(statsView, matchWidth());

        Button start = new Button(this);
        start.setText("측정 시작 (자동 재연결)");
        start.setOnClickListener(view -> startMonitoring());
        layout.addView(start, matchWidth());

        Button stop = new Button(this);
        stop.setText("측정 중지");
        stop.setOnClickListener(view -> stopMonitoring());
        layout.addView(stop, matchWidth());

        TextView help = new TextView(this);
        help.setTextSize(13);
        help.setText("센터: 1~3초 누르고 떼기 = 일시정지, 짧게 클릭 = 재개, 3초 이상 = 전원 끄기(다시 누르면 켜짐).\n"
                + "기기 측정값은 기기 시계 기준이며 System OFF 재부팅의 부트로더 시간은 포함하지 않습니다.");
        layout.addView(help, matchWidth());

        logView = new TextView(this);
        logView.setTextSize(13);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(logView);
        LinearLayout.LayoutParams scrollParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        scrollParams.setMargins(0, 12, 0, 0);
        layout.addView(scroll, scrollParams);
        return layout;
    }

    private LinearLayout.LayoutParams matchWidth() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        params.setMargins(0, 12, 0, 0);
        return params;
    }

    private void startMonitoring() {
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
        ring = null;
        for (BluetoothDevice device : adapter.getBondedDevices()) {
            if (DEVICE_NAME.equals(device.getName())) {
                ring = device;
                break;
            }
        }
        if (ring == null) {
            showStatus("Bluetooth 설정에서 " + DEVICE_NAME + "를 먼저 페어링하세요.");
            return;
        }
        monitoring = true;
        record("monitor_start", logFile.getAbsolutePath());
        connect();
    }

    private void stopMonitoring() {
        monitoring = false;
        mainHandler.removeCallbacksAndMessages(null);
        closeGatt();
        record("monitor_stop", "");
        showStatus("측정 중지됨");
    }

    private void connect() {
        if (!monitoring || ring == null) return;
        closeGatt();
        showStatus("연결 시도 중...");
        gatt = ring.connectGatt(this, false, gattCallback, BluetoothDevice.TRANSPORT_LE);
    }

    private void closeGatt() {
        if (gatt != null) {
            gatt.close();
            gatt = null;
        }
    }

    private void scheduleReconnect() {
        if (!monitoring) return;
        mainHandler.postDelayed(this::connect, RETRY_DELAY_MS);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != REQUEST_BLUETOOTH_CONNECT) return;
        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            startMonitoring();
        } else {
            showStatus("주변 기기 권한이 필요합니다.");
        }
    }

    private final BluetoothGattCallback gattCallback = new BluetoothGattCallback() {
        @Override
        public void onConnectionStateChange(BluetoothGatt g, int statusCode, int newState) {
            long now = SystemClock.elapsedRealtime();
            if (newState == BluetoothProfile.STATE_CONNECTED && statusCode == BluetoothGatt.GATT_SUCCESS) {
                connectedAt = now;
                expectedSlot = -1;
                String detail = disconnectedAt >= 0 ? "since_disconnect_ms=" + (now - disconnectedAt) : "";
                record("connected", detail);
                showStatus("연결됨. MTU 요청 중...");
                if (!g.requestMtu(247)) g.discoverServices();
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                if (connectedAt >= 0) {
                    disconnectedAt = now;  // 연결된 상태에서 끊긴 시각만 재연결 측정 기준으로 쓴다
                    connectedAt = -1;
                    subscribedAt = -1;
                    record("disconnected", "status=" + statusCode);
                } else {
                    record("connect_failed", "status=" + statusCode);
                }
                resumePending = false;
                firstDataPending = false;
                showStatus("연결 끊김 (status=" + statusCode + "). 다시 연결합니다.");
                mainHandler.post(() -> {
                    closeGatt();
                    scheduleReconnect();
                });
            }
        }

        @Override
        public void onMtuChanged(BluetoothGatt g, int mtu, int statusCode) {
            record("mtu", "mtu=" + mtu + " status=" + statusCode);
            g.discoverServices();
        }

        @Override
        public void onServicesDiscovered(BluetoothGatt g, int statusCode) {
            BluetoothGattService service = g.getService(SERVICE_UUID);
            if (statusCode != BluetoothGatt.GATT_SUCCESS || service == null) {
                showStatus("IMU 서비스를 찾지 못했습니다 (status=" + statusCode + ")");
                return;
            }
            // 알림 설정은 한 번에 하나씩: 상태 먼저, 쓰기 완료 후 데이터.
            enableNotify(g, service.getCharacteristic(STATUS_UUID));
        }

        @Override
        public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor descriptor, int statusCode) {
            UUID chr = descriptor.getCharacteristic().getUuid();
            if (statusCode != BluetoothGatt.GATT_SUCCESS) {
                showStatus("알림 설정 실패 (status=" + statusCode + ")");
                return;
            }
            if (STATUS_UUID.equals(chr)) {
                BluetoothGattService service = g.getService(SERVICE_UUID);
                enableNotify(g, service.getCharacteristic(DATA_UUID));
            } else if (DATA_UUID.equals(chr)) {
                subscribedAt = SystemClock.elapsedRealtime();
                firstDataPending = true;
                String detail = disconnectedAt >= 0 ? "since_disconnect_ms=" + (subscribedAt - disconnectedAt) : "";
                record("subscribed", detail);
                showStatus("수신 중");
            }
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic characteristic) {
            handleNotification(characteristic.getUuid(), characteristic.getValue());
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic characteristic, byte[] value) {
            handleNotification(characteristic.getUuid(), value);
        }
    };

    private void enableNotify(BluetoothGatt g, BluetoothGattCharacteristic characteristic) {
        if (characteristic == null || !g.setCharacteristicNotification(characteristic, true)) {
            showStatus("알림 설정 실패");
            return;
        }
        BluetoothGattDescriptor cccd = characteristic.getDescriptor(CCCD_UUID);
        if (cccd == null) {
            showStatus("알림 설정자(CCCD)를 찾지 못했습니다.");
            return;
        }
        cccd.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
        if (!g.writeDescriptor(cccd)) showStatus("알림 설정 쓰기 실패");
    }

    private void handleNotification(UUID uuid, byte[] value) {
        if (value == null) return;
        if (STATUS_UUID.equals(uuid)) {
            handleStatus(value);
        } else if (DATA_UUID.equals(uuid)) {
            handleData(value);
        }
    }

    private void handleStatus(byte[] v) {
        if (v.length < 10) return;
        int state = v[0] & 0xFF;
        int event = v[1] & 0xFF;
        long uptime = readU32(v, 2);
        long sinceTrigger = readU32(v, 6);
        long now = SystemClock.elapsedRealtime();
        String base = "state=" + (state == 1 ? "PAUSED" : "STREAMING") + " device_uptime_ms=" + uptime;

        switch (event) {
            case EVENT_SUBSCRIBED:
                record("status_subscribed", base);
                break;
            case EVENT_PAUSED:
                record("paused", base);
                showStatus("일시정지 (연결 유지)");
                break;
            case EVENT_RESUMED:
                resumePending = true;
                resumedStatusAt = now;
                expectedSlot = -1;  // 일시정지 동안의 슬롯 공백은 누락이 아니다
                record("resumed", base);
                break;
            case EVENT_FIRST_DATA:
                if (resumePending) {
                    resumePending = false;
                    // 기기 시계 기준: 클릭을 뗀 뒤 첫 데이터 패킷을 보낼 때까지
                    record("RESULT_pause_resume",
                            "device_release_to_first_data_ms=" + sinceTrigger
                                    + " phone_resumed_status_to_now_ms=" + (now - resumedStatusAt));
                } else if (disconnectedAt < 0) {
                    // 측정 시작 시 이미 켜져 있던 기기와의 첫 연결. 재부팅 측정이 아니다.
                    record("initial_first_data", "device_since_boot_ms=" + sinceTrigger);
                } else {
                    // 기기 시계 기준: 부팅 직후부터 첫 데이터 패킷을 보낼 때까지(부트로더 시간 제외)
                    record("RESULT_boot_reconnect",
                            "device_boot_to_first_data_ms=" + sinceTrigger
                                    + " phone_disconnect_to_now_ms=" + (now - disconnectedAt));
                }
                break;
            default:
                record("status_unknown", "event=" + event);
        }
    }

    private void handleData(byte[] v) {
        if (v.length < 5) return;
        long firstSlot = readU32(v, 0);
        int count = v[4] & 0xFF;
        if (v.length < 5 + count * 12) return;
        long now = SystemClock.elapsedRealtime();

        if (firstDataPending) {
            firstDataPending = false;
            String detail = disconnectedAt >= 0 ? "since_disconnect_ms=" + (now - disconnectedAt) : "";
            record("first_data_after_subscribe", detail);
        }
        if (expectedSlot >= 0 && firstSlot > expectedSlot) {
            missingSamples += firstSlot - expectedSlot;
        }
        expectedSlot = firstSlot + count;
        packets++;
        samples += count;

        if (rateWindowStart < 0) rateWindowStart = now;
        rateWindowSamples += count;
        if (now - rateWindowStart >= 2000) {
            recentRate = rateWindowSamples * 1000.0 / (now - rateWindowStart);
            rateWindowStart = now;
            rateWindowSamples = 0;
        }
        if (packets % 10 == 0) mainHandler.post(this::updateStats);
    }

    private static long readU32(byte[] v, int offset) {
        return (v[offset] & 0xFFL)
                | ((v[offset + 1] & 0xFFL) << 8)
                | ((v[offset + 2] & 0xFFL) << 16)
                | ((v[offset + 3] & 0xFFL) << 24);
    }

    private void updateStats() {
        statsView.setText(String.format(Locale.US,
                "패킷 %d · 샘플 %d · 누락 샘플 %d · 최근 수신율 %.1f Hz",
                packets, samples, missingSamples, recentRate));
    }

    private void record(String event, String detail) {
        long phoneMs = SystemClock.elapsedRealtime();
        String wall = new SimpleDateFormat("HH:mm:ss.SSS", Locale.US).format(new Date());
        appendLogFile(wall + "," + phoneMs + "," + event + "," + detail.replace(',', ';'));
        String line = wall + "  " + event + (detail.isEmpty() ? "" : "  " + detail);
        mainHandler.post(() -> logView.append(line + "\n"));
    }

    private void appendLogFile(String line) {
        if (logFile == null) return;
        try (FileWriter writer = new FileWriter(logFile, true)) {
            writer.write(line + "\n");
        } catch (IOException ignored) {
            // 화면 기록은 계속 남으므로 파일 쓰기 실패로 측정을 멈추지 않는다
        }
    }

    private void showStatus(String message) {
        mainHandler.post(() -> statusView.setText(message));
    }

    @Override
    protected void onDestroy() {
        monitoring = false;
        mainHandler.removeCallbacksAndMessages(null);
        closeGatt();
        super.onDestroy();
    }
}
