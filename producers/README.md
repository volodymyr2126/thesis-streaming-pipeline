# Event Producer Service

FastAPI-based microservice for generating and sending events to Kafka.

## API Endpoints

### `GET /health`
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "service": "event-producer",
  "kafka_topic": "raw-events"
}
```

### `POST /simulate`
Start event generation simulation.

**Request Body:**
```json
{
  "rate": 100,
  "num_events": 10000,
  "event_types": ["click", "view", "purchase"]
}
```

**Parameters:**
- `rate`: Events per second (1-10000)
- `num_events`: Total number of events to generate (1-10,000,000)
- `event_types`: Optional list of event types (null = all types)

**Response:**
```json
{
  "status": "started",
  "message": "Simulation started: 10000 events at 100 events/sec",
  "simulation_id": "uuid",
  "rate": 100,
  "num_events": 10000,
  "estimated_duration": 100.0
}
```

### `POST /stop`
Stop the current simulation.

**Response:**
```json
{
  "status": "stopped",
  "message": "Simulation stopped",
  "final_stats": {
    "is_running": false,
    "events_sent": 1234,
    "events_failed": 0,
    "current_rate": 100.5,
    "total_duration": 12.3,
    "avg_latency_ms": 2.5
  }
}
```

### `GET /stats`
Get current producer statistics.

**Response:**
```json
{
  "status": "ok",
  "is_running": true,
  "events_sent": 5000,
  "events_failed": 0,
  "current_rate": 100.2,
  "total_duration": 49.8,
  "avg_latency_ms": 2.3
}
```

### `GET /config`
Get producer configuration.

**Response:**
```json
{
  "kafka": {
    "bootstrap_servers": "broker:29092",
    "topic": "raw-events"
  },
  "event_generation": {
    "default_rate": 10,
    "max_rate": 10000,
    "event_types": ["click", "view", "purchase", "signup", "logout"]
  }
}
```

### `GET /event-types`
Get available event types.

**Response:**
```json
{
  "event_types": ["click", "view", "purchase", "signup", "logout"]
}
```

## Example Usage

### Using Shell Scripts (Recommended)

```bash
# Health check
./scripts/health.sh

# Start simulation: 100 events/sec, 10,000 total events
./scripts/simulate.sh 100 10000

# Watch statistics in real-time
./scripts/stats.sh --watch

# Stop simulation
./scripts/stop.sh
```

See `scripts/README.md` for detailed documentation.

### Using curl

```bash
# Health check
curl http://localhost:8000/health

# Start simulation: 100 events/sec, 10,000 total events
curl -X POST http://localhost:8000/simulate \
  -H "Content-Type: application/json" \
  -d '{"rate": 100, "num_events": 10000}'

# Get statistics
curl http://localhost:8000/stats

# Stop simulation
curl -X POST http://localhost:8000/stop
```

### Using httpie

```bash
# Health check
http :8000/health

# Start simulation
http POST :8000/simulate rate:=100 duration:=30

# Get statistics
http :8000/stats

# Stop simulation
http POST :8000/stop
```

### Using Python

```python
import requests

# Start simulation: 100 events/sec, 10,000 total events
response = requests.post('http://localhost:8000/simulate', json={
    'rate': 100,
    'num_events': 10000,
    'event_types': ['click', 'purchase']
})
print(response.json())
# Output: {"status": "started", "num_events": 10000, "estimated_duration": 100.0}

# Get stats
stats = requests.get('http://localhost:8000/stats').json()
print(f"Sent: {stats['events_sent']}, Rate: {stats['current_rate']}/sec")

# Stop
requests.post('http://localhost:8000/stop')
```

## Event Schema

Each event has the following structure:

```json
{
  "event_id": "uuid",
  "timestamp": 1708626543123,
  "user_id": 42,
  "event_type": "click",
  "value": 567,
  "metadata": {
    "source": "producer-service",
    "version": "1.0"
  }
}
```

## Running Locally

```bash
# Build and start
docker-compose up --build producer

# Or run directly (requires Kafka on localhost:9092)
cd producers
pip install -r requirements.txt
python -m src.main
```

## API Documentation

Once running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
