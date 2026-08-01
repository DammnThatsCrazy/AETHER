---
title: Governed Action Dispatch
slug: ai/action-dispatch
section: ai
visibility: I
audience: [architect, dev-senior, ops]
status: beta
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/intelligence/routes.py
  - Backend Architecture/aether-backend/services/intelligence/action_targets/base.py
  - Backend Architecture/aether-backend/services/intelligence/action_targets/registry.py
related:
  - ai/integration-actions
  - ai/decision-outcome-intelligence
canonical_owner: platform@aether
estimated_read_minutes: 4
toc_depth: 3
last_synced_commit: "297c204"
---

# Governed Action Dispatch

Action Dispatch connects approved Decision & Outcome Intelligence actions to external operator systems while preserving human-in-the-loop governance.

## Flow

1. Generate or evaluate a recommendation.
2. Record an approved decision with a selected candidate action.
3. Log an action for that decision.
4. Configure an action integration, if the target requires one.
5. Dispatch the action to a supported target.
6. Capture delivery receipts, retries, cancellations, and revenue metering events.

## API surface

- `GET /v1/intelligence/action-targets` lists available targets and their capabilities.
- `GET /v1/intelligence/action-integrations` lists tenant-scoped integration configs with secrets redacted.
- `POST /v1/intelligence/action-integrations` creates a config.
- `PUT /v1/intelligence/action-integrations/{config_id}` updates a config.
- `POST /v1/intelligence/actions/{action_id}/dispatch` dispatches an approved action.
- `POST /v1/intelligence/action-dispatches/{dispatch_id}/retry` retries a dispatch.
- `POST /v1/intelligence/action-dispatches/{dispatch_id}/cancel` cancels cancellable dispatches.
- `POST /v1/intelligence/action-dispatches/{dispatch_id}/receipts` records an external delivery receipt.
- `GET /v1/intelligence/action-dispatches` lists dispatches.

## Supported targets

The built-in target registry supports Slack, webhook, CRM, marketing automation, ticketing, and agent-assist workflows. Targets expose whether configuration, retries, delivery receipts, cancellation, and premium metering apply.

## Dispatch flow (as of 9.1.0)

`POST /v1/intelligence/actions/{action_id}/dispatch` no longer produces a simulated receipt. The dispatch call now:

1. Creates a `DeliveryIntent` (durable outbox record) atomically in the same DB transaction.
2. Creates a `DeliveryJob` per configured destination channel.
3. Returns `202 Accepted` with the job IDs.
4. `DeliveryWorker` (background process) leases jobs and calls the concrete `ProviderAdapter.deliver()` method.
5. A `ProviderReceipt` with a real `external_id` is required before the suggestion advances to DELIVERED.

`BaseActionTarget.dispatch()` raises `NotImplementedError` — it is no longer callable. `ActionTargetRegistry` delegates adapter resolution to `ProviderAdapterRegistry`. See [Delivery Architecture](DELIVERY-ARCHITECTURE.md) and [ADR-001](architecture/adr-001-canonical-delivery-pipeline.md).

## Secret handling

Integration secrets such as `auth_secret`, `secret`, `api_key`, and `webhook_secret` are converted to internal secret references and omitted from API responses. Responses only expose `has_secret` so tenants can verify a credential is configured without leaking a stable credential fingerprint. Credentials are resolved from the vault at job-lease time — never stored in job payloads, Kafka events, or logs.

## Governance

Dispatch requires an approved decision. The dispatch payload includes the action, decision, recommendation, expected value, expected outcome, and policy flags so downstream systems can preserve audit context.
