package com.hintringpilot.ringpilot;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.UUID;

/**
 * RingPilot-IMU(firmware/imu_ble_stream)에 연결해 IMU 원시값 알림을 받는다.
 * 끊기면 자동으로 다시 연결하고, 연결·일시정지·재개 이벤트와 지연 측정값을 connection_log.csv에 남긴다.
 * 콜백은 Bluetooth 스레드에서 호출된다.
 */
final class ImuBleClient {
    interface Listener {
        /** raw에는 샘플마다 accX,accY,accZ,gyrX,gyrY,gyrZ 원시값이 이어서 들어 있다. */
        void onSamples(long firstSlot, short[] raw, int count);

        void onConnectionText(String text);

        /** 보드(firmware/gesture_infer)가 발행한 제스처. direction은 UP, DOWN, LEFT, RIGHT다. */
        void onGesture(String direction, int sequence, double score);
    }

    static final String DEVICE_NAME = "RingPilot-IMU";
    private static final UUID SERVICE_UUID = UUID.fromString("b27a2000-8c5e-4b62-9a21-33dd714e9001");
    private static final UUID DATA_UUID = UUID.fromString("b27a2001-8c5e-4b62-9a21-33dd714e9001");
    private static final UUID STATUS_UUID = UUID.fromString("b27a2002-8c5e-4b62-9a21-33dd714e9001");
    private static final UUID GESTURE_UUID = UUID.fromString("b27a2003-8c5e-4b62-9a21-33dd714e9001");
    private static final String[] GESTURE_NAMES = {"NONE", "UP", "DOWN", "LEFT", "RIGHT"};
    private static final UUID CCCD_UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
    private static final long RETRY_DELAY_MS = 300;

    // 펌웨어 상태 패킷의 이벤트 번호
    private static final int EVENT_SUBSCRIBED = 0;
    private static final int EVENT_PAUSED = 1;
    private static final int EVENT_RESUMED = 2;
    private static final int EVENT_FIRST_DATA = 3;

    private final Context context;
    private final Listener listener;
    private final File logFile;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private BluetoothDevice device;
    private BluetoothGatt gatt;
    private boolean running = false;

    private volatile boolean streaming = false;
    private volatile boolean devicePaused = false;
    private volatile long missingSamples = 0;
    private volatile double recentRate = 0;

    // 아래 값은 모두 Bluetooth 콜백 스레드에서만 바뀐다. 시각은 SystemClock.elapsedRealtime() 기준 ms.
    private long disconnectedAt = -1;
    private long connectedAt = -1;
    private long resumedStatusAt = -1;
    private boolean resumePending = false;
    private long expectedSlot = -1;
    private long rateWindowStart = -1;
    private long rateWindowSamples = 0;

    ImuBleClient(Context context, File logFile, Listener listener) {
        this.context = context;
        this.logFile = logFile;
        this.listener = listener;
    }

    boolean isStreaming() {
        return streaming;
    }

    boolean isDevicePaused() {
        return devicePaused;
    }

    long missingSamples() {
        return missingSamples;
    }

    double recentRate() {
        return recentRate;
    }

    /** 본딩된 RingPilot-IMU를 찾아 연결을 시작한다. 실패하면 이유를 반환하고, 성공하면 null. */
    String start() {
        BluetoothManager manager = context.getSystemService(BluetoothManager.class);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) return "Bluetooth를 켜세요.";
        device = null;
        for (BluetoothDevice bonded : adapter.getBondedDevices()) {
            if (DEVICE_NAME.equals(bonded.getName())) {
                device = bonded;
                break;
            }
        }
        if (device == null) return "Bluetooth 설정에서 " + DEVICE_NAME + "를 먼저 페어링하세요.";
        running = true;
        record("client_start", "");
        connect();
        return null;
    }

    void stop() {
        running = false;
        streaming = false;
        mainHandler.removeCallbacksAndMessages(null);
        closeGatt();
    }

    private void connect() {
        if (!running || device == null) return;
        closeGatt();
        listener.onConnectionText("연결 시도 중");
        gatt = device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE);
    }

    private void closeGatt() {
        if (gatt != null) {
            gatt.close();
            gatt = null;
        }
    }

    private final BluetoothGattCallback callback = new BluetoothGattCallback() {
        @Override
        public void onConnectionStateChange(BluetoothGatt g, int statusCode, int newState) {
            long now = SystemClock.elapsedRealtime();
            if (newState == BluetoothProfile.STATE_CONNECTED && statusCode == BluetoothGatt.GATT_SUCCESS) {
                connectedAt = now;
                expectedSlot = -1;
                record("connected", disconnectedAt >= 0 ? "since_disconnect_ms=" + (now - disconnectedAt) : "");
                listener.onConnectionText("연결됨, 설정 중");
                if (!g.requestMtu(247)) g.discoverServices();
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                streaming = false;
                if (connectedAt >= 0) {
                    disconnectedAt = now;  // 연결된 상태에서 끊긴 시각만 재연결 측정 기준으로 쓴다
                    connectedAt = -1;
                    record("disconnected", "status=" + statusCode);
                } else {
                    record("connect_failed", "status=" + statusCode);
                }
                resumePending = false;
                listener.onConnectionText("연결 끊김, 다시 연결 중");
                mainHandler.post(() -> {
                    closeGatt();
                    if (running) mainHandler.postDelayed(ImuBleClient.this::connect, RETRY_DELAY_MS);
                });
            }
        }

        @Override
        public void onMtuChanged(BluetoothGatt g, int mtu, int statusCode) {
            record("mtu", "mtu=" + mtu + " status=" + statusCode);
            refreshGattCache(g);
            g.discoverServices();
        }

        @Override
        public void onServicesDiscovered(BluetoothGatt g, int statusCode) {
            BluetoothGattService service = g.getService(SERVICE_UUID);
            if (statusCode != BluetoothGatt.GATT_SUCCESS || service == null) {
                listener.onConnectionText("IMU 서비스를 찾지 못함 (status=" + statusCode + ")");
                return;
            }
            // 알림 설정은 한 번에 하나씩: 상태 먼저, 쓰기 완료 후 데이터.
            enableNotify(g, service.getCharacteristic(STATUS_UUID));
        }

        @Override
        public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor descriptor, int statusCode) {
            if (statusCode != BluetoothGatt.GATT_SUCCESS) {
                listener.onConnectionText("알림 설정 실패 (status=" + statusCode + ")");
                return;
            }
            UUID chr = descriptor.getCharacteristic().getUuid();
            if (STATUS_UUID.equals(chr)) {
                enableNotify(g, g.getService(SERVICE_UUID).getCharacteristic(DATA_UUID));
            } else if (DATA_UUID.equals(chr)) {
                streaming = true;
                long now = SystemClock.elapsedRealtime();
                record("subscribed", disconnectedAt >= 0 ? "since_disconnect_ms=" + (now - disconnectedAt) : "");
                listener.onConnectionText("수신 중");
                // 수집 펌웨어(imu_ble_stream)에는 이 특성이 없다. 없으면 건너뛴다
                BluetoothGattCharacteristic gesture = g.getService(SERVICE_UUID).getCharacteristic(GESTURE_UUID);
                record("gesture_characteristic", gesture != null ? "found" : "missing");
                if (gesture != null) enableNotify(g, gesture);
            } else if (GESTURE_UUID.equals(chr)) {
                record("gesture_subscribed", "");
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

    /** 본딩된 기기의 GATT 목록은 휴대폰에 캐시된다. 펌웨어에 특성이 추가돼도 보이도록 비운다(숨은 API, 실패하면 캐시를 그대로 쓴다). */
    private void refreshGattCache(BluetoothGatt g) {
        try {
            Object ok = g.getClass().getMethod("refresh").invoke(g);
            record("gatt_refresh", String.valueOf(ok));
        } catch (ReflectiveOperationException e) {
            record("gatt_refresh", "failed " + e.getClass().getSimpleName());
        }
    }

    private void enableNotify(BluetoothGatt g, BluetoothGattCharacteristic characteristic) {
        BluetoothGattDescriptor cccd = characteristic == null ? null : characteristic.getDescriptor(CCCD_UUID);
        if (cccd == null || !g.setCharacteristicNotification(characteristic, true)) {
            listener.onConnectionText("알림 설정 실패");
            return;
        }
        cccd.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
        if (!g.writeDescriptor(cccd)) listener.onConnectionText("알림 설정 쓰기 실패");
    }

    private void handleNotification(UUID uuid, byte[] value) {
        if (value == null) return;
        if (STATUS_UUID.equals(uuid)) handleStatus(value);
        else if (DATA_UUID.equals(uuid)) handleData(value);
        else if (GESTURE_UUID.equals(uuid)) handleGesture(value);
    }

    private void handleStatus(byte[] v) {
        if (v.length < 10) return;
        int state = v[0] & 0xFF;
        int event = v[1] & 0xFF;
        long uptime = readU32(v, 2);
        long sinceTrigger = readU32(v, 6);
        long now = SystemClock.elapsedRealtime();
        devicePaused = state == 1;
        String base = "state=" + (devicePaused ? "PAUSED" : "STREAMING") + " device_uptime_ms=" + uptime;

        switch (event) {
            case EVENT_SUBSCRIBED:
                record("status_subscribed", base);
                break;
            case EVENT_PAUSED:
                record("paused", base);
                listener.onConnectionText("링 일시정지됨 (연결 유지)");
                break;
            case EVENT_RESUMED:
                resumePending = true;
                resumedStatusAt = now;
                expectedSlot = -1;  // 일시정지 동안의 슬롯 공백은 누락이 아니다
                record("resumed", base);
                listener.onConnectionText("수신 중");
                break;
            case EVENT_FIRST_DATA:
                if (resumePending) {
                    resumePending = false;
                    record("RESULT_pause_resume", "device_release_to_first_data_ms=" + sinceTrigger
                            + " phone_resumed_status_to_now_ms=" + (now - resumedStatusAt));
                } else if (disconnectedAt < 0) {
                    record("initial_first_data", "device_since_boot_ms=" + sinceTrigger);
                } else {
                    record("RESULT_boot_reconnect", "device_boot_to_first_data_ms=" + sinceTrigger
                            + " phone_disconnect_to_now_ms=" + (now - disconnectedAt));
                }
                break;
            default:
                record("status_unknown", "event=" + event);
        }
    }

    private void handleGesture(byte[] v) {
        if (v.length < 8) return;
        int sequence = v[0] & 0xFF;
        int index = v[1] & 0xFF;
        if (index < 1 || index >= GESTURE_NAMES.length) return;
        double score = ((v[2] & 0xFF) | ((v[3] & 0xFF) << 8)) / 1000.0;
        record("gesture", "seq=" + sequence + " dir=" + GESTURE_NAMES[index] + " score=" + score + " slot=" + readU32(v, 4));
        listener.onGesture(GESTURE_NAMES[index], sequence, score);
    }

    private void handleData(byte[] v) {
        if (v.length < 5) return;
        long firstSlot = readU32(v, 0);
        int count = v[4] & 0xFF;
        if (v.length < 5 + count * 12) return;

        short[] raw = new short[count * 6];
        for (int i = 0; i < raw.length; i++) {
            int offset = 5 + i * 2;
            raw[i] = (short) ((v[offset] & 0xFF) | (v[offset + 1] << 8));
        }

        if (expectedSlot >= 0 && firstSlot > expectedSlot) missingSamples += firstSlot - expectedSlot;
        expectedSlot = firstSlot + count;
        long now = SystemClock.elapsedRealtime();
        if (rateWindowStart < 0) rateWindowStart = now;
        rateWindowSamples += count;
        if (now - rateWindowStart >= 2000) {
            recentRate = rateWindowSamples * 1000.0 / (now - rateWindowStart);
            rateWindowStart = now;
            rateWindowSamples = 0;
        }
        listener.onSamples(firstSlot, raw, count);
    }

    private static long readU32(byte[] v, int offset) {
        return (v[offset] & 0xFFL)
                | ((v[offset + 1] & 0xFFL) << 8)
                | ((v[offset + 2] & 0xFFL) << 16)
                | ((v[offset + 3] & 0xFFL) << 24);
    }

    private synchronized void record(String event, String detail) {
        String wall = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US).format(new Date());
        boolean header = !logFile.exists();
        try (FileWriter writer = new FileWriter(logFile, true)) {
            if (header) writer.write("wall_time,phone_ms,event,detail\n");
            writer.write(wall + "," + SystemClock.elapsedRealtime() + "," + event + "," + detail.replace(',', ';') + "\n");
        } catch (IOException ignored) {
            // 연결 기록 실패로 수집을 멈추지 않는다
        }
    }
}
