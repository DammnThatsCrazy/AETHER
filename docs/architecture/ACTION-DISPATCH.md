---
title: Governed Action Dispatch
slug: ai/action-dispatch
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: beta
since_version: 0.1.0
source_files: [services/api/intelligence/intelligence/routes.py, services/api/intelligence/intelligence/action_targets/base.py, services/api/intelligence/intelligence/action_targets/registry.py]
related: [ai/integration-actions, ai/decision-outcome-intelligence]
canonical_owner: platform@aether
estimated_read_minutes: 4
toc_depth: 3
source_hashes:
  "services/api/intelligence/intelligence/action_targets/base.py": "sha256:455280d204f34cf4b774550f1d46024b320ae8e0f2f77eed44b3db8b6b7c2672"
  "services/api/intelligence/intelligence/action_targets/registry.py": "sha256:06edc4a24ff4a7e14927a05414e5ce40b8da8d187af3895b0e893b21cb98d56c"
  "services/api/intelligence/intelligence/routes.py": "sha256:60d5307836ffcd38c784710b60689c803347d7a3dbb0f7608a64ba66ef150241"
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

An idempotent reservation starts as `authorization_pending`. One request
atomically claims it as `authorizing` before persisting the `action.dispatch`
policy decision. If policy or audit decision persistence fails, the reservation
returns to `authorization_pending`; a later retry can complete authorization
using the same dispatch ID. The target is not called until authorization
persistence succeeds, and concurrent retries cannot claim the reservation or
cause a second connector call.

Optional Journey intent or Risk intervention references are validated before a
new dispatch and retained on its reservation. Reusing a key cannot rebind that
reservation. Risk association currently supports exact entity subjects only;
the recommendation must name the same entity. Projection reads require a
separate actions-domain read policy decision and expose bounded dispatch
evidence, not proof of historical authority or an external effect. A replay
must repeat the same association reference and match the stored tenant, action,
decision, selected action, and recommendation linkage. It returns the reserved
dispatch and latest intelligence receipt without invoking the connector again;
the stored Journey or Risk association is used as recorded and is not treated
as proof that the referenced decision remains current.

When a concrete target returns a delivered receipt, it must include a real
external evidence id (simulation-shaped ids are rejected). When the target is
not implemented, the already-reserved dispatch remains a durable `queued`
plan and is handed to the canonical `DeliveryIntent`/`DeliveryJob` worker seam
when available. The response marks `planned: true` and
`external_side_effect: false`; it is not a claim that a provider was contacted.
Connector errors are retained as an auditable failed dispatch and do not clear
the reservation, so a retry cannot create a second external side effect.

The intelligence `action-dispatches/{dispatch_id}/receipts` API records a
dispatch receipt. Journey360 and Risk360 use a separate bounded read of the
canonical delivery worker chain: dispatch → deterministic `DeliveryIntent` →
`DeliveryJob` → `ProviderReceipt` → matching external-resource link. A provider
receipt is reported as connector-reported delivery evidence when tenant,
provider, external ID, and timestamps match. Tenant-submitted
`/v1/delivery/outcomes/ingest` events are labeled `caller_asserted` and are not
promoted to verified callbacks. Callback evidence is included only when the
outcome processor has verified the callback signature and bound it to the exact
tenant, provider receipt, and external resource. Even this evidence leaves
`externalEffect` as `not_independently_verified`; a delivery record or callback
does not independently establish the external action's effect.

`BaseActionTarget.dispatch()` raises `NotImplementedError` when no concrete
adapter exists. `ActionTargetRegistry` delegates adapter resolution to
`ProviderAdapterRegistry`. See [Delivery Architecture](DELIVERY-ARCHITECTURE.md)
and [ADR-001](adr-001-canonical-delivery-pipeline.md).

## Secret handling

Integration secrets such as `auth_secret`, `secret`, `api_key`, and `webhook_secret` are written to the tenant credential store under a server-built reference (`action_integration:{tenant_id}:{config_id}`) and omitted from API responses. A `secret_ref` supplied in the request body, at the top level or inside `config`, is discarded; the only reference an integration config or delivery job carries is the server-built one, and the delivery worker resolves it only within the job's tenant. Responses only expose `has_secret` so tenants can verify a credential is configured without leaking a stable credential fingerprint. Credentials are resolved at job-lease time — never stored in job payloads, Kafka events, or logs.

## Governance

Dispatch requires the authenticated tenant principal's `dispatch` permission and
an approved decision; elevated and critical actions also require an approval ID.
The persisted `action.dispatch` decision is bound to one dispatch ID, tenant,
principal, selected action, target, elevation/approval context, and Journey or Risk
association record. Journey360 and Risk360 recheck that exact context before
reporting a complete dispatch chain. This records an application permission
decision; it does not establish event-time authority, connector execution, or an
external effect. The dispatch payload includes the action, decision,
recommendation, expected value, expected outcome, and policy flags so downstream
systems can preserve audit context.
