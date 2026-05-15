import time
import asyncio
import logging
from typing import Optional

from confluent_kafka import Producer

from producers.src.utils.config import PRODUCER_CONFIG, KAFKA_TOPIC, PRODUCER_MODE
from producers.src.data.models import SensorReading

logger = logging.getLogger(__name__)


class SensorProducer:
    def __init__(self):
        self.producer: Optional[Producer] = None
        self.is_running = False

        self.events_sent = 0
        self.events_failed = 0
        self.start_time: Optional[float] = None
        self.latencies: list[float] = []

    def connect(self):
        self.producer = Producer(PRODUCER_CONFIG)
        logger.info(f"Connected to Kafka topic '{KAFKA_TOPIC}'")

    def disconnect(self):
        if self.producer:
            self.producer.flush()

    def _on_delivery(self, err, msg):
        if err:
            logger.error(f"Delivery failed: {err}")
            self.events_failed += 1
        else:
            self.events_sent += 1
            if msg.headers():
                for key, value in msg.headers():
                    if key == "send_time":
                        latency_ms = (time.time() - float(value.decode())) * 1000
                        self.latencies.append(latency_ms)
                        if len(self.latencies) > 1000:
                            self.latencies = self.latencies[-1000:]

    def _send(self, reading: SensorReading):
        self.producer.produce(
            topic=KAFKA_TOPIC,
            value=reading.model_dump_json().encode(),
            key=reading.sensor_id.encode(),
            headers=[("send_time", str(time.time()).encode())],
            callback=self._on_delivery,
        )
        self.producer.poll(0)

    async def run(self):
        self.is_running = True
        self.start_time = time.time()
        if PRODUCER_MODE == "realtime":
            await self._run_realtime()
        else:
            await self._run_replay()

    async def _run_realtime(self):
        from producers.src.simulation.realtime import realtime_stream
        logger.info("Starting real-time OWM mode")
        async for reading in realtime_stream():
            if not self.is_running:
                break
            self._send(reading)

    async def _run_replay(self):
        from producers.src.simulation.replay import replay_stream
        logger.info("Starting historical replay mode")
        count = 0
        async for reading in replay_stream():
            if not self.is_running:
                break
            self._send(reading)
            count += 1

        if count == 0:
            logger.warning("No historical data found in MinIO — nothing to replay")

    def stop(self):
        self.is_running = False

    def get_stats(self) -> dict:
        duration = (time.time() - self.start_time) if self.start_time else 0
        avg_latency = sum(self.latencies) / len(self.latencies) if self.latencies else 0
        return {
            "is_running": self.is_running,
            "events_sent": self.events_sent,
            "events_failed": self.events_failed,
            "current_rate": round(self.events_sent / duration, 2) if duration else 0,
            "total_duration": round(duration, 2),
            "avg_latency_ms": round(avg_latency, 2),
        }


sensor_producer = SensorProducer()
