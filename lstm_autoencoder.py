import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, Model, Sequential
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint
from typing import Tuple, Optional
import os
from loguru import logger


class LSTMAnomalyDetector:
    """
    LSTM Autoencoder для детекции аномалий в временных рядах
    Второй эшелон - глубокое обучение
    """

    def __init__(
            self,
            latent_dim: int = 32,
            sequence_length: int = 10,
            learning_rate: float = 0.001,
            model_path: str = "models_saved/lstm_ae.h5"
    ):
        self.latent_dim = latent_dim
        self.sequence_length = sequence_length
        self.learning_rate = learning_rate
        self.model_path = model_path
        self.model: Optional[Model] = None
        self.threshold: Optional[float] = None
        self.feature_dim: Optional[int] = None

    def _build_autoencoder(self, input_dim: int) -> Model:
        """
        Строит LSTM Autoencoder архитектуру
        """
        # Энкодер
        encoder_input = layers.Input(shape=(self.sequence_length, input_dim))

        # Stacked LSTM для энкодера
        encoded = layers.LSTM(128, return_sequences=True)(encoder_input)
        encoded = layers.LSTM(64, return_sequences=False)(encoded)

        # Латентое пространство
        latent = layers.Dense(self.latent_dim, activation='relu')(encoded)

        # Декодер
        decoded = layers.RepeatVector(self.sequence_length)(latent)
        decoded = layers.LSTM(64, return_sequences=True)(decoded)
        decoded = layers.LSTM(128, return_sequences=True)(decoded)

        # Выходной слой
        decoder_output = layers.TimeDistributed(
            layers.Dense(input_dim, activation='linear')
        )(decoded)

        autoencoder = Model(encoder_input, decoder_output)

        # Compile
        optimizer = tf.keras.optimizers.Adam(learning_rate=self.learning_rate)
        autoencoder.compile(optimizer=optimizer, loss='mse')

        return autoencoder

    def _create_sequences(self, X: np.ndarray) -> np.ndarray:
        """
        Создаёт последовательности для LSTM
        X: (samples, features)
        returns: (samples - sequence_length + 1, sequence_length, features)
        """
        n_samples = X.shape[0]
        sequences = []

        for i in range(n_samples - self.sequence_length + 1):
            seq = X[i:i + self.sequence_length]
            sequences.append(seq)

        return np.array(sequences)

    def train(
            self,
            X: np.ndarray,
            validation_split: float = 0.1,
            epochs: int = 100,
            batch_size: int = 32
    ):
        """
        Обучение автоэнкодера на нормальных данных
        """
        self.feature_dim = X.shape[1]

        # Создаём последовательности
        X_seq = self._create_sequences(X)

        if len(X_seq) < 10:
            raise ValueError(f"Not enough samples for sequences: {len(X_seq)}")

        logger.info(f"Training LSTM Autoencoder on {len(X_seq)} sequences")

        # Строим модель
        self.model = self._build_autoencoder(self.feature_dim)
        self.model.summary()

        # Callbacks
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        callbacks = [
            EarlyStopping(patience=10, restore_best_weights=True),
            ModelCheckpoint(self.model_path, save_best_only=True)
        ]

        # Обучение
        history = self.model.fit(
            X_seq, X_seq,
            validation_split=validation_split,
            epochs=epochs,
            batch_size=batch_size,
            callbacks=callbacks,
            verbose=1
        )

        # Вычисляем порог аномалии (95-й перцентиль ошибок на тренировочных данных)
        reconstructions = self.model.predict(X_seq)
        mse = np.mean(np.square(X_seq - reconstructions), axis=(1, 2))
        self.threshold = np.percentile(mse, 95)

        logger.info(f"LSTM Autoencoder trained. Threshold = {self.threshold:.4f}")

        return history

    def load(self):
        """
        Загружает сохранённую модель
        """
        if os.path.exists(self.model_path):
            self.model = tf.keras.models.load_model(self.model_path)
            logger.info(f"Loaded model from {self.model_path}")
        else:
            raise FileNotFoundError(f"Model not found at {self.model_path}")

    def predict(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Предсказывает аномалии
        Returns: (anomaly_scores, is_anomaly)
        """
        if self.model is None:
            raise ValueError("Model not trained or loaded")

        # Создаём последовательности
        X_seq = self._create_sequences(X)

        # Реконструкция
        reconstructions = self.model.predict(X_seq)

        # Ошибка реконструкции
        mse = np.mean(np.square(X_seq - reconstructions), axis=(1, 2))

        # Аномалия, если ошибка > порога
        is_anomaly = mse > self.threshold

        return mse, is_anomaly

    def get_reconstruction_error(self, X: np.ndarray) -> float:
        """
        Возвращает среднюю ошибку реконструкции для одного потока
        """
        if self.model is None:
            raise ValueError("Model not trained")

        # Для одного образца нужно решейпить
        if len(X.shape) == 1:
            X = X.reshape(1, -1)

        # Дублируем, чтобы создать последовательность
        n_repeats = max(1, self.sequence_length - len(X) + 1)
        X_seq = np.tile(X, (n_repeats, 1))
        X_seq = self._create_sequences(X_seq)

        if len(X_seq) == 0:
            return 0.0

        reconstructions = self.model.predict(X_seq)
        mse = np.mean(np.square(X_seq - reconstructions), axis=(1, 2))

        return float(np.mean(mse))