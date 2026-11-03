"""RingPilot 제스처 모델(TCN) 정의. 학습하지 않는다. 지난 2층 CNN(build_model)은 커밋 1162a44 이전 이력에 있다."""

from tensorflow import keras


SAMPLE_RATE_HZ = 100
WINDOW_SAMPLES = 160
AXES = ("accX", "accY", "accZ", "gyrX", "gyrY", "gyrZ")
CLASS_NAMES = ("NONE", "UP", "DOWN", "LEFT", "RIGHT")


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
    build_tcn(channels=6).summary()
