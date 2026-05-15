import logging
import time

from confluent_kafka import Producer

from producers.src.data.models import SensorReading
from producers.src.utils.config import (
    KAFKA_TOPIC,
    LATENCY_HISTORY_SIZE,
    PRODUCER_CONFIG,
    PRODUCER_MODE,
)

logger = logging.getLogger(__name__)


class SensorProducer:
    """Kafka producer that streams simulated air-quality sensor readings."""

    def __init__(self):
        """Initialise an idle sensor producer with zeroed counters."""
        self.producer: Producer | None = None
        self.is_running = False

        self.events_sent = 0
        self.events_failed = 0
        self.start_time: float | None = None
        self.latencies: list[float] = []

    def connect(self) -> None:
        """Open the underlying confluent-kafka producer.

        Returns:
            None.
        """
        self.producer = Producer(PRODUCER_CONFIG)
        logger.info(f"Connected to Kafka topic '{KAFKA_TOPIC}'")

    def disconnect(self) -> None:
        """Flush any pending messages to Kafka.

        Returns:
            None.
        """
        if self.producer:
            self.producer.flush()

    def _on_delivery(self, err, msg) -> None:
        """Record delivery outcome and update latency statistics.

        Args:
            err: A ``KafkaError`` instance on failure, otherwise ``None``.
            msg: The Kafka message whose delivery just completed.

        Returns:
            None.
        """
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
                        if len(self.latencies) > LATENCY_HISTORY_SIZE:
                            self.latencies = self.latencies[-LATENCY_HISTORY_SIZE:]

    def _send(self, reading: SensorReading) -> None:
        """Enqueue one sensor reading for asynchronous delivery to Kafka.

        Args:
            reading: The reading to publish.

        Returns:
            None.
        """
        self.producer.produce(
            topic=KAFKA_TOPIC,
            value=reading.model_dump_json().encode(),
            key=reading.sensor_id.encode(),
            headers=[("send_time", str(time.time()).encode())],
            callback=self._on_delivery,
        )
        self.producer.poll(0)

    async def run(self) -> None:
        """Run either the real-time or the replay streaming loop.

        Returns:
            None.
        """
        self.is_running = True
        self.start_time = time.time()
        if PRODUCER_MODE == "realtime":
            await self._run_realtime()
        else:
            await self._run_replay()

    async def _run_realtime(self) -> None:
        """Stream readings polled from the live OWM API.

        Returns:
            None.
        """
        from producers.src.simulation.realtime import realtime_stream

        logger.info("Starting real-time OWM mode")
        async for reading in realtime_stream():
            if not self.is_running:
                break
            self._send(reading)

    async def _run_replay(self) -> None:
        """Stream historical readings replayed from MinIO Parquet files.

        Returns:
            None.
        """
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

    def stop(self) -> None:
        """Signal the running streaming loop to stop after the next reading.

        Returns:
            None.
        """
        self.is_running = False

    def get_stats(self) -> dict:
        """Return throughput and latency statistics for the producer.

        Returns:
            A dict with running flag, sent and failed counters, current rate,
            total duration and average end-to-end latency in milliseconds.
        """
        duration = (time.time() - self.start_time) if self.start_time else 0
        avg_latency = sum(self.latencies) / len(self.latencies) if self.latencies else 0
        return {
            "is_running": self.is_running,
            "events_sent": self.events_sent,
            "events_failed": self.events_failed,
            "current_rate": (round(self.events_sent / duration, 2) if duration else 0),
            "total_duration": round(duration, 2),
            "avg_latency_ms": round(avg_latency, 2),
        }


sensor_producer = SensorProducer()
