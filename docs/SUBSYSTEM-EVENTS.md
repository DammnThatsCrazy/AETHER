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
  - Backend Architecture/aether-backend/services/ingestion/validation.py
canonical_owner: backend@aether
estimated_read_minutes: 5
toc_depth: 3
last_synced_commit: "b23e78c0"
---

# Events / Kafka Subsystem

## Architecture

The event bus provides publish/subscribe messaging for cross-service communication via `shared/events/events.py`.

**Backend selection:**
- `EVENT_BROKER=sns_sqs` (with `SQS_QUEUE_URL` set and boto3 installed) → AWS SQS, optionally with SNS fanout when `SNS_TOPIC_ARN` is set so every per-role consumer queue receives each published event
- `KAFKA_BOOTSTRAP_SERVERS` set → Kafka via `aiokafka`
- `AETHER_ENV=local` → in-memory list (events visible only within the process)

Non-local environments fail closed: if `EVENT_BROKER=sns_sqs` but boto3 or the queue URL is missing, or Kafka is selected but unreachable, startup raises `RuntimeError` rather than silently switching backends.

## Key Classes

- `EventProducer` — Publishes events (SNS/SQS, Kafka, or in-memory) with retry logic (`MAX_RETRIES=3`, exponential backoff from 0.1 s).
- `EventConsumer` — Subscribes to topics with consumer groups, backpressure (`MAX_CONCURRENT=10`, resizable via `resize_concurrency()`), per-role queue/DLQ bindings, and durable dead-lettering.
- `Event` — Serializable event schema with topic, payload, tenant_id, correlation_id, version, retry_count, and an optional `envelope` (v2 enrichment).
- `EventEnvelopeV2` — Profile 360 v2 enrichment envelope; every field optional, additive only. Attached via `Event.with_v2()`, which bumps `version` to `"2.0"`.
- `Topic` — Enum of all event topics (243 topics grouped into domain sections).
- `DLQPublishError` / `ConsumerClientTornDown` — named failure types: a failed durable dead-letter publish, and a broker client torn down while messages were still unacknowledged (which would otherwise turn a shutdown into a batch of duplicates).

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `KAFKA_BOOTSTRAP_SERVERS` | Yes (Kafka backend, staging/prod) | — | Kafka broker addresses |
| `EVENT_BROKER` | No | `kafka` | Set to `sns_sqs` to select the SQS backend |
| `SQS_QUEUE_URL` | Yes (SQS backend) | — | Process-wide consumer/producer queue; a consolidated process passes per-role queue URLs to `EventConsumer(queue_url=…)` instead |
| `SNS_TOPIC_ARN` | No | — | SNS fanout topic; publishes reach every subscribed per-role queue |
| `SQS_DLQ_QUEUE_URL` | Yes (SQS backend, single-role) | — | Dead-letter queue; per-role DLQs are passed as `EventConsumer(dlq_queue_url=…)` |

Consumer group IDs include `AETHER_ENV` (`aether-backend-<env>` by default) so staging/production consumer groups never interfere.

## Startup

`EventProducer.connect()` is called during `ResourceRegistry.startup()`. In Kafka mode it creates an `AIOKafkaProducer` with `acks=all` and 3 retries; in SQS mode it creates boto3 SQS (and, with fanout, SNS) clients. FIFO queues get `MessageGroupId=tenant_id` and `MessageDeduplicationId=event_id`.

`EventConsumer.start()` subscribes to registered topics and begins consuming (`enable_auto_commit=False` in Kafka mode — offsets are committed only after handlers or the durable DLQ path complete). Restart re-entry tears down any leftover broker client first so a zombie group member cannot stall partitions.

## Local In-Memory Delivery Pump

In `AETHER_ENV=local` with no broker reachable, `EventProducer.publish()` appends to an in-memory list and `EventConsumer.receive_loop()` returns immediately — nothing outside a broker poll ever invokes `EventConsumer.process()`. A `POST /v1/batch` therefore reached Bronze and stopped: the local stack's Bronze→Silver projection pipeline silently did not run.

`EventProducer.pump_local()` is the missing bridge. It is a cursor-based pump that drains the in-memory `_published` list into `consumer.process()`, the same canonical handler path the Kafka and SQS loops drive, giving the single-process local stack real Bronze→Silver delivery. Key properties:

- Wired by the `main.py` lifespan only when the producer actually connected **in-memory** (`producer.mode == "in-memory"`) and consumers are attached — a broker-connected producer is never double-delivered (its `_published` list stays empty, and the pump re-checks `mode`).
- Cursor-based: each event is delivered **at most once per process**; the cursor never resets.
- Events published by handlers while pumping are picked up on the next tick (handler-republish pickup).
- Cancelled cleanly on shutdown (the pump task is awaited with `CancelledError` swallowed before resources tear down).
- In a pure-`api` role process (`_start_consumers=False`) the pump never runs.

## Health Check

`EventProducer.health_check()` checks Kafka broker connectivity (SQS and in-memory modes report healthy while connected). Exposed as the `event_bus` check of the readiness probe (`GET /ready` / `GET /v1/ready`); `GET /v1/health` is the liveness surface and does not include per-dependency checks.

## Event Topics

Topics are organized by domain (243 total). Examples:
- **Ingestion:** `aether.sdk.events.raw`, `aether.sdk.events.validated`
- **Identity:** `aether.identity.resolved`, `aether.identity.merged`; identity-assurance lifecycle `aether.identity.verification.completed`, `aether.identity.verification.revoked`, and the async replay trigger `aether.identity.resolution.replay_requested`
- **Analytics:** `aether.analytics.session.scored`, `aether.analytics.anomaly`
- **Agent:** `aether.agent.task.started`, `aether.agent.task.completed`
- **Commerce:** `aether.commerce.payment.sent`, `aether.commerce.agent.hired`
- **A2H:** `aether.agent.notification.sent`, `aether.agent.recommendation.made`
- **Semantic Intelligence:** `aether.semantic.observed`, `aether.semantic.state.recomputed`, `aether.semantic.review.enqueued`
- **Notification Intelligence:** `aether.notifications.intelligence.detected`, `.validated`, `.queued`, `.delivered`, `.failed`, `.propagated`, `.expired`; `aether.notifications.operator.action`; `aether.notifications.channel.connected`, `.disconnected`
- **Platform control plane:** durable job lifecycle, export artifacts, tenant notification inbox/outbox, job schedules, bulk imports, measurement restatement, reconciliation runs
- **Dead letter:** the durable `DEAD_LETTER` topic

## Envelope Required-Field Enforcement (staged)

Ingestion validation (`services/ingestion/validation.py`) stages enforcement of the canonical envelope v1 fields `context.sequence`, `context.schemaVersion`, and `context.surface`:

- **Model layer:** the fields remain Optional — older SDK payloads still parse.
- **Enforcement:** gated by `settings.ingestion_v2.envelope_required_fields_enforced`, which defaults from the release profile — OFF in local/dev/integration, ON when `AETHER_ENV` is `staging` or `production`. The explicit env var `INGESTION_ENVELOPE_REQUIRED_FIELDS_ENFORCED` always wins, so enforcement can be rolled back per environment without a code change.
- **Scope:** applies only to release-critical event families `{core, journey, identity, consent}` — the families the founding release train projects. Families in excluded domains keep their metrics-only posture.
- **Rejection:** reason is `envelope_missing:<field>` (rendered via `format_rejection`, naming the first missing field in canonical order); the full missing-field list lands in `audit_metadata.envelope_missing_fields`, and `ingestion_validation_failed_total{reason="envelope_missing"}` is incremented.

## Failure Modes

- Kafka unreachable in production → `RuntimeError` at startup (fail-closed); `EVENT_BROKER=sns_sqs` with boto3 or the queue URL missing fails closed the same way rather than silently switching backends
- Broker unreachable in local → falls back to in-memory list
- Publish failure → retries 3 times with exponential backoff, then raises
- Consumer handler failure → retries twice (`MAX_HANDLER_RETRIES=2`), then dead-letters durably: to the `DEAD_LETTER` Kafka topic or the resolved SQS DLQ (never the source queue — a dead letter is never sent to the queue it came from)
- Durable DLQ publish failure → raises `DLQPublishError`; the source message is left unacknowledged (no Kafka commit / SQS delete) so it redelivers instead of being lost
- Kafka per-message failure that cannot be acknowledged → the consume loop rewinds to the failed offset and exits without committing, so the supervised restart re-fetches it (no auto-commit past failures)
- SQS messages are deleted only after successful processing; unacknowledged messages become visible again and move to the queue's redrive target after `maxReceiveCount`
- Client torn down while messages are unacknowledged → `ConsumerClientTornDown` (drains wait on both in-flight handlers and unacknowledged messages to avoid duplicate application)
- Kafka batch overflow (`batch.append()` returns `None`) → overflow events fall back to individual `publish()` calls, ensuring no silent drops when a batch payload exceeds broker limits
- DLQ events include `original_payload` so failed events are replayable without data loss
