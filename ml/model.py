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


TCN_DILATIONS = (1, 2, 4, 8, 16, 49)


def receptive_field(kernel=3, dilations=TCN_DILATIONS):
    """맨 마지막 시점 출력이 볼 수 있는 입력 샘플 수."""
    return 1 + (kernel - 1) * sum(dilations)


def build_tcn(window_samples=WINDOW_SAMPLES, channels=len(AXES), filters=16, kernel=3,
              dilations=TCN_DILATIONS, dropout=0.1):
    """인과 팽창 합성곱 TCN. 블록마다 합성곱 1개(ReLU, 드롭아웃) + 잔차 덧셈, 정규화 층 없음.

    첫 블록은 입력 채널이 filters와 다르므로 1×1 합성곱으로 채널을 맞춰 더한다. 판정은 마지막 블록의
    마지막 시점 특징(filters개)만 Dense로 받는다. 기본 dilation 1·2·4·8·16·49는 161샘플을 봐서 160샘플 창을 덮는다.
    """
    if channels < len(AXES):
        raise ValueError(f"channels must be >= {len(AXES)}")
    inputs = keras.layers.Input(shape=(window_samples, channels), name="imu_window")
    x = inputs
    for i, d in enumerate(dilations, start=1):
        h = keras.layers.Conv1D(filters, kernel, dilation_rate=d, padding="causal", activation="relu", name=f"block{i}_conv")(x)
        h = keras.layers.Dropout(dropout, name=f"block{i}_dropout")(h)
        skip = x if x.shape[-1] == filters else keras.layers.Conv1D(filters, 1, name=f"block{i}_match")(x)
        x = keras.layers.Add(name=f"block{i}")([skip, h])
    last = keras.layers.Cropping1D((window_samples - 1, 0), name="last_step")(x)     # 마지막 시점만 남긴다(저장·변환 가능한 표준 층)
    last = keras.layers.Flatten(name="last_features")(last)
    outputs = keras.layers.Dense(len(CLASS_NAMES), activation="softmax", name="event")(last)
    return keras.Model(inputs, outputs, name="ringpilot_tcn_v1")


if __name__ == "__main__":
    build_model().summary()
    build_tcn(channels=9).summary()
