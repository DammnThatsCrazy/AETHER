---
title: Action Dispatch
slug: ai/action-dispatch
section: ai
visibility: I
audience: [ai, architect, dev-senior, ops]
status: beta
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/intelligence/routes.py
  - Backend Architecture/aether-backend/services/intelligence/decision_models.py
  - Backend Architecture/aether-backend/services/intelligence/action_targets/base.py
flags:
  - AETHER_DECISION_RECORDS_ENABLED
related:
  - ai/integration-actions
  - ai/outcome-ledger
  - ai/playbooks
---

# Action Dispatch

Action Dispatch turns an `ActionFeedback` record into a governed integration delivery attempt.

## Lifecycle

1. Load the action and validate tenant isolation.
2. Load the decision and require `decision_status=approved`.
3. Load the recommendation and require it matches the decision.
4. Enforce `approval_id` metadata for elevated or critical selected actions.
5. Validate the integration config and target registry entry.
6. Build a deterministic idempotency key from tenant, action, target, integration, and payload.
7. Create `ActionDispatch` with `queued` status.
8. Simulate dispatch and create `ActionDeliveryReceipt`.
9. Update dispatch status to `sent`, `delivered`, or `failed`.
10. Emit lifecycle events and create `RevenueMeteringEvent` records.

## Endpoints

```http
POST /v1/intelligence/actions/{action_id}/dispatch
GET /v1/intelligence/actions/{action_id}/dispatches
GET /v1/intelligence/action-dispatches/{dispatch_id}
POST /v1/intelligence/action-dispatches/{dispatch_id}/retry
POST /v1/intelligence/action-dispatches/{dispatch_id}/cancel
```

Retries and cancellations are target-capability aware. Unsupported cancellation returns a validation error. Idempotent repeat dispatches return the existing dispatch and receipt instead of creating duplicates.

## Events

Dispatch emits `aether.action.dispatch_queued`, `aether.action.dispatch_sent`, `aether.action.dispatch_delivered`, `aether.action.dispatch_failed`, `aether.action.dispatch_retried`, and `aether.action.dispatch_cancelled` as applicable.
