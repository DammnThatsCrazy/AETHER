---
title: Data Ingestion — Architecture & API Reference
slug: data/ingestion
section: data
visibility: P
audience: [dev-junior, dev-senior, architect, ops]
status: stable
since_version: "8.8.0"
source_files:
  - Data Ingestion Layer/README.md
  - Data Ingestion Layer/services/ingestion/
  - Data Ingestion Layer/packages/
canonical_owner: ingest@aether
estimated_read_minutes: 10
toc_depth: 3
last_synced_commit: 4ca75de
---

# Data Ingestion — Architecture & API Reference

The Aether Ingestion Layer is a Node.js / TypeScript service that accepts
analytics events from every Aether SDK, enriches them, and fans them out to the
platform's storage and streaming backends. It is the single authoritative entry
point for raw event data.

## Architecture overview

```
SDK clients
    │  POST /v1/batch
    ▼
Ingestion Server (port 3001)
    │  validation → enrichment → fan-out
    ├──▶ Apache Kafka   (real-time consumers)
    ├──▶ Amazon S3      (raw archive / data lake)
    ├──▶ ClickHouse     (analytics warehouse)
    └──▶ Redis          (session cache / rate-limit state)
```

Events enter through a single HTTP endpoint. The server validates the payload,
enriches each event with server-side metadata (GeoIP, timestamp normalisation),
then writes to all four sinks atomically within a single processing pipeline.
Failed events land in a dead-letter queue for manual inspection.

## Packages

The ingestion monorepo (`Data Ingestion Layer/`) contains five internal packages
shared across the service and any consumers:

| Package | Purpose |
|---------|---------|
| `@aether/common` | Shared TypeScript types, error classes, utility helpers |
| `@aether/auth` | API-key validation middleware, rate-limit enforcement |
| `@aether/cache` | Redis client wrappers, TTL helpers |
| `@aether/events` | Event schema definitions and validation (Zod) |
| `@aether/logger` | Structured JSON logging (Pino) with correlation IDs |

## Event types

Twelve first-class event types are recognised (source:
`Data Ingestion Layer/services/ingestion/src/validator.ts`):

| Event | Description |
|-------|-------------|
| `track` | Generic custom event with arbitrary properties |
| `page` | Browser page-view impression |
| `screen` | Mobile screen impression |
| `identify` | User identity resolution (anonymous → identified) |
| `conversion` | Goal or funnel conversion |
| `wallet` | Web3 wallet connection or interaction |
| `transaction` | On-chain or off-chain commerce transaction |
| `error` | Client-side error capture |
| `performance` | Core Web Vitals and custom performance marks |
| `experiment` | A/B or feature-flag experiment exposure |
| `consent` | GDPR/CCPA consent change |
| `heartbeat` | SDK keep-alive / session heartbeat |

Events sent with an unrecognised type are rejected with 400.

## Enrichment

Every event is enriched server-side before fan-out:

- **GeoIP** — IP address resolved to country, region, city via MaxMind GeoLite2.
  The raw IP is not forwarded downstream (privacy-by-default).
- **Timestamp normalisation** — Client-supplied timestamps are validated; events
  with timestamps more than 24 hours in the past or future are rejected with 400.
- **Server receive time** — `received_at` set to the ingestion server's UTC clock.
- **Session correlation** — `session_id` propagated from the auth context when
  absent from the payload.
- **SDK version tag** — `sdk_version` attached from the `User-Agent` header.

## API

### POST /v1/batch

Ingest a batch of events.

**Authentication** — `Authorization: Bearer <api_key>` header required.
API keys are provisioned per project and validated against the key store on every
request.

**Request body**

```json
{
  "batch": [
    {
      "type": "page",
      "timestamp": "2025-01-15T12:00:00Z",
      "anonymous_id": "anon-uuid",
      "user_id": "usr_abc123",
      "properties": {}
    }
  ],
  "sentAt": "2025-01-15T12:00:00Z"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `batch` | array | yes | 1 – 500 events per request |
| `sentAt` | ISO-8601 string | yes | Client-side send time; used to detect clock skew |
| `batch[].type` | string | yes | One of the 12 recognised types (see Event types above) |
| `batch[].timestamp` | ISO-8601 string | yes | UTC; ±24 h window enforced |
| `batch[].anonymous_id` | string | no | Required when `user_id` is absent |
| `batch[].user_id` | string | no | Required when `anonymous_id` is absent |
| `batch[].properties` | object | no | Arbitrary key/value pairs |

**Response codes**

| Code | Meaning |
|------|---------|
| `200 OK` | Batch accepted and queued for fan-out |
| `400 Bad Request` | Validation failure (malformed payload, invalid timestamp) |
| `401 Unauthorized` | Missing or invalid API key |
| `413 Payload Too Large` | Batch exceeds `MAX_BATCH_SIZE` or single event exceeds `MAX_EVENT_SIZE_BYTES` |
| `429 Too Many Requests` | Rate limit exceeded for the API key |
| `500 Internal Server Error` | Fan-out failure; event may have been partially written |

### GET /health

Returns `{"status":"ok"}` when the service is healthy. Used by ECS health checks
and load-balancer probes. Returns 503 if any downstream sink is unreachable.

## Configuration

All configuration is supplied via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `3001` | HTTP listener port |
| `MAX_BATCH_SIZE` | `500` | Maximum events per `/v1/batch` call |
| `MAX_EVENT_SIZE_BYTES` | `32768` | Maximum bytes for a single serialised event (32 KB) |
| `KAFKA_BROKERS` | — | Comma-separated Kafka broker URLs |
| `KAFKA_TOPIC_PREFIX` | `aether.` | Prefix for all Kafka topic names |
| `S3_BUCKET` | — | S3 bucket for raw event archive |
| `CLICKHOUSE_URL` | — | ClickHouse HTTP endpoint |
| `REDIS_URL` | — | Redis connection string |
| `GEOIP_DB_PATH` | `/data/GeoLite2-City.mmdb` | Path to MaxMind database file |

See `.env.example` for a complete reference with descriptions.

## Dead-letter queue

Events that fail fan-out (e.g., a Kafka write times out after all retries) are
written to a DLQ topic (`aether.dlq`) and logged with a correlation ID.
The on-call engineer uses the DLQ replay script (`scripts/replay_dlq.ts`) to
re-enqueue failed events after the downstream issue is resolved.

Events in the DLQ are retained for 7 days. After that window, recovery requires
restoring from the raw S3 archive.

## Relationship to the Python backend

The Node.js ingestion server handles all **SDK-originated event streams** via
`POST /v1/batch`. The Python FastAPI backend (`Backend Architecture/`) exposes
a separate `/v1/ingest/*` family of endpoints for **server-side event ingestion**
(e.g., back-end commerce events, compliance audit records). Both paths converge
on the same Kafka topics and downstream sinks, but they are distinct services
with separate authentication and rate-limiting.

## Operational notes

- The ingestion server runs as an ECS Fargate service behind an ALB. Scale-out
  is triggered at 70% CPU or 1 000 in-flight requests.
- ClickHouse writes are batched in 1-second windows to amortise insert overhead.
  This introduces up to ~2 seconds of query lag on the analytics side.
- GeoIP lookups are in-process (no external API call). The MaxMind database is
  updated weekly via a scheduled ECS task.
- The S3 archive uses Hive-partitioned prefixes
  (`year=YYYY/month=MM/day=DD/hour=HH/`), enabling Athena ad-hoc queries
  without a schema migration.
