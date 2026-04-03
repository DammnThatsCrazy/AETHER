# Aether Data Ingestion Layer v8.7.0

High-throughput event ingestion pipeline for the Aether behavioral analytics platform. Receives, validates, enriches, and routes client-side events from the Aether SDK to downstream storage and streaming sinks.

## Tech Stack

- **Language:** TypeScript 5.4, targeting ES2022
- **Runtime:** Node.js >= 20
- **Module System:** NodeNext (ESM)
- **Monorepo:** npm workspaces with 5 shared packages and 1 service
- **Testing:** Vitest
- **Linting:** ESLint 9
- **Containerization:** Multi-stage Docker (node:20-slim)

## Architecture

```
                          Aether Data Ingestion Layer
                          ==========================

  +-----------+       +---------------------+       +---------------------+
  |           |       |                     |       |                     |
  | Aether SDK| ----> |  Ingestion Server   | ----> |  Enrichment Pipeline|
  | (Browser) | POST  |  :3001              |       |  GeoIP / UA / IP    |
  |           | /v1/  |  Auth + Validate    |       |  Bot Detection      |
  +-----------+ batch +---------------------+       +---------------------+
                              |                              |
                              v                              v
                      +-------+--------+           +---------+---------+
                      | Rate Limiting  |           | Dead Letter Queue |
                      | Deduplication  |           | (failed events)   |
                      +-------+--------+           +-------------------+
                              |
              +---------------+---------------+---------------+
              |               |               |               |
              v               v               v               v
        +-----------+   +-----------+   +-----------+   +-----------+
        |   Kafka   |   |    S3     |   |ClickHouse |   |   Redis   |
        | Streaming |   | Data Lake |   | Analytics |   | Real-time |
        +-----------+   +-----------+   +-----------+   +-----------+
```

## Packages

All packages live under `packages/` and are published under the `@aether/` scope as private workspace dependencies.

| Package | Name | Description |
|---------|------|-------------|
| **common** | `@aether/common` | Shared type definitions, utility functions (ID generation, IP anonymization, hashing, partition keys), and error classes (`AetherError`, `ValidationError`, `AuthenticationError`, `RateLimitError`, `PayloadTooLargeError`) |
| **auth** | `@aether/auth` | API key authentication, project resolution, permission enforcement, and per-key rate limit configuration |
| **cache** | `@aether/cache` | Redis-backed caching layer for API key lookups, deduplication windows, and real-time counters |
| **events** | `@aether/events` | Event schema validation, batch payload parsing, and event type definitions matching the SDK `BaseEvent` schema |
| **logger** | `@aether/logger` | Pino-style structured JSON logging with log levels (`debug`, `info`, `warn`, `error`, `fatal`), request context propagation, and child logger support |

### Services

| Service | Name | Description |
|---------|------|-------------|
| **ingestion** | `@aether/ingestion` | The HTTP ingestion server. Receives batched events, authenticates, validates, enriches, and fans out to configured sinks |

## Features

- **Event Validation** -- Schema validation against SDK `BaseEvent` types with 12 supported event types (`track`, `page`, `screen`, `identify`, `conversion`, `wallet`, `transaction`, `error`, `performance`, `experiment`, `consent`, `heartbeat`)
- **Server-Side Enrichment** -- GeoIP resolution (MaxMind GeoLite2), user agent parsing, IP anonymization (last-octet zeroing), and bot probability scoring
- **API Key Authentication** -- Project-scoped API keys with granular permissions (`read`, `write`, `admin`), allowed event types, allowed origins, and per-key rate limits
- **Redis Caching** -- API key lookup caching, event deduplication (configurable 5-minute window), and real-time counters with TTL
- **Structured Logging** -- JSON-formatted log output with service name, request ID, project ID, and trace ID context propagation
- **Multi-Sink Fan-Out** -- Simultaneous delivery to Kafka (streaming), S3 (data lake), ClickHouse (analytics), and Redis (real-time)
- **Rate Limiting** -- Configurable per-window rate limiting keyed by API key, IP, or combined
- **Dead Letter Queue** -- Failed events are captured with error context for later reprocessing
- **Batch Processing** -- Accepts batched event payloads (up to 500 events per batch, 32 KB per event)
- **CORS Support** -- Configurable allowed origins, methods, and headers for cross-origin SDK requests
- **Health Checks** -- `/health` endpoint reporting component-level status for all sinks and dependencies
- **Metrics** -- Prometheus-compatible metrics on a dedicated port (default 9090): events received/processed/failed, batch sizes, processing latency (avg/p99), Kafka lag, error rate

## Installation

### Prerequisites

- Node.js >= 20.0.0
- npm (ships with Node.js)
- Redis 7+ (for caching and deduplication)
- Kafka (for event streaming) -- optional in development
- Docker and Docker Compose (for containerized development)

### Setup

```bash
# Clone the repository
git clone <repository-url>
cd "Data Ingestion Layer"

# Install all workspace dependencies
npm install

# Verify TypeScript compilation
npm run typecheck
```

## Quick Start

### Local Development (without Docker)

```bash
# Start the ingestion server with hot-reload
npm run dev:ingestion
```

The server starts on `http://localhost:3001` by default. It expects a Redis instance at `redis://localhost:6379`.

### Docker Compose (full stack)

```bash
# Start all services: ingestion, Redis, Kafka, Zookeeper, ClickHouse
cd docker
docker compose up -d

# View ingestion server logs
docker compose logs -f ingestion
```

This brings up:

| Service | Port | Purpose |
|---------|------|---------|
| Ingestion | 3001 | Event ingestion API |
| Redis | 6379 | Caching, deduplication, real-time counters |
| Kafka | 9092 / 29092 | Event streaming |
| Zookeeper | 2181 | Kafka coordination |
| ClickHouse | 8123 / 9000 | Analytics database |

### Send a Test Event

```bash
curl -X POST http://localhost:3001/v1/batch \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-api-key>" \
  -d '{
    "batch": [
      {
        "id": "evt_001",
        "type": "track",
        "timestamp": "2025-01-15T12:00:00.000Z",
        "sessionId": "sess_abc123",
        "anonymousId": "anon_xyz789",
        "event": "button_click",
        "properties": {
          "buttonId": "cta-signup",
          "page": "/pricing"
        },
        "context": {
          "library": { "name": "aether-sdk", "version": "1.0.0" },
          "userAgent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        }
      }
    ],
    "sentAt": "2025-01-15T12:00:00.500Z"
  }'
```

## Configuration Reference

All configuration is driven by environment variables with sensible defaults. See `config.ts` for the full loader.

### Server

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `3001` | HTTP server port |
| `HOST` | `0.0.0.0` | Bind address |
| `NODE_ENV` | `development` | Environment (`production`, `staging`, `development`) |
| `LOG_LEVEL` | `info` | Log verbosity (`debug`, `info`, `warn`, `error`) |

### CORS

| Variable | Default | Description |
|----------|---------|-------------|
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |

### Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_ENABLED` | `true` | Enable rate limiting |
| `RATE_LIMIT_WINDOW_MS` | `60000` | Rate limit window (ms) |
| `RATE_LIMIT_MAX_REQUESTS` | `1000` | Max requests per window |

### Processing

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_BATCH_SIZE` | `500` | Maximum events per batch |
| `MAX_EVENT_SIZE_BYTES` | `32768` | Maximum single event size (bytes) |
| `ENRICH_GEO` | `true` | Enable GeoIP enrichment |
| `ENRICH_UA` | `true` | Enable user agent parsing |
| `ANONYMIZE_IP` | `true` | Anonymize client IP addresses |
| `VALIDATE_SCHEMA` | `true` | Enable event schema validation |
| `DEDUP_WINDOW_MS` | `300000` | Deduplication window (ms) |
| `DLQ_ENABLED` | `true` | Enable dead letter queue |

### Kafka

| Variable | Default | Description |
|----------|---------|-------------|
| `KAFKA_ENABLED` | `true` | Enable Kafka sink |
| `KAFKA_BROKERS` | `localhost:9092` | Comma-separated broker addresses |
| `KAFKA_EVENTS_TOPIC` | `aether.events.raw` | Target topic for raw events |
| `KAFKA_CLIENT_ID` | `aether-ingestion` | Kafka client identifier |
| `KAFKA_COMPRESSION` | `snappy` | Compression codec |
| `KAFKA_ACKS` | `-1` | Required acks (`-1` = all replicas) |
| `KAFKA_MAX_BATCH_SIZE` | `16384` | Producer max batch size (bytes) |
| `KAFKA_LINGER_MS` | `5` | Producer linger time (ms) |
| `KAFKA_SSL` | `true` in production | Enable SSL |
| `KAFKA_SASL` | `true` in production | Enable SASL authentication |
| `KAFKA_SASL_USER` | -- | SASL username |
| `KAFKA_SASL_PASS` | -- | SASL password |
| `KAFKA_FLUSH_BATCH` | `100` | Events per flush batch |
| `KAFKA_FLUSH_INTERVAL_MS` | `1000` | Flush interval (ms) |

### S3

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_ENABLED` | `true` | Enable S3 sink |
| `S3_EVENTS_BUCKET` | `aether-events-raw` | Target S3 bucket |
| `AWS_REGION` | `us-east-1` | AWS region |
| `S3_PREFIX` | `events/` | Object key prefix |
| `S3_FLUSH_BATCH` | `5000` | Events per flush batch |
| `S3_FLUSH_INTERVAL_MS` | `60000` | Flush interval (ms) |

### ClickHouse

| Variable | Default | Description |
|----------|---------|-------------|
| `CLICKHOUSE_ENABLED` | `false` | Enable ClickHouse sink |
| `CLICKHOUSE_HOST` | `localhost` | ClickHouse host |
| `CLICKHOUSE_PORT` | `8123` | ClickHouse HTTP port |
| `CLICKHOUSE_DB` | `aether` | Database name |
| `CLICKHOUSE_USER` | `default` | Username |
| `CLICKHOUSE_PASS` | -- | Password |
| `CLICKHOUSE_FLUSH_BATCH` | `1000` | Events per flush batch |
| `CLICKHOUSE_FLUSH_INTERVAL_MS` | `5000` | Flush interval (ms) |

### Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_ENABLED` | `true` | Enable Redis sink |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `REDIS_RT_TTL` | `86400` | Real-time data TTL (seconds) |

### Monitoring

| Variable | Default | Description |
|----------|---------|-------------|
| `METRICS_ENABLED` | `true` | Enable Prometheus metrics |
| `METRICS_PORT` | `9090` | Metrics server port |
| `TRACING_ENABLED` | `false` | Enable distributed tracing |

## API Endpoints

### `POST /v1/batch`

Ingest a batch of events. Requires a valid API key.

**Headers:**
- `Authorization: Bearer <api-key>` -- required
- `Content-Type: application/json` -- required
- `X-Aether-SDK: <sdk-identifier>` -- optional

**Request Body:**

```json
{
  "batch": [
    {
      "id": "string",
      "type": "track | page | screen | identify | conversion | wallet | transaction | error | performance | experiment | consent | heartbeat",
      "timestamp": "ISO 8601 string",
      "sessionId": "string",
      "anonymousId": "string",
      "userId": "string (optional)",
      "event": "string (optional)",
      "properties": {},
      "context": {
        "library": { "name": "string", "version": "string" },
        "page": { "url": "", "path": "", "title": "", "referrer": "", "search": "", "hash": "" },
        "device": { "type": "desktop | mobile | tablet", "..." : "..." },
        "campaign": { "source": "", "medium": "", "..." : "..." },
        "userAgent": "string",
        "ip": "string",
        "locale": "string",
        "timezone": "string",
        "consent": { "analytics": true, "marketing": false, "web3": false, "..." : "..." }
      }
    }
  ],
  "sentAt": "ISO 8601 string"
}
```

**Responses:**

| Status | Description |
|--------|-------------|
| `200` | Events accepted and queued for processing |
| `400` | Validation error (malformed payload, invalid event schema) |
| `401` | Authentication error (missing or invalid API key) |
| `413` | Payload too large (exceeds `MAX_EVENT_SIZE_BYTES` or `MAX_BATCH_SIZE`) |
| `429` | Rate limit exceeded (includes `Retry-After` header) |
| `500` | Internal server error |

### `GET /health`

Health check endpoint returning component-level status.

**Response:**

```json
{
  "status": "healthy | degraded | unhealthy",
  "version": "8.7.0",
  "uptime": 12345,
  "timestamp": "2025-01-15T12:00:00.000Z",
  "checks": {
    "kafka": { "status": "up", "latencyMs": 2, "lastCheck": "..." },
    "redis": { "status": "up", "latencyMs": 1, "lastCheck": "..." },
    "clickhouse": { "status": "down", "message": "...", "lastCheck": "..." }
  }
}
```

## Development Commands

All commands are run from the repository root.

```bash
# Start ingestion server with hot-reload (tsx watch)
npm run dev:ingestion

# Build all packages and services
npm run build

# Run all unit tests
npm run test

# Run tests in watch mode
npm run test:watch

# Run integration tests
npm run test:integration

# Lint all TypeScript files
npm run lint

# Type-check without emitting
npm run typecheck

# Clean all build artifacts
npm run clean
```

### Docker

```bash
# Start full development stack
cd docker && docker compose up -d

# Rebuild after code changes
cd docker && docker compose up -d --build

# Stop all services
cd docker && docker compose down

# Stop and remove volumes
cd docker && docker compose down -v
```

## Project Structure

```
Data Ingestion Layer/
  packages/
    auth/              @aether/auth — API key authentication
    cache/             @aether/cache — Redis caching layer
    common/            @aether/common — Shared types and utilities
    events/            @aether/events — Event validation and schemas
    logger/            @aether/logger — Structured JSON logging
  services/
    ingestion/         @aether/ingestion — HTTP ingestion server
  docker/
    Dockerfile         Multi-stage build (dev / build / production)
    docker-compose.yml Full local stack (Redis, Kafka, ClickHouse)
  config.ts            Environment-aware configuration loader
  types.ts             Shared type definitions
  utils.ts             Shared utility functions
  event-enricher.ts    Enrichment pipeline and dead letter queue
  index.ts             Logger implementation
  tsconfig.json        Root TypeScript configuration
  tsconfig.build.json  Build-specific TypeScript configuration
  package.json         Workspace root
```

## License

Proprietary. All rights reserved.
