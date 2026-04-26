import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import numpy as np
from loguru import logger


@dataclass
class NetworkFlow:
    """Сетевой поток (5-кортеж)"""
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    protocol: int

    # Статистики
    packets: List[Dict] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

    # Счётчики
    packet_count: int = 0
    bytes_sent: int = 0
    bytes_recv: int = 0

    def add_packet(self, packet_info: Dict):
        """Добавляет пакет в поток"""
        self.packets.append(packet_info)
        self.packet_count += 1
        self.bytes_sent += packet_info['size']

        if self.start_time == 0:
            self.start_time = packet_info['timestamp']
        self.end_time = packet_info['timestamp']

    def get_features(self) -> np.ndarray:
        """Извлекает признаковый вектор из потока"""
        if len(self.packets) < 2:
            return None

        # Межпакетные интервалы (IAT)
        timestamps = [p['timestamp'] for p in self.packets]
        iats = np.diff(timestamps)

        # Размеры пакетов
        sizes = [p['size'] for p in self.packets]

        # TCP флаги (если есть)
        tcp_flags = [p.get('tcp_flags', 0) for p in self.packets if p.get('tcp_flags') is not None]

        features = {
            # Базовые метрики
            'duration': self.end_time - self.start_time,
            'packet_count': self.packet_count,
            'bytes_total': self.bytes_sent,
            'bytes_per_sec': self.bytes_sent / max(0.001, self.end_time - self.start_time),
            'packets_per_sec': self.packet_count / max(0.001, self.end_time - self.start_time),

            # Статистики IAT
            'iat_mean': np.mean(iats) if len(iats) > 0 else 0,
            'iat_std': np.std(iats) if len(iats) > 0 else 0,
            'iat_min': np.min(iats) if len(iats) > 0 else 0,
            'iat_max': np.max(iats) if len(iats) > 0 else 0,
            'iat_median': np.median(iats) if len(iats) > 0 else 0,

            # Статистики размеров
            'size_mean': np.mean(sizes),
            'size_std': np.std(sizes),
            'size_min': np.min(sizes),
            'size_max': np.max(sizes),
            'size_median': np.median(sizes),

            # Отношения и пропорции
            'bytes_per_packet': self.bytes_sent / self.packet_count,
            'packet_size_variance': np.var(sizes) if len(sizes) > 1 else 0,
        }

        # TCP специфичные признаки
        if tcp_flags:
            features['syn_count'] = sum(1 for f in tcp_flags if f & 0x02)
            features['ack_count'] = sum(1 for f in tcp_flags if f & 0x10)
            features['rst_count'] = sum(1 for f in tcp_flags if f & 0x04)
            features['fin_count'] = sum(1 for f in tcp_flags if f & 0x01)

        return np.array(list(features.values()))

    def is_expired(self, timeout: float = 60) -> bool:
        """Проверяет, истёк ли поток (таймаут неактивности)"""
        return (time.time() - self.end_time) > timeout


class FlowBuilder:
    """
    Сборщик потоков из сырых пакетов
    """

    def __init__(self, idle_timeout: float = 60, max_flow_packets: int = 1000):
        self.idle_timeout = idle_timeout
        self.max_flow_packets = max_flow_packets
        self.active_flows: Dict[str, NetworkFlow] = {}
        self.completed_flows: List[NetworkFlow] = []

    def _get_flow_key(self, packet: Dict) -> str:
        """Генерирует ключ потока (5-кортеж)"""
        return f"{packet['src_ip']}:{packet['src_port']}-{packet['dst_ip']}:{packet['dst_port']}-{packet['protocol']}"

    def process_packet(self, packet: Dict):
        """Обрабатывает пакет и обновляет потоки"""
        if packet is None:
            return

        # Создаём или получаем поток
        flow_key = self._get_flow_key(packet)

        if flow_key not in self.active_flows:
            # Новый поток
            flow = NetworkFlow(
                src_ip=packet['src_ip'],
                dst_ip=packet['dst_ip'],
                src_port=packet.get('src_port', 0),
                dst_port=packet.get('dst_port', 0),
                protocol=packet['protocol']
            )
            self.active_flows[flow_key] = flow

        # Добавляем пакет в поток
        flow = self.active_flows[flow_key]
        flow.add_packet(packet)

        # Если поток перерос лимит - завершаем
        if flow.packet_count >= self.max_flow_packets:
            self._complete_flow(flow_key)

    def _complete_flow(self, flow_key: str):
        """Завершает поток"""
        flow = self.active_flows.pop(flow_key)
        if flow.packet_count >= 2:  # Минимум 2 пакета для признаков
            self.completed_flows.append(flow)

    def cleanup_expired_flows(self):
        """Удаляет истекшие потоки"""
        expired_keys = [
            key for key, flow in self.active_flows.items()
            if flow.is_expired(self.idle_timeout)
        ]
        for key in expired_keys:
            self._complete_flow(key)

    def get_completed_flows(self) -> List[NetworkFlow]:
        """Возвращает все завершённые потоки и очищает список"""
        flows = self.completed_flows.copy()
        self.completed_flows.clear()
        return flows

    def get_active_flow_count(self) -> int:
        """Количество активных потоков"""
        return len(self.active_flows)