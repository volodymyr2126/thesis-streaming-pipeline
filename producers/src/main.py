import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from producers.src.kafka.admin import create_topics_if_not_exist
from producers.src.kafka.producer import sensor_producer
from producers.src.utils.config import HOST, KAFKA_TOPIC, PORT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Manage producer startup and shutdown around the FastAPI app lifetime.

    Args:
        _app: The FastAPI application instance (unused).

    Yields:
        Control back to FastAPI while the producer simulation runs.
    """
    create_topics_if_not_exist()
    sensor_producer.connect()
    simulation_task = asyncio.create_task(sensor_producer.run())

    yield

    sensor_producer.stop()
    await simulation_task
    sensor_producer.disconnect()


app = FastAPI(
    title="Air Quality Producer",
    description="Simulates air quality sensor readings and produces them to Kafka",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Return the current health state of the producer service.

    Returns:
        A dict with health flag, Kafka topic and run state.
    """
    return {
        "status": "healthy",
        "kafka_topic": KAFKA_TOPIC,
        "is_running": sensor_producer.is_running,
    }


@app.get("/stats")
async def stats():
    """Return runtime statistics for the producer.

    Returns:
        A dict with throughput and latency counters.
    """
    return sensor_producer.get_stats()


@app.get("/config")
async def config():
    """Return the configured Kafka topic.

    Returns:
        A dict containing the configured topic name.
    """
    return {
        "kafka_topic": KAFKA_TOPIC,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
