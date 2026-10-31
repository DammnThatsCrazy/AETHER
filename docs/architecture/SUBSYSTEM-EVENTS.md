---
title: Events / Kafka Subsystem
slug: data/kafka
section: architecture
visibility: P
audience: [dev-senior, architect, ops]
status: stable
since_version: 0.1.0
source_files: [services/api/shared/events/events.py, services/api/ingestion/ingestion/validation.py, packages/shared/contracts/event-registry.json, packages/sdk/server/src/agent-telemetry.ts, services/api/actions/agent_marketplace/authority.py, services/api/actions/agent_marketplace/identity_binding.py, services/api/actions/agent/deployment_routes.py, services/api/actions/agent/user_agents.py, services/api/alembic/versions/20261011_agent_delegated_to_namespace.py, services/api/alembic/versions/20261022_execution_approval_decisions.py, services/api/ingestion/ingestion/lifecycle_worker.py, services/api/ingestion/silver/projectors/agent_execution_projector.py, services/api/ingestion/silver/projectors/silver_graph_projector.py, services/api/repositories/repos.py, services/api/repositories/commerce_repos.py, services/api/value/x402/commerce_models.py, services/api/value/x402/commerce_store.py, services/api/value/x402/provenance.py]
canonical_owner: backend@aether
estimated_read_minutes: 5
toc_depth: 3
reviewed_source_commits:
  - commit: "3906b500a"
    reason: "Reviewed the 360 PR repository diff: AgentExecution now records exact workflow-run and approval references and can claim an execution ID without overwriting it. This is backend execution metadata, not a new event topic."
  - commit: "482948261"
    reason: "Reviewed 482948261 (Codex findings on fleet hypotheses, bounded lineage reads and journey handoff): repositories/repos.py only gains the additive BaseRepository.insert_if_absent and replace_if_matches conditional-write primitives, deployment_routes.py reads lineage through a shared bounded reader that reports truncation, middleware.py lets site-bound publishable keys reach the two journey-handoff POSTs, and route_registry.yaml classifies the /sdk/journey-handoff prefix; nothing this doc describes changed behavior, so no body change was required."
source_hashes:
  "packages/sdk/server/src/agent-telemetry.ts": "sha256:216d195137016823c34f6878057c3ba088a56583e4cf39f5c162b8a780d8d30e"
  "packages/shared/contracts/event-registry.json": "sha256:120f804eb01fc0a3651b2b412850c848f47862421ef495233526599da31994b2"
  "services/api/actions/agent/deployment_routes.py": "sha256:052adc35fd86925e255ea0f0fd2101ebdd3a9ea1b832f2b98702ecda335adc1f"
  "services/api/actions/agent/user_agents.py": "sha256:1c816eeb373ef4d4d4fb62e8c07dfc98ae76dc7558551cbf18b10beef3a34bd0"
  "services/api/actions/agent_marketplace/authority.py": "sha256:b136984919ab302e7140815f5984f4cfad11494c3a591853af33d4c741a88b29"
  "services/api/actions/agent_marketplace/identity_binding.py": "sha256:0508f1094a8d369cd6c02004a18456c4b21b3b15f7160742d0ba6c9155aae352"
  "services/api/alembic/versions/20261011_agent_delegated_to_namespace.py": "sha256:446edfe924829cc75d627af169fb12c975f11f2ab13cf17b735ff14a8fed1c10"
  "services/api/alembic/versions/20261022_execution_approval_decisions.py": "sha256:6f3c2ff0235a78fd144f0b26bb76a36556c23a1bc5a8285e58588608e9fa7fb6"
  "services/api/ingestion/ingestion/lifecycle_worker.py": "sha256:7b6d7d2323a5646c0f7a7093e7ae256f943c70af07557080ef5949d09d07e5d8"
  "services/api/ingestion/ingestion/validation.py": "sha256:b643b9e467899a1b1ed5b73e7be21cfdc3ab79f9c962067ffdda71d55c2abff1"
  "services/api/ingestion/silver/projectors/agent_execution_projector.py": "sha256:0f2e0ac53d5ed9c4c62ee6cf110ee2bcb5ba5691f4ef246cb093eeb1c1c1fc8b"
  "services/api/ingestion/silver/projectors/silver_graph_projector.py": "sha256:c9af48ff73ec21e1c48a91249d97931bd3317b24dc19beb0be84c8be2eb8d8cd"
  "services/api/repositories/commerce_repos.py": "sha256:8c49d39ce010798b1bc1bd959d3845dddace8d33135c4f98c1d604eed120612e"
  "services/api/repositories/repos.py": "sha256:c84eb3895639d7a9e0dbd8575fe0c1a1e0e83ce794f57ab4aca464d4a7c0e4a8"
  "services/api/shared/events/events.py": "sha256:92a17e02a32de87e1744f75bf5c665d0482400efe0b734602abb37eda4dbdb1b"
  "services/api/value/x402/commerce_models.py": "sha256:50dbf80d7699ccdfcd5206d94a2dadc33ae73c1c06caac80da23e953320e282a"
  "services/api/value/x402/commerce_store.py": "sha256:4edc09e2cd51b0a7eefbf0c12cb4894f389b4f01f4e66a1ffacf10d9c7bd46e9"
  "services/api/value/x402/provenance.py": "sha256:235c29fc3b743ea75c15902f8e9a2cb635c95d2b04b7aa82c28c96ae65769b18"
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
- `Topic` — Enum of all event topics (257 topics grouped into domain sections).
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

Topics are organized by domain (257 total). Examples:
- **Ingestion:** `aether.sdk.events.raw`, `aether.sdk.events.validated`
- **Identity:** `aether.identity.resolved`, `aether.identity.merged`
- **Analytics:** `aether.analytics.session.scored`, `aether.analytics.anomaly`
- **Agent:** `aether.agent.task.started`, `aether.agent.task.completed`
- **Commerce:** `aether.commerce.payment.sent`, `aether.commerce.agent.hired`
- **A2H:** `aether.agent.notification.sent`, `aether.agent.recommendation.made`
- **Semantic Intelligence:** `aether.semantic.observed`, `aether.semantic.state.recomputed`, `aether.semantic.review.enqueued`
- **Notification Intelligence:** `aether.notifications.intelligence.detected`, `.validated`, `.queued`, `.delivered`, `.failed`, `.propagated`, `.expired`; `aether.notifications.operator.action`; `aether.notifications.channel.connected`, `.disconnected`
- **Platform control plane:** durable job lifecycle, export artifacts, tenant notification inbox/outbox, job schedules, bulk imports, measurement restatement, reconciliation runs
- **Risk360 / Fraud360 (read-only projection plane):** `aether.risk.signal.created` / `.superseded`, `aether.risk.assessment.created` / `.superseded`, `aether.fraud.hypothesis.created` / `.updated` / `.confirmed` / `.superseded`
- **Data Exchange Plane:** `aether.data_exchange.artifact.uploaded` (governed transfer uploads; envelope import/export transitions deliberately reuse the existing `IMPORT_*` / `EXPORT_*` vocabulary)
- **Reports (Data Exchange):** `aether.report.requested`, `.available`, `.failed`, `.downloaded` (report-artifact lifecycle)
- **Responsiveness spine:** `aether.tenant.activation.updated`, `aether.tenant.surface_readiness.updated`, `aether.lens.projection.updated`, `aether.background_job.updated`. These are best-effort state-transition notifications from `services/api/governance/responsiveness`.
- **Dead letter:** the durable `DEAD_LETTER` topic

## Envelope Required-Field Enforcement (staged)

Ingestion validation (`services/api/ingestion/ingestion/validation.py`) stages enforcement of the canonical envelope v1 fields `context.sequence`, `context.schemaVersion`, and `context.surface`:

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

## External agent action evidence

The server SDK emits source-asserted events for agent task starts/completions/
failures, tool invocations, policy evaluations, and delegated tasks. Ingestion
accepts these events, `agent_subagent_spawned`, and the 37 agent behavior
taxonomy types (objectives, decisions, authorization, execution, economic,
information and memory references) only with an active deployment identity
validated against the authenticated tenant. The backend registry identity is authoritative;
SDK-supplied agent identity and delegation targets remain source references.
Silver preserves the event timeline and run explanation reports which evidence
was not observed. Graph projection links bounded action and policy-decision
records to a tenant-scoped run through the retryable graph-writer outbox.
Optional payment, settlement and delegation IDs remain source references.
Economic links require exact same-tenant records with server-owned x402
provenance and the validated deployment agent reference; reported payment
values are not accepted as facts. For delegation, the tenant-admin binding
service resolves deployment source namespace/reference to a same-tenant
canonical Agent, and an exact delegation reference resolves the canonical
Delegation. Target binding requires the source-declared `delegated_to_namespace`
and never falls back to the actor namespace. If both endpoints resolve, the
backend evaluates canonical grant status, endpoints, effective/revocation window, action, resource, and supported
amount limit at the source-reported event time as `within_scope`,
`out_of_scope`, or `indeterminate`. Event payload action/resource/time remain
source-asserted. This grant-policy evaluation does not prove external execution;
without a server-owned receipt occurrence remains source-reported and
unverified.

Communications connector ingress can request the consent authority's durable
receipt ID as part of validation. The receipt is passed to the projector only
when the evaluated consent decision allows the event; the connector bridge
keeps that receipt separate from provider-reported identity and consent fields.

When AETHER's own execution endpoint creates an `agent_executions` row, it
records the authenticated initiating principal separately from the target
agent and stores the server-recorded delegation decision, evaluated tenant,
and constraints. A
rejected attempt is still an execution-denial record; this local policy record
does not assert that an external tool or business action occurred.

The row can retain exact workflow-run, invocation, and approval references.
It can also retain a caller-reported workflow definition ID, revision, and
digest after the server checks one exact tenant run link, an active registered
revision, and a step naming the Agent. This is execution-row metadata, not a
new event topic or evidence that a declared trigger or step ran. The execution
path can claim a new ID without overwriting an existing record; those
references remain correlation evidence until their own authorities are joined
and verified.

When that run uses an execution-bound x402 approval, the server-owned execution
row and its start event also carry the exact `approval_id` and
`approval_decision_id`. The decision history remains in the commerce approval
authority and is joined by exact tenant and execution ID for Execution360. This
is not universal action authority and does not verify external execution.
