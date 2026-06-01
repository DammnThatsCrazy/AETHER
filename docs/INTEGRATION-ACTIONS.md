---
title: Integration Actions
slug: ai/integration-actions
section: ai
visibility: I
audience: [ai, architect, dev-senior, ops]
status: beta
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/intelligence/action_targets/base.py
  - Backend Architecture/aether-backend/services/intelligence/action_targets/registry.py
  - Backend Architecture/aether-backend/services/intelligence/routes.py
flags:
  - AETHER_DECISION_RECORDS_ENABLED
  - AETHER_OUTCOME_FEEDBACK_ENABLED
related:
  - ai/decision-outcome-intelligence
  - ai/action-dispatch
  - ai/revenue-metering-events
---

# Integration Actions

Integration Actions let tenants dispatch approved OODA actions into operational systems without leaving the governed recommendation → decision → action → outcome lifecycle.

Supported targets are Slack, webhook, CRM task, marketing automation, ticketing, and agent assist. Placeholder connectors return structured simulated receipts in this phase; they do not call external APIs.

## Registry

`ActionTargetRegistry` exposes target descriptors with supported action types, retry/cancel capability, delivery receipt support, and approval policy notes.

```http
GET /v1/intelligence/action-targets
```

## Integration configuration

Tenants configure target placeholders through:

```http
GET /v1/intelligence/action-integrations
POST /v1/intelligence/action-integrations
PATCH /v1/intelligence/action-integrations/{integration_config_id}
POST /v1/intelligence/webhooks/test
POST /v1/intelligence/webhooks/{integration_config_id}/rotate-secret
```

API responses never return raw secrets. Secrets are represented only by `has_secret` / secret references. Webhook tests are simulated and return the payload that would be delivered.

## Governance

Dispatch requires write permission, tenant ownership of the action, an approved decision, a matching recommendation, and approval metadata for elevated or critical selected actions. Dispatch does not bypass human-in-the-loop controls and does not execute irreversible autonomous work.
