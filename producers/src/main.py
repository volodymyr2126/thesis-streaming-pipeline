"""FastAPI application for the event producer service."""
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from src.config import KAFKA_TOPIC, EVENT_TYPES
from src.models import SimulateRequest, SimulateResponse, StatsResponse
from src.producer import event_producer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting Event Producer Service...")

    # Create topics if they don't exist
    from src.kafka_admin import create_topics_if_not_exist
    try:
        create_topics_if_not_exist()
    except Exception as e:
        logger.error(f"Failed to create topics: {e}")
        raise

    # Connect producer
    try:
        event_producer.connect()
        logger.info("Connected to Kafka successfully")
    except Exception as e:
        logger.error(f"Failed to connect to Kafka: {e}")
        raise

    yield

    logger.info("Shutting down Event Producer Service...")
    event_producer.stop_simulation()
    event_producer.disconnect()


app = FastAPI(
    title="Event Producer Service",
    description="Microservice for generating and sending events to Kafka",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "event-producer",
        "kafka_topic": KAFKA_TOPIC
    }

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Event Producer",
    }

@app.get("/help")
async def help():
    """Root endpoint with API information."""
    return {
        "service": "Event Producer",
        "version": "1.0.0",
        "endpoints": {
            "health": "GET /health",
            "simulate": "POST /simulate",
            "stop": "POST /stop",
            "stats": "GET /stats",
            "config": "GET /config"
        }
    }


@app.post("/simulate", response_model=SimulateResponse)
async def simulate_events(request: SimulateRequest, background_tasks: BackgroundTasks):
    """
    Start event simulation.

    Args:
        rate: Events per second (1-10000)
        num_events: Total number of events to generate
        event_types: List of event types to generate (optional)

    Returns:
        Simulation details
    """
    if event_producer.is_running:
        raise HTTPException(status_code=400, detail="Simulation already running. Stop it first.")

    try:
        event_producer.reset_stats()

        estimated_duration = request.num_events / request.rate

        simulation_id = await event_producer.simulate(
            rate=request.rate,
            num_events=request.num_events,
            event_types=request.event_types
        )

        return SimulateResponse(
            status="started",
            message=f"Simulation started: {request.num_events} events at {request.rate} events/sec",
            simulation_id=simulation_id,
            rate=request.rate,
            num_events=request.num_events,
            estimated_duration=round(estimated_duration, 2)
        )

    except Exception as e:
        logger.error(f"Failed to start simulation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/stop")
async def stop_simulation():
    """Stop the current simulation."""
    if not event_producer.is_running:
        raise HTTPException(status_code=400, detail="No simulation is running")

    event_producer.stop_simulation()

    return {
        "status": "stopped",
        "message": "Simulation stopped",
        "final_stats": event_producer.get_stats()
    }


@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Get current producer statistics."""
    stats = event_producer.get_stats()

    return StatsResponse(
        status="ok",
        **stats
    )


@app.get("/config")
async def get_config():
    """Get producer configuration."""
    from src.config import KAFKA_BOOTSTRAP_SERVERS, DEFAULT_EVENT_RATE, MAX_EVENT_RATE

    return {
        "kafka": {
            "bootstrap_servers": KAFKA_BOOTSTRAP_SERVERS,
            "topic": KAFKA_TOPIC
        },
        "event_generation": {
            "default_rate": DEFAULT_EVENT_RATE,
            "max_rate": MAX_EVENT_RATE,
            "event_types": EVENT_TYPES
        }
    }


@app.get("/event-types")
async def get_event_types():
    """Get available event types."""
    return {
        "event_types": EVENT_TYPES
    }


@app.get("/topic-info")
async def get_topic_info():
    """Get Kafka topic information."""
    from src.kafka_admin import get_topic_info
    try:
        info = get_topic_info()
        if info:
            return {
                "status": "ok",
                **info
            }
        else:
            return {
                "status": "not_found",
                "message": f"Topic '{KAFKA_TOPIC}' does not exist"
            }
    except Exception as e:
        logger.error(f"Failed to get topic info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
