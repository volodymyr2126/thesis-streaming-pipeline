"""Event producer that sends events to Kafka."""
import json
import time
import uuid
import random
import asyncio
import logging
from typing import Optional, List
from confluent_kafka import Producer, KafkaException
from src.config import PRODUCER_CONFIG, KAFKA_TOPIC, EVENT_TYPES, MIN_USER_ID, MAX_USER_ID, MIN_VALUE, MAX_VALUE
from src.models import Event

logger = logging.getLogger(__name__)


class EventProducer:
    """Manages event generation and sending to Kafka."""

    def __init__(self):
        """Initialize the Kafka producer."""
        self.producer: Optional[Producer] = None
        self.is_running = False
        self.simulation_task: Optional[asyncio.Task] = None

        # Statistics
        self.events_sent = 0
        self.events_failed = 0
        self.start_time: Optional[float] = None
        self.latencies: List[float] = []

    def connect(self):
        """Connect to Kafka."""
        try:
            self.producer = Producer(PRODUCER_CONFIG)
            logger.info(f"Connected to Kafka: {PRODUCER_CONFIG['bootstrap.servers']}")
        except KafkaException as e:
            logger.error(f"Failed to connect to Kafka: {e}")
            raise

    def disconnect(self):
        """Disconnect from Kafka."""
        if self.producer:
            self.producer.flush()
            logger.info("Disconnected from Kafka")

    def _delivery_callback(self, err, msg):
        """Callback for message delivery reports."""
        if err:
            logger.error(f"Message delivery failed: {err}")
            self.events_failed += 1
        else:
            self.events_sent += 1
            # Calculate latency (time from creation to delivery)
            if msg.headers():
                for key, value in msg.headers():
                    if key == 'send_time':
                        send_time = float(value.decode())
                        latency_ms = (time.time() - send_time) * 1000
                        self.latencies.append(latency_ms)

    def generate_event(self, event_types: Optional[List[str]] = None) -> Event:
        """Generate a random event."""
        types = event_types if event_types else EVENT_TYPES

        return Event(
            event_id=str(uuid.uuid4()),
            timestamp=int(time.time() * 1000),  # milliseconds
            user_id=random.randint(MIN_USER_ID, MAX_USER_ID),
            event_type=random.choice(types),
            value=random.randint(MIN_VALUE, MAX_VALUE),
            metadata={
                "source": "producer-service",
                "version": "1.0"
            }
        )

    def send_event(self, event: Event):
        """Send an event to Kafka."""
        if not self.producer:
            raise RuntimeError("Producer not connected to Kafka")

        try:
            # Serialize event to JSON
            value = json.dumps(event.dict()).encode('utf-8')

            # Add header with send time for latency tracking
            headers = [('send_time', str(time.time()).encode())]

            # Send to Kafka
            self.producer.produce(
                topic=KAFKA_TOPIC,
                value=value,
                key=str(event.user_id).encode('utf-8'),  # Partition by user_id
                headers=headers,
                callback=self._delivery_callback
            )

            # Trigger callbacks
            self.producer.poll(0)

        except Exception as e:
            logger.error(f"Failed to send event: {e}")
            self.events_failed += 1

    async def simulate(self, rate: int, num_events: int, event_types: Optional[List[str]] = None) -> str:
        """
        Simulate event generation.

        Args:
            rate: Events per second
            num_events: Total number of events to generate
            event_types: List of event types to generate (None = all)

        Returns:
            Simulation ID
        """
        if self.is_running:
            raise RuntimeError("Simulation already running")

        simulation_id = str(uuid.uuid4())
        self.is_running = True
        self.start_time = time.time()

        estimated_duration = num_events / rate
        logger.info(f"Starting simulation {simulation_id}: {num_events} events at {rate} events/sec (~{estimated_duration:.1f}s)")

        interval = 1.0 / rate  # Time between events
        events_generated = 0

        while events_generated < num_events and self.is_running:
            loop_start = time.time()

            # Generate and send event
            event = self.generate_event(event_types)
            self.send_event(event)
            events_generated += 1

            # Sleep to maintain desired rate
            elapsed = time.time() - loop_start
            sleep_time = max(0, interval - elapsed)
            await asyncio.sleep(sleep_time)

        self.is_running = False
        actual_duration = time.time() - self.start_time
        actual_rate = self.events_sent / actual_duration if actual_duration > 0 else 0
        logger.info(f"Simulation {simulation_id} completed: {self.events_sent} events sent in {actual_duration:.2f}s (avg {actual_rate:.1f} events/sec)")

        return simulation_id

    def stop_simulation(self):
        """Stop the current simulation."""
        if self.is_running:
            self.is_running = False
            logger.info("Stopping simulation...")

    def get_stats(self) -> dict:
        """Get producer statistics."""
        total_duration = (time.time() - self.start_time) if self.start_time else 0
        current_rate = self.events_sent / total_duration if total_duration > 0 else 0
        avg_latency = sum(self.latencies) / len(self.latencies) if self.latencies else 0

        # Keep only last 1000 latencies to avoid memory issues
        if len(self.latencies) > 1000:
            self.latencies = self.latencies[-1000:]

        return {
            "is_running": self.is_running,
            "events_sent": self.events_sent,
            "events_failed": self.events_failed,
            "current_rate": round(current_rate, 2),
            "total_duration": round(total_duration, 2),
            "avg_latency_ms": round(avg_latency, 2)
        }

    def reset_stats(self):
        """Reset statistics."""
        self.events_sent = 0
        self.events_failed = 0
        self.start_time = None
        self.latencies = []


# Global producer instance
event_producer = EventProducer()
