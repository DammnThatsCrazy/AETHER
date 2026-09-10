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
source_hashes:
  "Backend Architecture/aether-backend/services/intelligence/action_targets/base.py": "sha256:983f23fdb3696c505d39e80232b5e91c22d917744fef156cc58900bbfde0c449"
  "Backend Architecture/aether-backend/services/intelligence/action_targets/registry.py": "sha256:06edc4a24ff4a7e14927a05414e5ce40b8da8d187af3895b0e893b21cb98d56c"
  "Backend Architecture/aether-backend/services/intelligence/routes.py": "sha256:a86a574763413db637d04ed7b679dc89d004c8d738dd090ebcbe8a822b81da05"
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

## Dispatch flow (current)

`POST /v1/intelligence/actions/{action_id}/dispatch` never fabricates a
successful delivery. Before invoking a target, an optional idempotency key is
reserved within the authenticated tenant and action. A replay returns the
existing durable dispatch and latest receipt with `replayed: true`; it does not
invoke a connector a second time, and the same key on another action or tenant
does not alias the reservation.

When a concrete target returns a delivered receipt, it must include a real
external evidence id (simulation-shaped ids are rejected). When the target is
not implemented, the already-reserved dispatch remains a durable `queued`
plan and is handed to the canonical `DeliveryIntent`/`DeliveryJob` worker seam
when available. The response marks `planned: true` and
`external_side_effect: false`; it is not a claim that a provider was contacted.
Connector errors are retained as an auditable failed dispatch and do not clear
the reservation, so a retry cannot create a second external side effect.

`BaseActionTarget.dispatch()` raises `NotImplementedError` when no concrete
adapter exists. `ActionTargetRegistry` delegates adapter resolution to
`ProviderAdapterRegistry`. See [Delivery Architecture](DELIVERY-ARCHITECTURE.md)
and [ADR-001](architecture/adr-001-canonical-delivery-pipeline.md).

## Secret handling

Integration secrets such as `auth_secret`, `secret`, `api_key`, and `webhook_secret` are converted to internal secret references and omitted from API responses. Responses only expose `has_secret` so tenants can verify a credential is configured without leaking a stable credential fingerprint. Credentials are resolved from the vault at job-lease time — never stored in job payloads, Kafka events, or logs.

## Governance

Dispatch requires an approved decision. The dispatch payload includes the action, decision, recommendation, expected value, expected outcome, and policy flags so downstream systems can preserve audit context.
