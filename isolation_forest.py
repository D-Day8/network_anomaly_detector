import numpy as np
from sklearn.ensemble import IsolationForest
from typing import Optional
from loguru import logger


class QuickAnomalyDetector:
    """
    Быстрый детектор аномалий на основе Isolation Forest
    Для первого эшелона обнаружения
    """

    def __init__(self, contamination: float = 0.05, random_state: int = 42):
        self.model = IsolationForest(
            contamination=contamination,
            random_state=random_state,
            n_estimators=100,
            max_samples='auto',
            bootstrap=False
        )
        self.is_trained = False

    def train(self, X: np.ndarray):
        """
        Обучение на нормальных данных
        """
        self.model.fit(X)
        self.is_trained = True
        logger.info(f"Isolation Forest trained on {len(X)} samples")

    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Предсказание: 1 = норма, -1 = аномалия
        """
        if not self.is_trained:
            raise ValueError("Model not trained")

        return self.model.predict(X)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        Оценка аномальности (чем выше, тем более аномально)
        """
        if not self.is_trained:
            raise ValueError("Model not trained")

        # Isolation Forest даёт оценку аномальности в decision_function
        scores = -self.model.decision_function(X)

        # Нормализуем в [0, 1]
        min_score = np.min(scores)
        max_score = np.max(scores)
        if max_score > min_score:
            scores = (scores - min_score) / (max_score - min_score)

        return scores