import asyncio
import threading
from queue import Queue
from scapy.all import sniff, IP, TCP, UDP, ICMP
from loguru import logger
from typing import Callable, Optional


class AsyncPacketSniffer:
    """
    Асинхронный сниффер пакетов с буферизацией
    """

    def __init__(self, interface: str = None, buffer_size: int = 10000):
        self.interface = interface
        self.packet_queue = Queue(maxsize=buffer_size)
        self.sniffer_thread: Optional[threading.Thread] = None
        self.running = False
        self.callbacks: list[Callable] = []

    def _packet_handler(self, packet):
        """Обработчик пакета для Scapy (вызывается в потоке)"""
        if not self.running:
            return

        # Извлекаем базовую информацию
        packet_info = self._extract_packet_info(packet)
        if packet_info:
            # Неблокирующая запись в очередь
            try:
                self.packet_queue.put_nowait(packet_info)
            except:
                logger.warning("Packet queue full, dropping packet")

    def _extract_packet_info(self, packet):
        """Извлекает ключевую информацию из пакета"""
        if not packet.haslayer(IP):
            return None

        ip_layer = packet[IP]
        packet_info = {
            'timestamp': packet.time,
            'src_ip': ip_layer.src,
            'dst_ip': ip_layer.dst,
            'protocol': ip_layer.proto,
            'size': len(packet),
            'flags': None,
            'src_port': None,
            'dst_port': None,
            'tcp_flags': 0
        }

        # TCP
        if packet.haslayer(TCP):
            tcp = packet[TCP]
            packet_info['src_port'] = tcp.sport
            packet_info['dst_port'] = tcp.dport
            packet_info['tcp_flags'] = tcp.flags
            packet_info['flags'] = f"TCP:{tcp.flags}"

        # UDP
        elif packet.haslayer(UDP):
            udp = packet[UDP]
            packet_info['src_port'] = udp.sport
            packet_info['dst_port'] = udp.dport
            packet_info['flags'] = "UDP"

        # ICMP
        elif packet.haslayer(ICMP):
            packet_info['flags'] = "ICMP"

        return packet_info

    def start(self):
        """Запуск сниффера в отдельном потоке"""
        self.running = True

        def sniff_thread_func():
            sniff(
                iface=self.interface,
                prn=self._packet_handler,
                store=False,
                stop_filter=lambda _: not self.running
            )

        self.sniffer_thread = threading.Thread(target=sniff_thread_func, daemon=True)
        self.sniffer_thread.start()
        logger.info(f"Sniffer started on interface {self.interface or 'default'}")

    def stop(self):
        """Остановка сниффера"""
        self.running = False
        if self.sniffer_thread:
            self.sniffer_thread.join(timeout=2)
        logger.info("Sniffer stopped")

    async def get_packet(self, timeout: float = 1.0):
        """Асинхронное получение пакета из очереди"""
        try:
            # Используем run_in_executor для блокирующей операции Queue.get
            loop = asyncio.get_event_loop()
            packet = await loop.run_in_executor(None, self.packet_queue.get, True, timeout)
            return packet
        except:
            return None