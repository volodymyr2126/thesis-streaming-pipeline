"""Air quality producer service — starts simulation automatically on startup."""
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from producers.src.utils.config import KAFKA_TOPIC
from producers.src.kafka.admin import create_topics_if_not_exist
from producers.src.kafka.producer import sensor_producer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
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
    return {
        "status": "healthy",
        "kafka_topic": KAFKA_TOPIC,
        "is_running": sensor_producer.is_running,
    }


@app.get("/stats")
async def stats():
    return sensor_producer.get_stats()


@app.get("/config")
async def config():
    return {
        "kafka_topic": KAFKA_TOPIC,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
