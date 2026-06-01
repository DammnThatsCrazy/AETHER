---
title: Integration Actions
slug: ai/integration-actions
section: ai
visibility: I
audience: [architect, dev-senior, ops]
status: beta
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/intelligence/routes.py
  - Backend Architecture/aether-backend/services/intelligence/decision_models.py
flags:
  - AETHER_DECISION_RECORDS_ENABLED
  - AETHER_OUTCOME_FEEDBACK_ENABLED
related:
  - ai/decision-outcome-intelligence
canonical_owner: platform@aether
estimated_read_minutes: 4
toc_depth: 3
---
# Integration Actions

Integration-ready actions let tenants log governed action targets without forcing irreversible autonomous execution.

## API

`POST /v1/intelligence/actions/integration-ready`

Initial targets are Slack notification, webhook, CRM task placeholder, marketing automation placeholder, and ticketing placeholder.

## Controls

Integration actions require an approved decision before queued or executed status. Elevated and critical actions still require `authorization_metadata.approval_id`. Every action creates an `ActionFeedback` record, emits the action lifecycle event, supports later outcome observation, preserves tenant isolation, and remains auditable.

## Audit export readiness

Action dispatch evidence is available through `action_dispatch_audit`, including actions, dispatches, delivery receipts, authorization metadata presence, status transitions, and idempotency keys. Connector secrets remain redacted and tenant-scoped.
