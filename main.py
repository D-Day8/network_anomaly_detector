#!/usr/bin/env python3
"""
Network Anomaly Detector - God Level Implementation
"""

import argparse
import asyncio
import sys
from loguru import logger

from src.pipeline.realtime import RealTimeAnomalyPipeline
from src.api.server import DetectionAPI


def main():
    parser = argparse.ArgumentParser(description="Network Anomaly Detector")
    parser.add_argument("--mode", choices=["train", "detect", "api"], required=True)
    parser.add_argument("--interface", help="Network interface for capture", default=None)
    parser.add_argument("--pcap", help="PCAP file for training", default=None)
    parser.add_argument("--api-port", type=int, default=8000)

    args = parser.parse_args()

    # Настройка логирования
    logger.add("anomaly_detector.log", rotation="100 MB")

    pipeline = RealTimeAnomalyPipeline(interface=args.interface)

    if args.mode == "train":
        if not args.pcap:
            logger.error("Training mode requires --pcap")
            sys.exit(1)

        async def train():
            await pipeline.train_offline(args.pcap)
            logger.info("Training complete. Model saved.")

        asyncio.run(train())

    elif args.mode == "detect":
        async def detect():
            await pipeline.train_offline(args.pcap or "training_capture.pcap")
            await pipeline.start_realtime()

        try:
            asyncio.run(detect())
        except KeyboardInterrupt:
            logger.info("Shutting down...")

    elif args.mode == "api":
        async def start_api():
            # Сначала обучаемся (если есть PCAP)
            if args.pcap:
                await pipeline.train_offline(args.pcap)
            else:
                logger.warning("API running WITHOUT trained model. Use /train endpoint first.")

            # Запускаем API сервер
            api = DetectionAPI(pipeline)
            api.run(port=args.api_port)

        asyncio.run(start_api())

    else:
        parser.print_help()


if __name_
    _ == "__main__":
    main()