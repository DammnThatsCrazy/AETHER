# Aether Data Lake Architecture v8.7.1

A distributed data warehouse and lakehouse backend for the Aether behavioral analytics platform. The system ingests, processes, and serves high-volume event data through a medallion architecture (Bronze / Silver / Gold), providing real-time streaming, batch ETL, GDPR governance, and ML feature serving across multi-tenant workspaces.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Technology Stack](#technology-stack)
- [Services](#services)
- [Data Architecture](#data-architecture)
- [Data Stores](#data-stores)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Development](#development)
- [Testing](#testing)
- [License](#license)

## Architecture Overview

```
                          Aether Data Lake — End-to-End Data Flow

  SDKs / Sources                Ingestion                  Streaming              Data Lake
 +----------------+       +------------------+        +--------------+      +------------------+
 | Web SDK        |       |                  |        |              |      |                  |
 | Mobile SDK     | --->  |  Ingestion API   | -----> |    Kafka     | ---> |  Bronze (Raw)    |
 | Server SDK     | HTTP  |  (validate,      |  sink  |  (real-time  |      |  JSONL + gzip    |
 | Webhooks       | POST  |   dedup,         |        |   stream)    |      |  S3 partitioned  |
 | Web3 Events    |       |   enrich)        |        +--------------+      +--------+---------+
 |  (7 VMs, DeFi) |       |                  |
 +----------------+       +--------+---------+              |                        |
                                   |                        |                   ETL Scheduler
                                   |                        v                        |
                                   |               +--------------+          +-------v---------+
                                   +-------------> |  ClickHouse  |          |  Silver (Clean)  |
                                   |     sink      |  (OLAP)      |          |  Parquet+snappy  |
                                   |               +--------------+          |  deduplicated,   |
                                   |                                         |  sessionized     |
                                   +-------------> +--------------+          +--------+---------+
                                         sink      |    Redis     |                   |
                                                   |  (counters)  |              Aggregation
                                                   +--------------+                   |
                                                                             +--------v---------+
                                         Serving & Query                     |  Gold (Metrics)  |
                                    +-------------------+                    |  Parquet + zstd   |
                                    |  Data Lake API    | <------------------+  daily KPIs,     |
                                    |  /catalog         |                    |  funnels,        |
                                    |  /etl/status      |                    |  attribution,    |
                                    |  /quality/report  |                    |  ML features     |
                                    |  /governance      |                    +------------------+
                                    |  /metrics         |
                                    +-------------------+
```

## Technology Stack

### Dual Stack

| Layer               | Technology            | Purpose                                    |
|---------------------|-----------------------|--------------------------------------------|
| **API Services**    | TypeScript / Node.js  | Ingestion API, Data Lake management, HTTP routing |
| **Data Processing** | TypeScript + planned Python | ETL pipelines, ML feature computation, batch transforms |
| **Build System**    | npm workspaces        | Monorepo package management                |
| **Tooling**         | tsx, vitest, ESLint   | Hot reload, testing, linting               |

### Runtime Requirements

- Node.js >= 20.0.0
- TypeScript 5.4+
- Docker and Docker Compose (for infrastructure services)

## Services

The backend is organized as a monorepo with shared packages and independent services.

### Core Services

| Service            | Port   | Description                                                        |
|--------------------|--------|--------------------------------------------------------------------|
| **Ingestion**      | `3001` | High-throughput HTTP event ingestion with auth, rate limiting, dedup, enrichment, and multi-sink routing (Kafka, S3, ClickHouse, Redis) |
| **Data Lake**      | `8082` | Medallion tier storage management, ETL orchestration, compaction, quality checks, streaming bridge, GDPR governance, lifecycle management, and monitoring |

### Shared Packages

| Package             | Description                                              |
|---------------------|----------------------------------------------------------|
| `@aether/common`   | Shared configuration loaders, utility functions, hashing |
| `@aether/logger`   | Structured logging (namespace-scoped)                    |
| `@aether/auth`     | API key validation, rate limiting                        |
| `@aether/cache`    | In-memory and Redis cache, deduplication filters         |
| `@aether/events`   | Event routing, sink abstractions (Kafka, S3, ClickHouse, Redis) |

### Planned Microservices

The platform is designed to expand to 13+ microservices:

| Service           | Purpose                                               |
|-------------------|-------------------------------------------------------|
| **Admin**         | Workspace and project management                      |
| **Agent**         | Autonomous AI-driven analytics agents                 |
| **Analytics**     | Query engine and dashboard data API                   |
| **Campaign**      | Multi-touch attribution and campaign analytics        |
| **Consent**       | Privacy consent management and enforcement            |
| **Gateway**       | API gateway, routing, and service mesh                |
| **Identity**      | Identity graph resolution and cross-device stitching  |
| **ML Serving**    | Real-time model inference (churn, LTV, intent)        |
| **Notification**  | Alert delivery (email, Slack, webhooks)               |

## Data Architecture

### Medallion Lakehouse Model

All event data flows through three progressively refined storage tiers:

```
+------------------------------------------------------------------+
|                        BRONZE (Raw)                               |
|  Format:     JSONL + gzip                                        |
|  Bucket:     aether-data-lake-bronze                             |
|  Partition:  project_id / year / month / day / hour              |
|  Retention:  90 days                                             |
|  Compaction: 128 MB target                                       |
|  Purpose:    Immutable append-only event archive (incl. Web3)    |
+------------------------------+-----------------------------------+
                               |  ETL: validate, dedup, extract,
                               |       sessionize, resolve identity,
                               |       parse Web3 events (7 VMs)
                               v
+------------------------------------------------------------------+
|                        SILVER (Clean)                             |
|  Format:     Parquet + snappy                                    |
|  Bucket:     aether-data-lake-silver                             |
|  Partition:  project_id / event_type / year / month / day        |
|  Retention:  365 days                                            |
|  Compaction: 256 MB target                                       |
|  Tables:     silver_events, silver_sessions                      |
|  Purpose:    Deduplicated, typed, sessionized events + Web3 txns |
+------------------------------+-----------------------------------+
                               |  ETL: aggregate, compute features,
                               |       build attribution, funnels,
                               |       Web3 activity aggregation
                               v
+------------------------------------------------------------------+
|                        GOLD (Metrics)                             |
|  Format:     Parquet + zstd                                      |
|  Bucket:     aether-data-lake-gold                               |
|  Partition:  project_id / year / month / day                     |
|  Retention:  730 days (2 years)                                  |
|  Tables:     gold_daily_metrics, gold_funnel_metrics,            |
|              gold_attribution, gold_user_features                 |
|  Purpose:    Pre-aggregated KPIs, ML features, dashboard data    |
+------------------------------------------------------------------+
```

### Table Definitions

**Bronze Tier**
- `bronze_events` -- Raw ingested events from all SDKs. 40+ columns covering event identifiers, timestamps, page context, device info, UTM/campaign parameters, geo enrichment, consent flags, and SDK metadata.

**Silver Tier**
- `silver_events` -- Cleaned, deduplicated events with identity resolution, extracted typed properties (conversions, web vitals, Web3 transactions, A/B experiments), and data quality flags.
- `silver_sessions` -- Sessionized aggregates with engagement metrics (event counts, page views, revenue, bounce detection), attribution, device/geo context, and performance averages.

**Gold Tier**
- `gold_daily_metrics` -- Daily project KPIs: traffic, engagement, conversions, revenue, web performance (Core Web Vitals), errors, Web3 activity, and bot detection rates.
- `gold_funnel_metrics` -- Funnel step conversion analysis with drop-off tracking and time-to-complete.
- `gold_attribution` -- Multi-touch campaign attribution using first-touch, last-touch, linear, and Shapley value models.
- `gold_user_features` -- Pre-computed ML feature vectors (behavioral, conversion, Web3, acquisition) with cached model predictions (churn probability, 30d/365d LTV).

## Data Stores

| Store              | Role                                                             |
|--------------------|------------------------------------------------------------------|
| **Amazon S3**      | Primary data lake storage (Bronze JSONL, Silver/Gold Parquet)    |
| **ClickHouse**     | OLAP analytics engine for real-time queries over event data      |
| **Kafka**          | Event streaming backbone (real-time ingestion to Bronze via streaming bridge) |
| **Redis**          | Real-time counters, deduplication cache, session state           |
| **TimescaleDB**    | Time-series event storage (planned)                              |
| **Neptune**        | Identity graph storage (planned)                                 |
| **DynamoDB**       | API key store, configuration metadata (planned)                  |
| **OpenSearch**     | Full-text search and vector embeddings (planned)                 |

## Features

### Multi-Tenant Isolation
- All data is partitioned by `project_id` at every tier
- API key authentication scopes access to a single project/organization
- Rate limiting is applied per API key with configurable thresholds

### Event Sourcing and Ingestion
- HTTP batch and single-event ingestion endpoints (`/v1/batch`, `/v1/track`, `/v1/page`, `/v1/identify`, `/v1/conversion`)
- Schema validation, deduplication (configurable window), geo/UA enrichment, IP anonymization
- Multi-sink routing: events are simultaneously written to Kafka, ClickHouse, S3, and Redis
- Dead letter queue for unprocessable messages

### Real-Time + Batch Processing
- **Streaming Bridge**: Kafka consumer writes micro-batches to Bronze S3 with exactly-once semantics, backpressure management, and configurable flush intervals
- **ETL Scheduler**: Periodic Bronze-to-Silver and Silver-to-Gold transformations with concurrency control, checkpointing, and idempotency
- **Backfill Manager**: On-demand reprocessing of historical partitions

### Data Quality
- Automated quality checks across all tiers: completeness, freshness, volume anomalies, schema compliance, uniqueness, and distribution monitoring
- Severity levels (critical, warning, info) with reporting and failure tracking

### Data Governance
- **GDPR Compliance**: Data subject requests (deletion, access, portability, rectification, restriction) with audit trails and 30-day deadline enforcement
- **Schema Evolution**: Managed schema migrations with versioning
- **Lifecycle Management**: Automated S3 storage class transitions (Standard -> IA -> Glacier), partition pruning, retention enforcement, and legal hold support

### Monitoring and Observability
- Prometheus-compatible metric export (`/metrics`)
- Pipeline health tracking with SLA definitions (latency, completeness, freshness, uptime)
- Alert system with severity levels (info, warning, critical, page)
- Data freshness and throughput monitoring

### Compaction
- Background compaction service merges small files within partitions to meet target sizes (128 MB Bronze, 256 MB Silver, 512 MB Gold)

## Prerequisites

- **Node.js** >= 20.0.0
- **npm** >= 9.0.0
- **Docker** and **Docker Compose** (for Kafka, ClickHouse, Redis)

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd aether-datalake-backend

# Install dependencies
npm install

# Copy environment configuration
cp .env.example .env

# Build all packages and services
npm run build
```

## Quick Start

### 1. Start Infrastructure

```bash
# Start Kafka, ClickHouse, Redis, and Kafka UI
./scripts/dev.sh docker:up
```

This starts:
- **Kafka** on port `9092` (event streaming)
- **ClickHouse** on port `8123` (OLAP analytics)
- **Redis** on port `6379` (cache/counters)
- **Kafka UI** on port `8080` (development tool)

### 2. Start the Ingestion Service

```bash
# Development mode with hot reload
npm run dev:ingestion
```

The ingestion API will be available at `http://localhost:3001`.

### 3. Start the Data Lake Service

```bash
# Development mode with hot reload
npm run dev:datalake
```

The data lake API will be available at `http://localhost:8082`.

### 4. Send a Smoke Test

```bash
./scripts/dev.sh smoke
```

This sends a test event batch using the development API key (`ak_dev_aether_test_key_12345678`).

### 5. Check Health

```bash
# Ingestion health
curl http://localhost:3001/health | jq .

# Data Lake health
curl http://localhost:8082/health | jq .
```

## Configuration

### Environment Variables

Configuration is managed through environment variables. See `.env.example` for the full list.

#### Service

| Variable       | Default       | Description                     |
|----------------|---------------|---------------------------------|
| `NODE_ENV`     | `development` | Runtime environment             |
| `PORT`         | `3001`        | Ingestion service port          |
| `HOST`         | `0.0.0.0`    | Bind address                    |
| `LOG_LEVEL`    | `debug`       | Log verbosity                   |

#### Kafka

| Variable              | Default               | Description            |
|-----------------------|-----------------------|------------------------|
| `KAFKA_ENABLED`       | `true`                | Enable Kafka sink      |
| `KAFKA_BROKERS`       | `localhost:9092`      | Broker connection list |
| `KAFKA_EVENTS_TOPIC`  | `aether.events.raw`   | Raw events topic       |

#### S3 Data Lake

| Variable            | Default                      | Description              |
|---------------------|------------------------------|--------------------------|
| `S3_ENABLED`        | `false`                      | Enable S3 sink           |
| `S3_BRONZE_BUCKET`  | `aether-data-lake-bronze`    | Bronze tier bucket       |
| `S3_SILVER_BUCKET`  | `aether-data-lake-silver`    | Silver tier bucket       |
| `S3_GOLD_BUCKET`    | `aether-data-lake-gold`      | Gold tier bucket         |
| `AWS_REGION`        | `us-east-1`                  | AWS region               |

#### ClickHouse

| Variable            | Default     | Description             |
|---------------------|-------------|-------------------------|
| `CLICKHOUSE_ENABLED`| `false`     | Enable ClickHouse sink  |
| `CLICKHOUSE_HOST`   | `localhost` | ClickHouse server host  |
| `CLICKHOUSE_PORT`   | `8123`      | ClickHouse HTTP port    |
| `CLICKHOUSE_DB`     | `aether`    | Database name           |

#### Redis

| Variable        | Default                  | Description         |
|-----------------|--------------------------|---------------------|
| `REDIS_ENABLED` | `true`                   | Enable Redis sink   |
| `REDIS_URL`     | `redis://localhost:6379` | Redis connection    |

#### Data Lake Service

| Variable                           | Default    | Description                          |
|------------------------------------|------------|--------------------------------------|
| `DATALAKE_PORT`                    | `8082`     | Data lake service port               |
| `DATALAKE_SCHEDULER`               | `true`     | Enable ETL scheduler                 |
| `DATALAKE_COMPACTION`              | `true`     | Enable background compaction         |
| `DATALAKE_QUALITY`                 | `true`     | Enable quality checks                |
| `DATALAKE_STREAMING`               | `true`     | Enable Kafka streaming bridge        |
| `DATALAKE_MONITORING`              | `true`     | Enable monitoring subsystem          |
| `DATALAKE_GOVERNANCE`              | `true`     | Enable GDPR governance               |
| `DATALAKE_SCHEDULER_POLL_MS`       | `300000`   | ETL poll interval (5 min)            |
| `DATALAKE_COMPACTION_INTERVAL_MS`  | `3600000`  | Compaction interval (1 hr)           |
| `DATALAKE_QUALITY_INTERVAL_MS`     | `900000`   | Quality check interval (15 min)      |
| `DATALAKE_LIFECYCLE_INTERVAL_MS`   | `86400000` | Lifecycle enforcement interval (24 hr) |
| `DATALAKE_MAX_CONCURRENCY`         | `4`        | Max concurrent ETL jobs              |

#### Processing

| Variable              | Default  | Description                          |
|-----------------------|----------|--------------------------------------|
| `MAX_BATCH_SIZE`      | `500`    | Max events per batch request         |
| `MAX_EVENT_SIZE_BYTES`| `32768`  | Max single event size (32 KB)        |
| `ENRICH_GEO`         | `true`   | Enable geo IP enrichment             |
| `ENRICH_UA`          | `true`   | Enable user agent parsing            |
| `ANONYMIZE_IP`       | `true`   | Anonymize IP addresses               |
| `DEDUP_WINDOW_MS`    | `300000` | Deduplication window (5 min)         |

## API Reference

### Ingestion Service (`localhost:3001`)

| Method | Path             | Auth     | Description                  |
|--------|------------------|----------|------------------------------|
| POST   | `/v1/batch`      | Required | Batch event ingestion        |
| POST   | `/v1/track`      | Required | Single track event           |
| POST   | `/v1/page`       | Required | Single page view event       |
| POST   | `/v1/identify`   | Required | Single identify event        |
| POST   | `/v1/conversion` | Required | Single conversion event      |
| GET    | `/health`        | Public   | Health check                 |
| GET    | `/metrics`       | Public   | Prometheus metrics           |
| GET    | `/status`        | Public   | Service status               |

### Data Lake Service (`localhost:8082`)

| Method | Path                          | Description                           |
|--------|-------------------------------|---------------------------------------|
| GET    | `/health`                     | Full health check with subsystem status |
| GET    | `/api/v1/catalog`             | List data catalog (filter by `?tier=` or `?search=`) |
| GET    | `/api/v1/catalog/lineage`     | Data lineage graph (`?table=`)        |
| GET    | `/api/v1/schema/ddl`          | Generate full ClickHouse DDL          |
| GET    | `/api/v1/etl/status`          | ETL job status and summary            |
| GET    | `/api/v1/quality/report`      | Quality check report                  |
| GET    | `/api/v1/quality/checks`      | List registered quality checks        |
| GET    | `/api/v1/compaction/stats`    | Compaction statistics                 |
| GET    | `/api/v1/governance/compliance` | GDPR compliance summary             |
| GET    | `/api/v1/governance/requests` | Data subject requests                 |
| GET    | `/api/v1/governance/lifecycle`| Lifecycle rules and S3 policy         |
| GET    | `/api/v1/streaming/status`    | Streaming bridge status               |
| GET    | `/api/v1/backfill/jobs`       | Backfill job listing                  |
| GET    | `/api/v1/monitoring/health`   | Monitoring health summary             |
| GET    | `/api/v1/monitoring/alerts`   | Active alerts                         |
| GET    | `/api/v1/monitoring/sla`      | SLA compliance report                 |
| GET    | `/metrics`                    | Prometheus-compatible metrics          |

## Development

### Project Structure

```
aether-datalake-backend/
  packages/
    common/              Shared utilities and config loaders
    logger/              Structured logging
    auth/                API key validation, rate limiting
    cache/               Cache and deduplication
    events/              Event routing and sink abstractions
  services/
    ingestion/           HTTP event ingestion service
      src/
        index.ts         Server bootstrap
        routes/          HTTP route handlers (batch, track, health)
        middleware/       Auth, rate limiting, CORS
        validators/      Event schema validation
        enrichers/       Geo, UA enrichment
        metrics.ts       Prometheus metrics
    data-lake/           Data lake management service
      src/
        index.ts         Service orchestrator
        storage/         S3 storage layer (read/write/lifecycle)
        schema/          Table definitions, DDL generation
        catalog/         Data catalog and lineage tracking
        etl/             ETL pipelines and scheduler
        quality/         Automated quality checks
        compaction/      File compaction service
        governance/      Schema evolution, GDPR, lifecycle
        streaming/       Kafka streaming bridge, backfill
        monitoring/      Health, SLA, alerts, Prometheus export
        query/           Analytics query helpers
  docker/
    docker-compose.yml   Development infrastructure stack
    Dockerfile.ingestion Ingestion service container image
  scripts/
    dev.sh               Development CLI (dev, test, docker, smoke)
  tests/
    unit/                Unit tests
    integration/         Integration tests
    fixtures/            Test data
```

### CLI Commands

```bash
./scripts/dev.sh dev              # Start ingestion in dev mode (hot reload)
./scripts/dev.sh test             # Run unit tests
./scripts/dev.sh test:watch       # Run tests in watch mode
./scripts/dev.sh test:integration # Run integration tests
./scripts/dev.sh build            # Compile TypeScript
./scripts/dev.sh lint             # Run ESLint
./scripts/dev.sh typecheck        # Type check
./scripts/dev.sh docker:up        # Start full Docker stack
./scripts/dev.sh docker:down      # Stop Docker stack
./scripts/dev.sh docker:build     # Build ingestion Docker image
./scripts/dev.sh smoke            # Send a smoke test batch
./scripts/dev.sh health           # Check health endpoint
./scripts/dev.sh metrics          # Check metrics endpoint
./scripts/dev.sh clean            # Remove build artifacts
```

### npm Scripts

```bash
npm run build            # Build all packages (tsc -b)
npm run dev:ingestion    # Start ingestion service with hot reload
npm run dev:datalake     # Start data lake service with hot reload
npm test                 # Run unit tests (vitest)
npm run test:integration # Run integration tests
npm run lint             # ESLint
npm run typecheck        # Type check without emitting
npm run clean            # Remove build artifacts
```

## Testing

```bash
# Unit tests
npm test

# Watch mode
npm run test:watch

# Integration tests (requires Docker stack running)
npm run test:integration
```

## License

Proprietary -- Copyright (c) 2024 Aether Analytics. All rights reserved.

See [LICENSE](./aether-datalake-backend/LICENSE) for details.
