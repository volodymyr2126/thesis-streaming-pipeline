# Producer Control Scripts

Convenient shell scripts to control the event producer service.

## Available Scripts

### `./simulate.sh <rate> <num_events> [event_types]`

Start event generation simulation.

**Arguments:**
- `rate`: Events per second (default: 10)
- `num_events`: Total number of events to generate (default: 100)
- `event_types`: Optional comma-separated list of event types (default: all)

**Examples:**

```bash
# Generate 10,000 events at 100 events/sec
./simulate.sh 100 10000

# Generate 1,000 events at 50 events/sec
./simulate.sh 50 1000

# Generate 5,000 purchase and click events at 200 events/sec
./simulate.sh 200 5000 "purchase,click"

# Use defaults (10 events/sec, 100 events)
./simulate.sh
```

---

### `./stats.sh [--watch]`

Get current producer statistics.

**Options:**
- No args: Show stats once
- `--watch` or `-w`: Continuously update stats every 2 seconds

**Examples:**

```bash
# Show current stats
./stats.sh

# Watch stats in real-time (Ctrl+C to exit)
./stats.sh --watch
```

**Output:**
```
Status:         🟢 Running
Events sent:    5,234
Events failed:  0
Current rate:   100.12 events/sec
Duration:       52.34 seconds
Avg latency:    2.45 ms
```

---

### `./stop.sh`

Stop the current simulation.

**Example:**

```bash
./stop.sh
```

**Output:**
```
🛑 Stopping simulation...
✅ Simulation stopped!

📊 Final Statistics:
  Events sent:    10,000
  Events failed:  0
  Total duration: 100.23 seconds
  Avg rate:       99.77 events/sec
  Avg latency:    2.31 ms
```

---

### `./clear-topic.sh [topic_name]`

Clear all messages from Kafka topic by deleting and recreating it.

**Arguments:**
- `topic_name`: Topic to clear (default: raw-events)

**Example:**

```bash
# Clear default topic (raw-events)
./clear-topic.sh

# Clear specific topic
./clear-topic.sh my-events
```

**What it does:**
1. Deletes the topic
2. Recreates it with same configuration (3 partitions, 1 replica)
3. Resets consumer offsets to 0

**Use when:**
- Starting fresh test run
- Want to reset message count to zero
- Need clean state for duplicate testing

---

### `./purge-topic.sh [topic_name]`

Purge messages from Kafka topic without deleting it.

**Arguments:**
- `topic_name`: Topic to purge (default: raw-events)

**Example:**

```bash
# Purge default topic
./purge-topic.sh

# Purge specific topic
./purge-topic.sh my-events
```

**What it does:**
1. Temporarily sets retention to 1ms
2. Waits for messages to expire
3. Restores retention to 7 days

**Use when:**
- Want to keep consumer group offsets
- Don't want to recreate topic
- Prefer non-destructive cleanup

---

### `./health.sh`

Check producer health, configuration, and topic status.

**Example:**

```bash
./health.sh
```

**Output:**
```
🏥 Producer Health Check
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📍 Endpoint: http://localhost:8000
✅ Status: Healthy

⚙️  Configuration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Kafka brokers:  broker:29092
Kafka topic:    raw-events
Default rate:   10 events/sec
Max rate:       10000 events/sec
Event types:    click, view, purchase, signup, logout

📋 Topic Info
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Topic:          raw-events
Partitions:     3

✅ All systems operational!
```

---

## Common Workflows

### Fresh Test Run

```bash
# 1. Clear topic from previous test
./clear-topic.sh

# 2. Start new simulation
./simulate.sh 100 10000

# 3. Watch progress
./stats.sh --watch

# 4. Verify count in Kafka UI
open http://localhost:8080
# Should show exactly 10,000 messages
```

### Testing Different Loads

```bash
# Low load test (10 events/sec, 1,000 events)
./simulate.sh 10 1000
./stats.sh --watch

# Medium load test (100 events/sec, 10,000 events)
./simulate.sh 100 10000
./stats.sh --watch

# High load test (1,000 events/sec, 100,000 events)
./simulate.sh 1000 100000
./stats.sh --watch
```

### Duplicate Detection Test

```bash
# Generate exactly 10,000 events
./simulate.sh 100 10000

# Check final count
./stats.sh
# Should show: Events sent: 10,000

# Verify in Kafka (should be exactly 10,000 messages)
# Go to http://localhost:8080 → Topics → raw-events
```

### Latency Measurement

```bash
# Start simulation
./simulate.sh 100 50000

# Watch avg latency in real-time
./stats.sh --watch

# Note: avg_latency_ms shows producer→Kafka latency
```

### Stop Mid-Simulation

```bash
# Start long-running simulation
./simulate.sh 100 1000000

# Stop after a few seconds
./stop.sh

# Check how many were sent
./stats.sh
```

---

## Environment Variables

All scripts respect the `PRODUCER_URL` environment variable:

```bash
# Default (local)
export PRODUCER_URL="http://localhost:8000"

# Custom port
export PRODUCER_URL="http://localhost:9000"
./simulate.sh 100 1000

# Remote producer (cloud)
export PRODUCER_URL="http://producer.example.com"
./health.sh
```

---

## Tips

1. **Always check health first:**
   ```bash
   ./health.sh
   ```

2. **Watch stats during simulation:**
   ```bash
   ./simulate.sh 100 10000
   ./stats.sh --watch  # In another terminal
   ```

3. **Precise event counts for testing:**
   ```bash
   # Want exactly 5,000 events? Use num_events!
   ./simulate.sh 100 5000
   # Much better than: rate=100, duration=50 (might be 4,998 or 5,002)
   ```

4. **Test specific event types:**
   ```bash
   # Only purchases
   ./simulate.sh 50 1000 "purchase"

   # Clicks and views
   ./simulate.sh 200 10000 "click,view"
   ```

---

## Troubleshooting

**"Connection refused":**
```bash
# Check if producer is running
docker ps | grep producer

# Check producer logs
docker logs event-producer
```

**"command not found: python3":**
```bash
# Scripts use python3 for JSON parsing
# On some systems, try: python instead of python3
# Or install: sudo apt-get install python3
```

**Scripts not executable:**
```bash
# Make scripts executable
chmod +x scripts/*.sh
```

---

## For Windows Users

Use Git Bash or WSL, or create batch file equivalents:

```batch
@echo off
REM simulate.bat
curl -X POST http://localhost:8000/simulate ^
  -H "Content-Type: application/json" ^
  -d "{\"rate\": %1, \"num_events\": %2}"
```
