import numpy as np
import pandas as pd
from typing import List, Dict, Optional
from sklearn.preprocessing import StandardScaler
from loguru import logger


class FeatureExtractor:
    """
    Извлечение и нормализация признаков из сетевых потоков
    """

    # Имена признаков (должны совпадать с NetworkFlow.get_features)
    FEATURE_NAMES = [
        'duration', 'packet_count', 'bytes_total', 'bytes_per_sec', 'packets_per_sec',
        'iat_mean', 'iat_std', 'iat_min', 'iat_max', 'iat_median',
        'size_mean', 'size_std', 'size_min', 'size_max', 'size_median',
        'bytes_per_packet', 'packet_size_variance',
        'syn_count', 'ack_count', 'rst_count', 'fin_count'
    ]

    def __init__(self):
        self.scaler = StandardScaler()
        self.is_fitted = False

    def extract_flows_to_dataframe(self, flows: List) -> pd.DataFrame:
        """
        Конвертирует список потоков в DataFrame с признаками
        """
        features_list = []

        for flow in flows:
            features = flow.get_features()
            if features is not None and len(features) == len(self.FEATURE_NAMES):
                features_list.append(features)

        if not features_list:
            return pd.DataFrame(columns=self.FEATURE_NAMES)

        df = pd.DataFrame(features_list, columns=self.FEATURE_NAMES)

        # Обработка NaN и Inf
        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.fillna(0)

        return df

    def fit_normalize(self, df: pd.DataFrame):
        """
        Обучает нормализатор на нормальных данных
        """
        self.scaler.fit(df)
        self.is_fitted = True
        logger.info(f"Fitted scaler on {len(df)} samples")

    def normalize(self, df: pd.DataFrame) -> np.ndarray:
        """
        Нормализует признаки
        """
        if not self.is_fitted:
            raise ValueError("Scaler not fitted. Call fit_normalize first.")

        # Убеждаемся, что колонки совпадают
        missing_cols = set(self.FEATURE_NAMES) - set(df.columns)
        if missing_cols:
            for col in missing_cols:
                df[col] = 0

        df = df[self.FEATURE_NAMES]
        df = df.replace([np.inf, -np.inf], np.nan).fillna(0)

        return self.scaler.transform(df)

    def denormalize(self, X: np.ndarray) -> np.ndarray:
        """Обратная нормализация"""
        return self.scaler.inverse_transform(X)