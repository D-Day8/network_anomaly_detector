import asyncio
import numpy as np
import pandas as pd
from typing import Optional, List, Dict
from collections import deque
from datetime import datetime
from loguru import logger

from ..capture.sniffer import AsyncPacketSniffer
from ..capture.flow_builder import FlowBuilder
from ..features.extractor import FeatureExtractor
from ..models.ensemble import EnsembleAnomalyDetector


class RealTimeAnomalyPipeline:
    """
    Реалтайм пайплайн обработки трафика
    """

    def __init__(
            self,
            interface: Optional[str] = None,
            flow_timeout: float = 60,
            batch_size: int = 100,
            anomaly_history_size: int = 1000
    ):
        self.interface = interface
        self.flow_builder = FlowBuilder(idle_timeout=flow_timeout)
        self.feature_extractor = FeatureExtractor()
        self.detector = EnsembleAnomalyDetector()

        self.sniffer = AsyncPacketSniffer(interface=interface)
        self.batch_size = batch_size
        self.packet_buffer = deque(maxlen=batch_size * 10)

        # Статистика
        self.anomaly_history = deque(maxlen=anomaly_history_size)
        self.total_flows_processed = 0
        self.anomalies_detected = 0

        # Контрольные флаги
        self.is_running = False
        self.is_trained = False

    async def train_offline(self, pcap_path: str):
        """
        Оффлайн обучение на дампе нормального трафика
        """
        logger.info(f"Training on offline PCAP: {pcap_path}")

        # Импортируем здесь, чтобы не замедлять импорт
        from scapy.all import rdpcap

        # Загружаем дамп
        packets = rdpcap(pcap_path)
        logger.info(f"Loaded {len(packets)} packets")

        # Обрабатываем пакеты для сборки потоков
        for packet in packets:
            packet_info = self.sniffer._extract_packet_info(packet)
            if packet_info:
                self.flow_builder.process_packet(packet_info)

        # Получаем потоки
        flows = self.flow_builder.get_completed_flows()
        logger.info(f"Extracted {len(flows)} flows")

        # Извлекаем признаки
        df = self.feature_extractor.extract_flows_to_dataframe(flows)
        logger.info(f"Extracted {len(df)} feature vectors")

        if len(df) < 100:
            raise ValueError(f"Not enough flows for training: {len(df)}")

        # Нормализуем
        self.feature_extractor.fit_normalize(df)
        X_normal = self.feature_extractor.normalize(df)

        # Обучаем детектор
        self.detector.train(X_normal)

        self.is_trained = True
        logger.info("Training completed successfully")

    async def start_realtime(self):
        """
        Запуск реалтайм детекции
        """
        if not self.is_trained:
            raise ValueError("Pipeline not trained. Call train_offline first.")

        logger.info(f"Starting real-time detection on interface {self.interface}")

        # Запускаем сниффер
        self.sniffer.start()
        self.is_running = True

        # Периодическая очистка потоков
        cleanup_task = asyncio.create_task(self._periodic_cleanup())

        # Основной цикл обработки
        try:
            while self.is_running:
                # Получаем пакет
                packet = await self.sniffer.get_packet(timeout=0.1)

                if packet:
                    self.packet_buffer.append(packet)
                    self.flow_builder.process_packet(packet)

                # Обрабатываем накопленные потоки
                if len(self.flow_builder.completed_flows) >= self.batch_size:
                    await self._process_batch()

        except KeyboardInterrupt:
            logger.info("Stopping real-time pipeline...")
        finally:
            self.is_running = False
            cleanup_task.cancel()
            self.sniffer.stop()

    async def _periodic_cleanup(self):
        """Периодическая очистка истекших потоков"""
        while self.is_running:
            await asyncio.sleep(5)
            self.flow_builder.cleanup_expired_flows()

    async def _process_batch(self):
        """Обрабатывает батч потоков"""
        flows = self.flow_builder.get_completed_flows()

        if not flows:
            return

        # Извлекаем признаки
        df = self.feature_extractor.extract_flows_to_dataframe(flows)

        if len(df) == 0:
            return

        # Нормализуем
        X = self.feature_extractor.normalize(df)

        # Детектируем аномалии
        scores, quick_res, deep_res = self.detector.predict(X)

        # Логируем результаты
        for i, (flow, score, quick, deep) in enumerate(zip(flows, scores, quick_res, deep_res)):
            self.total_flows_processed += 1

            if score > 0.5:
                self.anomalies_detected += 1

                # Определяем тип аномалии
                anomaly_type = self._classify_anomaly(flow, score, quick, deep)

                # Логируем
                logger.warning(
                    f"ANOMALY DETECTED | Score: {score:.3f} | Type: {anomaly_type} | "
                    f"Flow: {flow.src_ip}:{flow.src_port} -> {flow.dst_ip}:{flow.dst_port}"
                )

                # Сохраняем в историю
                self.anomaly_history.append({
                    'timestamp': datetime.now(),
                    'score': score,
                    'type': anomaly_type,
                    'flow': flow,
                    'features': df.iloc[i].to_dict() if i < len(df) else {}
                })

        # Периодический вывод статистики
        if self.total_flows_processed % 1000 == 0:
            anomaly_rate = self.anomalies_detected / self.total_flows_processed
            logger.info(
                f"Stats: {self.total_flows_processed} flows processed, "
                f"{self.anomalies_detected} anomalies ({anomaly_rate:.2%})"
            )

    def _classify_anomaly(self, flow, score: float, quick: bool, deep: bool) -> str:
        """
        Классифицирует тип аномалии на основе паттернов
        """
        # Простая эвристика
        if flow.packet_count > 1000 and flow.duration < 10:
            return "POSSIBLE_DDOS"
        elif flow.syn_count > flow.ack_count * 10:
            return "SYN_SCAN"
        elif flow.rst_count > 5:
            return "CONNECTION_RESET_FLOOD"
        elif flow.bytes_per_sec > 1000000 and flow.packets_per_sec > 1000:
            return "TRAFFIC_BURST"
        elif abs(flow.iat_std - flow.iat_mean) / max(0.001, flow.iat_mean) > 10:
            return "IRREGULAR_TIMING"
        else:
            return "UNKNOWN_ANOMALY"

    def get_stats(self) -> Dict:
        """Возвращает статистику работы"""
        return {
            'flows_processed': self.total_flows_processed,
            'anomalies_detected': self.anomalies_detected,
            'anomaly_rate': self.anomalies_detected / max(1, self.total_flows_processed),
            'active_flows': self.flow_builder.get_active_flow_count(),
            'buffer_size': len(self.packet_buffer)
        }