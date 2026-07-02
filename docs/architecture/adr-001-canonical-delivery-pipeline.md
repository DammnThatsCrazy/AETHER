---
title: "ADR-001: Canonical Delivery Pipeline"
slug: architecture/adr-001
section: architecture
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "9.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 8
---

# ADR-001: Canonical Delivery Pipeline

**Status:** Accepted  
**Date:** 2026-07-02  
**Deciders:** Platform Engineering

---

## Context

Before version 9.1, Aether had four independent delivery pathways:

1. `notification_adapter.py` — called `service.deliver_suggestion()` directly after approval, marking DELIVERED with zero proof.
2. `notification_intelligence/consumer.py` — used `asyncio.create_task()` for fire-and-forget routing; worker restarts lost all in-flight deliveries.
3. `channel_gateway.py` — direct Slack/webhook gateway with no receipt model.
4. `action_targets/base.py` — returned `{"simulated": True, "external_id": "sim-…"}` for all 6 targets; suggestions reached DELIVERED state based on fabricated external IDs.

These pathways had 14 confirmed defects (D1–D14), including credential references returned as literal tokens, suggestion lifecycle advancing without provider confirmation, and no durable job model.

---

## Decision

Consolidate all delivery into one canonical pipeline:

```
APPROVED suggestion
  → DeliveryIntent (atomic, same DB transaction)
  → DeliveryJob per destination (durable, QUEUED state)
  → DeliveryWorker leases job (SELECT FOR UPDATE SKIP LOCKED)
  → ProviderAdapter.deliver() → real HTTP call
  → AdapterReceipt (external_id required, non-empty, non-simulated)
  → ProviderReceipt persisted
  → ExternalResourceLink created
  → Suggestion.status → DELIVERED only after policy-satisfying receipts
  → Provider webhook/poll → WebhookInbox persistence
  → ExternalOutcomeEvent normalized
  → OutcomeLedger updated
  → Graph mutation
  → Suggestion.outcome_state updated
```

---

## Rationale

### Why one pipeline

Multiple independent delivery pathways produced split brain: the same suggestion could be "delivered" via one path while another path treated it as undelivered. Runbook authors could not reason about state. Consolidating to one pipeline gives a single source of truth for delivery state.

### Why at-least-once + idempotency

Exactly-once delivery is impossible across network boundaries. At-least-once with idempotency is the industry-standard solution. Every `DeliveryIntent` and `DeliveryJob` carries an `idempotency_key` (`sha256(source_type:source_id:tenant_id)`). Duplicate job creation is rejected by a unique constraint. Provider adapters include the idempotency key in outbound requests where the provider supports it (Slack `idempotency_key`, webhook `X-Aether-Idempotency-Key` header).

### Why provider receipts control DELIVERED

A suggestion must not reach DELIVERED state until at least one provider has acknowledged receipt with a real, verifiable external identifier. This eliminates the D1 class of defect (marking delivered before confirmation) and the D4 class (simulated delivery with fake external IDs).

Hard guards enforce this at every layer:
- `AdapterReceipt.__post_init__` raises `ValueError` if `external_id` is empty or None.
- `ProviderReceiptRepository.create_receipt()` raises `ValueError` if `simulated=True` is present.
- `BaseActionTarget.dispatch()` raises `NotImplementedError` — simulation removed at the call site.

### How external outcomes return to the graph

Provider confirmations flow back via webhooks:
1. Raw webhook arrives at `/v1/webhooks/{provider}/events`.
2. Written to `WebhookInbox` immediately, before any business logic.
3. `WebhookInboxProcessor` claims pending inbox records and verifies signatures.
4. Normalized to `ExternalOutcomeEvent` and linked to `ExternalResourceLink`.
5. `OutcomeRouter` maps event type to suggestion outcome, advances `outcome_state`, and emits a graph edge (`OUTCOME_OBSERVED`).

Loop prevention: `OutcomeRouter` skips events where `event_data.aether_origin` is set (Aether-originated updates should not feed back as external outcomes). No-op transitions (new state == current state) are also skipped.

### How 4 delivery pathways were consolidated

| Old pathway | Replacement |
|-------------|-------------|
| `notification_adapter.py` direct deliver | Creates `DeliveryIntent` + `DeliveryJob`; returns suggestion at APPROVED |
| `consumer.py` `asyncio.create_task()` | Creates `DeliveryIntent` + `DeliveryJob` synchronously; no fire-and-forget |
| `channel_gateway.py` direct dispatch | Reused internally by `SlackProviderAdapter.deliver()`; not replaced |
| `action_targets/base.py` simulated dispatch | Raises `NotImplementedError`; `ActionTargetRegistry` delegates to `ProviderAdapterRegistry` |

### Credential flow (fail-closed)

Credentials are never stored in `DeliveryIntent` or `DeliveryJob` payloads. Each job carries a `credentials_ref` (vault reference). `DeliveryWorker` resolves the reference on each job lease via `ProvidersRepository`. If resolution fails, the job fails — it does not fall back to treating the ref as a literal token. The D3 defect (credential ref returned as token) is eliminated at the code level with a hard `RuntimeError`.

---

## Alternatives Considered

**Separate pipeline per provider type**: Rejected. Increases operational surface area, requires separate monitoring per pipeline, and does not simplify runbooks.

**Kafka-only delivery**: Rejected. Kafka at-least-once delivery without a database-backed job model provides no way to query delivery state, replay individual jobs, or implement lease-based worker recovery.

**Keep simulated dispatch for non-production environments**: Rejected. Simulation hiding behind an environment flag is a subtle correctness risk. Fake IDs in test data mislead runbooks and confuse production queries. Fake providers (FastAPI test servers) serve the same testing purpose without simulation.

---

## Consequences

- Every suggestion delivery creates at least two new DB rows (DeliveryIntent + DeliveryJob). This is intentional — it provides a complete audit trail.
- `DeliveryWorker` must be running for suggestions to reach DELIVERED. Feature-flagged via `AETHER_DELIVERY_WORKER_ENABLED`.
- Provider adapters for CRM, marketing, and agent-assist require additional concrete implementations; those adapters currently fail closed with `InvalidPayloadError` or publish internal events.
- Existing `action_delivery_receipts` rows with `external_id LIKE 'sim-%'` are classified as `receipt_classification='legacy_simulated'` in the migration backfill — not promoted to real receipts.
