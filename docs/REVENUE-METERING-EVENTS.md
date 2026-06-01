---
title: Revenue Metering Events
slug: ai/revenue-metering-events
section: ai
visibility: I
audience: [ai, architect, dev-senior, ops, exec]
status: beta
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/intelligence/decision_models.py
  - Backend Architecture/aether-backend/services/intelligence/routes.py
  - Backend Architecture/aether-backend/services/admin/kyber_strategic.py
flags:
  - KYBER_RECOMMENDATION_OBSERVABILITY_ENABLED
related:
  - ai/integration-actions
  - ai/kyber-revenue-intelligence
---

# Revenue Metering Events

Revenue metering events are internal records that connect governed action dispatch to future pricing, invoices, enterprise contracts, or value-based packaging. This phase does not integrate with a billing provider.

Metering event types:

- `action_dispatched`
- `integration_delivery`
- `integration_retry`
- `premium_connector_used`
- `managed_workflow_triggered`

Each event stores tenant, action, dispatch, playbook, recommendation, quantity, estimated billable value, and creation timestamp.

Kyber Strategic Observability aggregates these records into integration health, premium connector usage, dispatch success/failure rates, and integration upsell opportunities.
