# Streaming Pipeline POC - 2-Week Implementation Plan

**Project:** Low-latency streaming data pipeline proof-of-concept
**Duration:** 2 weeks
**Goal:** Measure end-to-end latency from producer to visualization on low data volumes
**Strategy:** Build locally first, then deploy to AWS for 3-day validation

---

## 🎯 Objectives

1. ✅ Build complete streaming pipeline: Producer → Kafka → Flink → ClickHouse → Grafana
2. ✅ Measure end-to-end latency (P50, P95, P99)
3. ✅ Compare local vs cloud performance
4. ✅ Demonstrate low-latency processing on small data volumes
5. ✅ Keep cloud costs under $25 (deploy for 3 days only)
6. ✅ Document findings for thesis

---

## 🏗️ Architecture

### **Local Development Stack** (Week 1)

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Compose (Local)                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Event Producer (Python)                                    │
│         ↓                                                   │
│  Apache Kafka (1 broker, KRaft mode)                        │
│         ↓ topic: raw-events                                 │
│  Apache Flink (JobManager + TaskManager)                    │
│         ↓ 1-minute tumbling windows                         │
│         ↓ aggregate by user_id                              │
│  ClickHouse (OLAP database)                                 │
│         ↓ materialized views                                │
│  Grafana (Real-time dashboards)                             │
│         - Latency metrics (P50/P95/P99)                     │
│         - Events per second                                 │
│         - Aggregated analytics                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Cost:** $0/month

---

### **Cloud Stack** (Week 2 - 3 days only)

```
┌─────────────────────────────────────────────────────────────┐
│                         AWS Cloud                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Event Producer (ECS Fargate)                               │
│         ↓                                                   │
│  Amazon MSK (kafka.t3.small × 2 brokers)                    │
│         ↓ topic: raw-events                                 │
│  Kinesis Data Analytics for Apache Flink (1 KPU)           │
│         ↓ same Flink job as local                           │
│  ClickHouse (EC2 t3.medium, eu-central-1)                  │
│         ↓ same schema as local                              │
│  Grafana (EC2 t3.micro OR Grafana Cloud free tier)         │
│         - Same dashboards as local                          │
│         - CloudWatch integration                            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Cost:** ~$21 for 3 days (72 hours)

| Service | Instance Type | Cost/hour | 72 hours |
|---------|--------------|-----------|----------|
| MSK | kafka.t3.small × 2 | $0.1052 | $7.57 |
| Kinesis Flink | 1 KPU | $0.11 | $7.92 |
| ClickHouse | t3.medium EC2 | $0.0416 | $3.00 |
| Grafana | t3.micro EC2 | $0.0104 | $0.75 |
| Producer | Fargate (0.25 vCPU) | $0.012 | $0.86 |
| Data transfer | - | - | ~$1.00 |
| **Total** | | | **~$21.10** |

---

## 📅 Week 1: Local Development (Days 1-7)

**Goal:** Complete working pipeline running locally on Docker

### **Day 1-2: Foundation**

**Tasks:**
- [ ] Create project structure
  ```
  /producers          # Event generator service
  /flink-jobs         # Flink processing jobs
  /clickhouse         # ClickHouse schema & config
  /grafana            # Dashboard configs
  docker-compose.yml  # All services
  ```
- [ ] Update docker-compose.yml with all services
- [ ] Build simple Python event producer
  - Generate events: event_id, timestamp, user_id, event_type, value
  - Configurable rate (10/100/1000 events per second)
  - Publish to Kafka topic `raw-events`
- [ ] Test Kafka message flow
- [ ] View events in Kafka UI (http://localhost:8080)

**Deliverable:** Producer sending events to Kafka ✓

---

### **Day 3-4: Flink Stream Processing**

**Tasks:**
- [ ] Add Flink to docker-compose
  - JobManager (Web UI: http://localhost:8081)
  - TaskManager
- [ ] Write Flink job (PyFlink or Java)
  - Read from Kafka topic `raw-events`
  - Parse JSON events
  - 1-minute tumbling windows
  - Aggregate by user_id:
    - COUNT(*) as event_count
    - SUM(value) as total_value
    - AVG(value) as avg_value
  - Write to ClickHouse
- [ ] Configure Flink checkpointing (local filesystem)
- [ ] Test Flink job submission
- [ ] Monitor Flink Web UI

**Deliverable:** Flink processing events and writing to ClickHouse ✓

---

### **Day 5-6: ClickHouse & Data Storage**

**Tasks:**
- [ ] Add ClickHouse to docker-compose
- [ ] Create database schema:
  ```sql
  CREATE TABLE events_raw (
      event_id String,
      timestamp DateTime64(3),
      user_id UInt32,
      event_type String,
      value UInt32,
      processing_time DateTime64(3) DEFAULT now64()
  ) ENGINE = MergeTree()
  ORDER BY (timestamp, user_id);

  CREATE TABLE events_aggregated (
      window_start DateTime,
      user_id UInt32,
      event_count UInt64,
      total_value UInt64,
      avg_value Float64
  ) ENGINE = MergeTree()
  ORDER BY (window_start, user_id);
  ```
- [ ] Test Flink → ClickHouse writes
- [ ] Create materialized views for real-time aggregations
- [ ] Write test queries for validation

**Deliverable:** ClickHouse storing aggregated data ✓

---

### **Day 7: Grafana Dashboards & Metrics**

**Tasks:**
- [ ] Add Grafana to docker-compose
- [ ] Install ClickHouse datasource plugin
- [ ] Create dashboards:
  1. **Real-time Metrics:**
     - Events per second (gauge)
     - End-to-end latency (graph: P50, P95, P99)
     - Processing lag (Kafka lag)
  2. **Analytics:**
     - Event type distribution (pie chart)
     - Top users by event count (bar chart)
     - Windowed aggregates over time (time series)
  3. **System Health:**
     - Flink job status
     - ClickHouse query performance
- [ ] Set up auto-refresh (5-10 seconds)
- [ ] Test different event rates (10, 100, 1000/sec)

**Deliverable:** Grafana showing real-time pipeline metrics ✓

---

### **End of Week 1: Testing & Baseline Measurements**

**Tasks:**
- [ ] Run load tests at different rates:
  - 10 events/second (low)
  - 100 events/second (medium)
  - 1000 events/second (high)
- [ ] Measure for each rate:
  - End-to-end latency (producer timestamp → ClickHouse insert)
  - Flink processing time
  - ClickHouse query latency
- [ ] Document baseline metrics
- [ ] Take screenshots of Grafana dashboards
- [ ] Export sample data for analysis

**Deliverable:** Complete local pipeline with documented performance ✓

---

## 📅 Week 2: Cloud Deployment (Days 8-14)

### **Day 8-10 (Mon-Wed): Cloud Infrastructure**

**Tasks:**
- [ ] Create Terraform modules:
  - `modules/msk/` - Amazon MSK Kafka cluster
  - `modules/flink/` - Kinesis Data Analytics for Flink
  - `modules/clickhouse/` - EC2 instance with ClickHouse
  - `modules/grafana/` - EC2 instance with Grafana
  - `modules/producer/` - ECS Fargate task definition
- [ ] Configure MSK:
  - 2 brokers (kafka.t3.small)
  - VPC: Use Phase 0 private subnets
  - Create topic `raw-events` (3 partitions)
  - Enable CloudWatch metrics
- [ ] Configure Kinesis Data Analytics:
  - Runtime: Flink 1.18
  - 1 KPU (Kinesis Processing Unit)
  - Upload same Flink job JAR from local
  - Configure Kafka source (MSK)
  - Configure ClickHouse sink
- [ ] Configure ClickHouse EC2:
  - t3.medium instance
  - Same schema as local
  - Security group: Allow from Flink, Grafana
  - Attach EBS volume for data
- [ ] Configure Grafana:
  - t3.micro instance OR Grafana Cloud free tier
  - Same dashboards as local
  - ClickHouse datasource
  - CloudWatch datasource (for AWS metrics)
- [ ] Configure Producer ECS:
  - Fargate task (0.25 vCPU, 0.5 GB)
  - Same Python code as local
  - Environment variables for MSK endpoint
- [ ] Test all Terraform with `terraform plan`

**Deliverable:** Terraform ready to deploy (don't apply yet) ✓

---

### **Day 11 (Thursday Evening): Deploy to AWS**

**Timeline:**
- 6:00 PM: Start deployment
- 6:30 PM: Infrastructure provisioned
- 7:00 PM: Deploy producer
- 7:30 PM: Verify end-to-end flow
- 8:00 PM: Start baseline tests

**Tasks:**
- [ ] Run `terraform apply` in eu-central-1
- [ ] Wait for MSK cluster (15-20 minutes)
- [ ] Deploy Flink job to Kinesis Data Analytics
- [ ] Deploy producer to ECS
- [ ] Verify:
  - [ ] Producer sending to MSK
  - [ ] Flink consuming from MSK
  - [ ] ClickHouse receiving aggregates
  - [ ] Grafana showing dashboards
- [ ] Run initial smoke test (10 events/sec)

**Deliverable:** Full pipeline running on AWS ✓

---

### **Day 12-13 (Fri-Sat): Testing & Data Collection**

**Test Scenarios:**

| Scenario | Events/sec | Duration | Purpose |
|----------|-----------|----------|---------|
| Low volume | 10 | 2 hours | Baseline latency |
| Medium volume | 100 | 2 hours | Typical load |
| High volume | 1000 | 1 hour | Stress test |
| Burst test | 0 → 1000 → 0 | 30 min | Elasticity |

**Metrics to Collect:**

1. **Latency Metrics:**
   - Producer → Kafka (P50, P95, P99)
   - Kafka → Flink (P50, P95, P99)
   - Flink → ClickHouse (P50, P95, P99)
   - **End-to-end: Producer → Grafana** (P50, P95, P99)

2. **Throughput:**
   - Events produced per second
   - Events processed by Flink per second
   - ClickHouse inserts per second

3. **Resource Utilization:**
   - MSK broker CPU/memory
   - Flink KPU utilization
   - ClickHouse CPU/memory/disk

4. **Cost Tracking:**
   - Hourly cost breakdown
   - Cost per million events

**Tasks:**
- [ ] Run all test scenarios
- [ ] Export CloudWatch metrics to CSV
- [ ] Take Grafana dashboard screenshots
- [ ] Export sample data from ClickHouse
- [ ] Document any issues or anomalies
- [ ] Compare with local baseline metrics

**Deliverable:** Complete dataset for local vs cloud comparison ✓

---

### **Day 14 (Sunday Evening): Teardown & Analysis**

**Timeline:**
- 6:00 PM: Final data export
- 6:30 PM: Run `terraform destroy`
- 7:00 PM: Verify all resources deleted
- 7:30 PM: Start data analysis

**Tasks:**
- [ ] Export final metrics from CloudWatch
- [ ] Download ClickHouse data for offline analysis
- [ ] Save Grafana dashboard configs
- [ ] Run `terraform destroy` (IMPORTANT!)
- [ ] Verify in AWS Console:
  - [ ] MSK cluster deleted
  - [ ] Kinesis Flink app deleted
  - [ ] EC2 instances terminated
  - [ ] ECS tasks stopped
- [ ] Keep only:
  - [ ] VPC (Phase 0, free)
  - [ ] S3 with exported data (~$0.10)
  - [ ] CloudWatch logs (for reference, ~$0.50)
- [ ] Check final AWS bill estimate

**Deliverable:** All cloud resources destroyed, data saved ✓

---

## 📊 Success Metrics

### **Latency Goals:**

| Metric | Target | Measurement |
|--------|--------|-------------|
| End-to-end P50 | < 100ms | Producer timestamp → ClickHouse insert |
| End-to-end P95 | < 500ms | 95th percentile |
| End-to-end P99 | < 1000ms | 99th percentile |
| Flink processing | < 50ms | Window trigger → output |
| ClickHouse insert | < 10ms | Batch insert latency |

### **Comparison Points:**

| Aspect | Local | AWS Cloud |
|--------|-------|-----------|
| P50 latency | ? ms | ? ms |
| P95 latency | ? ms | ? ms |
| P99 latency | ? ms | ? ms |
| Max throughput | ? events/sec | ? events/sec |
| Setup time | ~1 week | ~3 days |
| Running cost | $0 | ~$21 (3 days) |
| Operational complexity | Low | Medium |
| Reliability | Single host | Multi-AZ, managed |
| Scalability | Limited (1 machine) | High (managed services) |

---

## 🛠️ Technology Stack

### **Core Components:**

| Component | Local | Cloud |
|-----------|-------|-------|
| **Producer** | Python 3.11 (confluent-kafka) | Same code on ECS Fargate |
| **Message Queue** | Apache Kafka 3.6 (KRaft) | Amazon MSK (Kafka 3.6) |
| **Stream Processing** | Apache Flink 1.18 (docker) | Kinesis Data Analytics (Flink 1.18) |
| **OLAP Storage** | ClickHouse 23.x (docker) | ClickHouse 23.x (EC2) |
| **Visualization** | Grafana 10.x (docker) | Grafana 10.x (EC2 or Cloud) |

### **Supporting Tools:**

- **Kafka UI:** Provectus Labs (local monitoring)
- **Flink Web UI:** Built-in (job monitoring)
- **ClickHouse Client:** CLI for queries
- **Prometheus:** Metrics collection (optional)
- **Terraform:** IaC for AWS deployment
- **Docker Compose:** Local orchestration

---

## 📦 Deliverables

### **Code Artifacts:**
- [ ] `docker-compose.yml` - Complete local stack
- [ ] `producers/` - Event generator service
- [ ] `flink-jobs/` - Flink processing job
- [ ] `clickhouse/schema.sql` - Database schema
- [ ] `grafana/dashboards/` - Dashboard JSON configs
- [ ] `infrastructure/` - Terraform modules for AWS

### **Documentation:**
- [ ] `LOCAL_SETUP.md` - How to run locally
- [ ] `CLOUD_DEPLOYMENT.md` - AWS deployment guide
- [ ] `METRICS_ANALYSIS.md` - Performance comparison
- [ ] `COST_BREAKDOWN.md` - Detailed cost analysis

### **Data:**
- [ ] Latency measurements (CSV)
- [ ] CloudWatch metrics export
- [ ] Grafana dashboard screenshots
- [ ] Sample event data

### **Thesis Sections:**
- [ ] Architecture diagrams (local vs cloud)
- [ ] Performance comparison tables
- [ ] Cost-benefit analysis
- [ ] Lessons learned
- [ ] Trade-offs discussion

---

## 🎓 Thesis Value

This POC demonstrates:

1. **Technical Skills:**
   - Real-time stream processing (Flink)
   - Distributed systems (Kafka)
   - OLAP databases (ClickHouse)
   - Cloud infrastructure (AWS)
   - Infrastructure as Code (Terraform)

2. **Analytical Skills:**
   - Performance measurement (latency analysis)
   - Cost optimization (deploy only when needed)
   - Trade-off analysis (local vs cloud)
   - Data-driven decisions

3. **Practical Insights:**
   - "Low-latency achieved with sub-100ms P50 on both local and cloud"
   - "Cloud deployment cost $21 for validation vs $0 local development"
   - "MSK provides operational benefits (HA, scalability) at 3x cost"
   - "ClickHouse enables sub-second analytical queries on streaming data"

4. **Reproducibility:**
   - Complete code in GitHub
   - Docker Compose for one-command local setup
   - Terraform for repeatable cloud deployment
   - Anyone can validate findings

---

## ⚠️ Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Cloud costs exceed budget | Set $25 AWS Budget alarm (already done in Phase 0) |
| Flink job fails | Test thoroughly locally first, have rollback plan |
| MSK takes too long to provision | Start deployment Thursday evening, not Friday |
| ClickHouse data loss | Regular snapshots to S3 |
| Forget to destroy resources | Calendar reminder, Terraform destroy checklist |
| Local machine performance | Use lightweight configs (1 Kafka broker, minimal Flink parallelism) |

---

## 📝 Daily Checklist Template

```markdown
## Day X: [Task Name]

**Start time:** [HH:MM]
**Goals:**
- [ ] Goal 1
- [ ] Goal 2

**Progress:**
- [Time] Completed: ...
- [Time] Issue: ... (resolution: ...)

**End time:** [HH:MM]
**Status:** ✅ Complete / ⚠️ Partial / ❌ Blocked

**Tomorrow:**
- [ ] Next task
```

---

## 🚀 Getting Started

**Next steps:**

1. Review this plan
2. Set up project structure
3. Start Day 1: Create docker-compose.yml
4. Build producer service
5. Test Kafka integration

**Ready to begin?** Let's start with Week 1, Day 1! 🎯
