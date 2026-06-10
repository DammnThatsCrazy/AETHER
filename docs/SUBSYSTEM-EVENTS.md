---
title: Events / Kafka Subsystem
slug: data/kafka
section: data
visibility: P
audience: [dev-senior, architect, ops]
status: stable
since_version: "8.8.0"
source_files:
  - Backend Architecture/aether-backend/shared/events/events.py
canonical_owner: backend@aether
estimated_read_minutes: 4
toc_depth: 3
last_synced_commit: 9257a68
---

# Events / Kafka Subsystem

## Architecture

The event bus provides publish/subscribe messaging for cross-service communication via `shared/events/events.py`.

**Backend selection:**
- `AETHER_ENV=local` → in-memory list (events visible only within the process)
- `AETHER_ENV=staging/production` → Kafka via `aiokafka`

## Key Classes

- `EventProducer` — Publishes events to Kafka topics with retry logic.
- `EventConsumer` — Subscribes to topics with consumer groups and backpressure.
- `Event` — Serializable event schema with topic, payload, tenant_id, correlation_id.
- `Topic` — Enum of all event topics (114 topics across 17 sections).

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `KAFKA_BOOTSTRAP_SERVERS` | Yes (staging/prod) | — | Kafka broker addresses |

## Startup

`EventProducer.connect()` is called during `ResourceRegistry.startup()`. Creates an `AIOKafkaProducer` with `acks=all` and 3 retries.

`EventConsumer.start()` subscribes to registered topics and begins consuming.

## Health Check

`EventProducer.health_check()` checks Kafka broker connectivity. Exposed via `GET /v1/health` as the `event_bus` dependency.

## Event Topics

Topics are organized by domain:
- **Ingestion:** `aether.sdk.events.raw`, `aether.sdk.events.validated`
- **Identity:** `aether.identity.resolved`, `aether.identity.merged`
- **Analytics:** `aether.analytics.session.scored`, `aether.analytics.anomaly`
- **Agent:** `aether.agent.task.started`, `aether.agent.task.completed`
- **Commerce:** `aether.commerce.payment.sent`, `aether.commerce.agent.hired`
- **A2H:** `aether.agent.notification.sent`, `aether.agent.recommendation.made`
- **Notification Intelligence:** `aether.notifications.intelligence.detected`, `.validated`, `.queued`, `.delivered`, `.failed`, `.propagated`, `.expired`; `aether.notifications.operator.action`; `aether.notifications.channel.connected`, `.disconnected`

## Failure Modes

- Kafka unreachable in production → `RuntimeError` at startup (fail-closed)
- Kafka unreachable in local → falls back to in-memory list
- Publish failure → retries 3 times with exponential backoff, then raises
- Consumer handler failure → retries twice, then sends to DLQ
