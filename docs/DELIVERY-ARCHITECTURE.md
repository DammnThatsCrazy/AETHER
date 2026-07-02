---
title: Delivery Architecture
slug: architecture/delivery-architecture
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: production
since_version: "9.0.0"
canonical_owner: platform@aether
estimated_read_minutes: 8
---

# Delivery Architecture

## Overview

Aether uses a **durable outbox pattern** to deliver suggestions and notifications to external systems (Slack, Linear, Jira, signed webhooks). Delivery is at-least-once with idempotency keys, and external outcomes (Slack button clicks, Linear status changes, Jira resolutions) return as canonical `ExternalOutcomeEvent` records that update the graph and outcome ledger.

## Canonical Flow

```
Graph / Noesis / Detection
  → SuggestionService (creates Suggestion with lineage)
  → PolicyDecision (auto or operator approval)
  → Suggestion status = APPROVED
  → DeliveryIntent created (idempotent on sha256(source_type:source_id:tenant_id))
  → DeliveryJob per destination channel (state = QUEUED)
  → DeliveryWorker leases job (SELECT FOR UPDATE SKIP LOCKED)
  → ProviderAdapter.deliver(payload, credentials, idempotency_key)
  → DeliveryAttempt persisted (immutable)
  → Provider API call → AdapterReceipt (real external_id required)
  → ProviderReceipt persisted (sim-* external_id rejected at DB level)
  → ExternalResourceLink created (aether_object ↔ provider resource)
  → Suggestion.status → DELIVERED (only after policy-satisfying receipt)
  → SUGGESTION_DELIVERED event published

Inbound:
  Provider webhook → POST /webhooks/{provider}/events
  → WebhookInbox persisted FIRST (before any business logic)
  → 200 returned immediately
  → WebhookInboxProcessor.process_pending()
  → signature verified (provider-native algorithm)
  → ExternalOutcomeEvent normalized
  → OutcomeRouter resolves ExternalResourceLink
  → Suggestion.outcome_state updated
  → Graph edge (OUTCOME_OBSERVED) created
```

## Data Models

| Model | Purpose |
|-------|---------|
| `DeliveryIntent` | Approved outbox record; idempotent per `(source_type, source_id, tenant_id)` |
| `DeliveryJob` | Per-destination durable work unit; state machine: QUEUED → LEASED → RUNNING → SUCCEEDED / FAILED → DEAD_LETTER |
| `DeliveryAttempt` | Immutable attempt record with latency, HTTP status, response excerpt |
| `ProviderReceipt` | Real provider acknowledgement; `external_id` is NOT NULL at DB level; `sim-*` prefix rejected by model validator |
| `ExternalResourceLink` | Join table between Aether objects and external provider resources |
| `ExternalOutcomeEvent` | Normalized inbound event; routed to suggestion / notification lifecycle |
| `WebhookInbox` | Raw webhook persistence (idempotent); persisted before any business processing |
| `ConnectorCursor` | Pull checkpoint per (tenant, connector); updated after each successful sync |

## Worker Model

`DeliveryWorker` runs as a background asyncio task (controlled by `AETHER_DELIVERY_WORKER_ENABLED`):

1. `lease_next_batch(worker_id, batch_size, lease_seconds)` — `SELECT FOR UPDATE SKIP LOCKED`
2. Per job: resolve credentials from `providers_repo` (fails closed if ref not found)
3. `adapter.deliver(payload, credentials, idempotency_key)` → `AdapterReceipt`
4. Persist `DeliveryAttempt` + `ProviderReceipt` + `ExternalResourceLink`
5. Advance lifecycle: suggestion → DELIVERED, publish `SUGGESTION_DELIVERED`
6. On failure: exponential backoff (base 30s × 2^attempt ± 20% jitter, max 1800s)
7. At `max_attempts`: mark DEAD_LETTER, publish `DELIVERY_JOB_DEAD_LETTERED`
8. Reclaim loop: every 60s re-queue jobs with expired `lease_expires_at`

## Retry Semantics

| Provider | Max attempts | Backoff |
|----------|-------------|---------|
| Slack | 3 | 30s → 60s → DEAD_LETTER |
| Linear | 5 | 30s → 60s → 120s → 240s → DEAD_LETTER |
| Jira | 5 | same |
| Webhook | 5 | same |

`Retry-After` response header is respected when present.

## Delivery Policy

`DeliveryIntent.delivery_policy`:
- `ALL_REQUIRED` — all jobs must succeed; partial delivery does not mark source as DELIVERED
- `ANY_REQUIRED` — any one successful receipt advances the source to DELIVERED

## Idempotency

- `DeliveryIntent`: `sha256(source_type:source_id:tenant_id)`
- `DeliveryJob`: `sha256(intent_id:channel_type:tenant_id)`
- `WebhookInbox`: `sha256(provider:raw_body_hash:received_at_minute)` — duplicate webhooks ignored

## Credential Flow

1. `DeliveryJob.provider_config.secret_ref` stores a vault reference (never a raw secret)
2. `DeliveryWorker` calls `providers_repo.find_by_id(secret_ref)` to resolve credentials
3. If the vault ref does not exist, the job fails with `AuthError` (fail-closed — never falls back to plaintext)
4. Credentials are never logged, returned by API, placed in task payloads, or sent to Kafka

## Anti-Simulation Guards

- `AdapterReceipt.__post_init__` raises `ValueError` if `external_id` is empty or `None`
- `ProviderReceipt` model validator raises `ValueError` if `external_id.startswith("sim-")`
- `ProviderReceiptRepository.create_receipt()` raises `ValueError` if `simulated=True` key present
- `BaseActionTarget.dispatch()` raises `NotImplementedError` — simulation removed entirely
