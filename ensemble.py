import numpy as np
from typing import Dict, Tuple
from .isolation_forest import QuickAnomalyDetector
from .lstm_autoencoder import LSTMAnomalyDetector
from loguru import logger


class EnsembleAnomalyDetector:
    """
    Ансамблевый детектор:
    1. Быстрый (Isolation Forest) для фильтрации
    2. Тяжёлый (LSTM Autoencoder) для подтверждения
    """

    def __init__(self, contamination: float = 0.05):
        self.quick_detector = QuickAnomalyDetector(contamination=contamination)
        self.deep_detector = LSTMAnomalyDetector()
        self.is_trained = False

        # Веса для финального решения
        self.quick_weight = 0.3
        self.deep_weight = 0.7

    def train(self, X_normal: np.ndarray):
        """
        Обучает оба детектора на нормальных данных
        """
        logger.info("Training ensemble (2-stage)")

        # Обучаем быстрый детектор
        self.quick_detector.train(X_normal)

        # Обучаем глубокий детектор
        self.deep_detector.train(X_normal)

        self.is_trained = True
        logger.info("Ensemble training complete")

    def predict(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Возвращает: (anomaly_scores, quick_results, deep_results)
        """
        if not self.is_trained:
            raise ValueError("Ensemble not trained")

        # Stage 1: Быстрая проверка
        quick_scores = self.quick_detector.predict_proba(X)
        quick_is_anomaly = self.quick_detector.predict(X) == -1

        # Stage 2: Глубокая проверка (только для образцов, пропущенных быстрым)
        deep_scores = np.zeros(len(X))
        deep_is_anomaly = np.zeros(len(X), dtype=bool)

        # Пропускаем через LSTM только потенциально аномальные или случайную выборку
        indices_to_check = np.where(quick_is_anomaly)[0]

        if len(indices_to_check) > 0:
            X_to_check = X[indices_to_check]
            deep_scores_sub, deep_anomaly_sub = self.deep_detector.predict(X_to_check)

            deep_scores[indices_to_check] = deep_scores_sub
            deep_is_anomaly[indices_to_check] = deep_anomaly_sub

        # Ансамблевая оценка
        ensemble_scores = self.quick_weight * quick_scores + self.deep_weight * deep_scores

        return ensemble_scores, quick_is_anomaly, deep_is_anomaly

    def predict_single(self, x: np.ndarray) -> Dict:
        """
        Предсказание для одного образца
        """
        x_reshaped = x.reshape(1, -1)
        scores, quick_res, deep_res = self.predict(x_reshaped)

        # Определяем степень угрозы
        if scores[0] > 0.8 and deep_res[0]:
            severity = "CRITICAL"
        elif scores[0] > 0.6:
            severity = "HIGH"
        elif scores[0] > 0.4:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        return {
            'anomaly_score': float(scores[0]),
            'quick_anomaly': bool(quick_res[0]),
            'deep_anomaly': bool(deep_res[0]),
            'severity': severity,
            'is_anomaly': scores[0] > 0.5
        }