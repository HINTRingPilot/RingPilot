"""RingPilot 무선 데이터용 첫 CNN. 모델 정의만 제공하며 학습하지 않는다."""

from tensorflow import keras


SAMPLE_RATE_HZ = 100
WINDOW_SAMPLES = 160
AXES = ("accX", "accY", "accZ", "gyrX", "gyrY", "gyrZ")
CLASS_NAMES = ("NONE", "UP", "DOWN", "LEFT", "RIGHT")


def build_model(window_samples=WINDOW_SAMPLES, readout="flatten", channels=len(AXES)):
    """훈련 자료에서 구한 축별 고정 정규화를 적용한 입력을 받는다. channels는 6축 뒤에 붙인 채널까지 센 수다."""
    if not isinstance(window_samples, int) or isinstance(window_samples, bool) or window_samples < 4:
        raise ValueError("window_samples must be an integer >= 4")
    if readout not in ("flatten", "gap"):
        raise ValueError("readout must be 'flatten' or 'gap'")
    if not isinstance(channels, int) or channels < len(AXES):
        raise ValueError(f"channels must be an integer >= {len(AXES)}")
    return keras.Sequential(
        [
            keras.layers.Input(shape=(window_samples, channels), name="imu_window"),
            keras.layers.Conv1D(
                16, 5, strides=1, padding="same", activation="relu", name="conv1"
            ),
            keras.layers.MaxPooling1D(pool_size=2, strides=2, name="pool1"),
            keras.layers.Dropout(0.2, name="dropout1"),
            keras.layers.Conv1D(
                32, 5, strides=1, padding="same", activation="relu", name="conv2"
            ),
            keras.layers.MaxPooling1D(pool_size=2, strides=2, name="pool2"),
            (keras.layers.Flatten(name="time_features") if readout == "flatten"
             else keras.layers.GlobalAveragePooling1D(name="time_features")),
            keras.layers.Dropout(0.3, name="dropout2"),
            keras.layers.Dense(len(CLASS_NAMES), activation="softmax", name="event"),
        ],
        name="ringpilot_cnn_v1",
    )


if __name__ == "__main__":
    build_model().summary()
