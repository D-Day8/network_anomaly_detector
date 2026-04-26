from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict
import uvicorn
import asyncio
from loguru import logger

from ..pipeline.realtime import RealTimeAnomalyPipeline


class FlowData(BaseModel):
    """Модель данных потока для API"""
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    protocol: int
    packets: List[Dict]


class AnomalyResponse(BaseModel):
    """Ответ детектора"""
    is_anomaly: bool
    severity: str
    anomaly_score: float
    anomaly_type: Optional[str] = None
    details: Optional[Dict] = None


class DetectionAPI:
    """
    FastAPI сервер для детекции аномалий
    """

    def __init__(self, pipeline: RealTimeAnomalyPipeline):
        self.pipeline = pipeline
        self.app = FastAPI(title="Network Anomaly Detector", version="1.0.0")
        self._setup_routes()

    def _setup_routes(self):

        @self.app.get("/health")
        async def health():
            return {"status": "ok", "trained": self.pipeline.is_trained}

        @self.app.get("/stats")
        async def stats():
            return self.pipeline.get_stats()

        @self.app.post("/detect", response_model=AnomalyResponse)
        async def detect_anomaly(flow_data: FlowData):
            """
            Детекция аномалии для одного потока
            """
            if not self.pipeline.is_trained:
                raise HTTPException(status_code=503, detail="Pipeline not trained")

            # Конвертируем в формат NetworkFlow
            # (упрощённо - в реальности нужно создать временный поток)
            try:
                result = await self._detect_flow(flow_data)
                return result
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/detect/batch")
        async def detect_batch(flows: List[FlowData]):
            """
            Пакетная детекция
            """
            if not self.pipeline.is_trained:
                raise HTTPException(status_code=503, detail="Pipeline not trained")

            results = []
            for flow in flows:
                result = await self._detect_flow(flow)
                results.append(result)

            return {"results": results}

        @self.app.post("/train")
        async def train(pcap_path: str, background_tasks: BackgroundTasks):
            """
            Запуск обучения (асинхронно)
            """
            background_tasks.add_task(self.pipeline.train_offline, pcap_path)
            return {"status": "training_started", "pcap": pcap_path}

    async def _detect_flow(self, flow_data: FlowData) -> AnomalyResponse:
        """
        Внутренний метод детекции
        """
        # Создаём временный поток
        from ..capture.flow_builder import NetworkFlow

        flow = NetworkFlow(
            src_ip=flow_data.src_ip,
            dst_ip=flow_data.dst_ip,
            src_port=flow_data.src_port,
            dst_port=flow_data.dst_port,
            protocol=flow_data.protocol
        )

        # Добавляем пакеты
        for pkt in flow_data.packets:
            flow.add_packet(pkt)

        # Извлекаем признаки
        df = self.pipeline.feature_extractor.extract_flows_to_dataframe([flow])

        if len(df) == 0:
            return AnomalyResponse(
                is_anomaly=False,
                severity="LOW",
                anomaly_score=0.0,
                anomaly_type="INSUFFICIENT_DATA"
            )

        # Нормализуем
        X = self.pipeline.feature_extractor.normalize(df)

        # Детектируем
        result = self.pipeline.detector.predict_single(X[0])

        # Классифицируем тип
        anomaly_type = None
        if result['is_anomaly']:
            anomaly_type = self.pipeline._classify_anomaly(
                flow, result['anomaly_score'],
                result['quick_anomaly'], result['deep_anomaly']
            )

        return AnomalyResponse(
            is_anomaly=result['is_anomaly'],
            severity=result['severity'],
            anomaly_score=result['anomaly_score'],
            anomaly_type=anomaly_type,
            details={
                'quick_anomaly': result['quick_anomaly'],
                'deep_anomaly': result['deep_anomaly']
            }
        )

    def run(self, host: str = "0.0.0.0", port: int = 8000):
        """Запуск сервера"""
        uvicorn.run(self.app, host=host, port=port)