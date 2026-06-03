---
title: OODA & Outcome Usage Dimensions
slug: operations/ooda-usage-dimensions
section: operations
visibility: I
audience: [architect, dev-senior, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# OODA & Outcome Usage Dimensions

Aether meters usage across the full Observe → Orient → Decide → Act → Learn loop
(plus ingestion and connectors), so plans and invoices can price the
intelligence the platform actually produces — not just raw events.

## Metering dimensions

Dimensions are the `MeteringEventType` values recorded via `MeteringService`
(`services/billing/revops.py`). The catalog:

| Dimension | Label | Stage |
| --- | --- | --- |
| `sdk_event_ingested` | SDK events ingested | Ingestion |
| `webhook_ingested` | Webhook events ingested | Ingestion |
| `event_ingested` | Events ingested | Ingestion |
| `connector_sync` | Connector syncs | Ingestion |
| `entity_resolved` | Entities resolved | Identity |
| `graph_operation` | Graph operations | Graph |
| `profile_query` | Profile360 queries | Orient |
| `recommendation_generated` | Recommendations generated | Orient |
| `recommendation_previewed` | Recommendations previewed | Orient |
| `decision_recorded` | Decisions recorded | Decide |
| `confidence_updated` | Confidence updates | Learn |
| `action_logged` | Actions logged | Act |
| `action_dispatched` | Actions dispatched | Act |
| `investigation_opened` | Investigations opened | Orient |
| `outcome_observed` | Outcomes observed | Learn |
| `playbook_run` | Playbook runs | Act |
| `audit_export_generated` | Audit exports generated | Governance |
| `integration_delivery` | Integration deliveries | Act |
| `value_created` | Value-created events | Learn |
| `premium_connector_used` | Premium connector usage | Connectors |
| `deployment_mode_active` | Deployment mode activations | Platform |
| `managed_workflow_triggered` | Managed workflow triggers | Platform |

The six dimensions added in this pass (`recommendation_previewed`,
`confidence_updated`, `investigation_opened`, `connector_sync`,
`webhook_ingested`, `sdk_event_ingested`) extend the original 16 so the OODA
loop and both ingestion paths (SDK and connector/webhook) are fully metered.

## How dimensions are recorded

All dimensions flow through the same idempotent path:
`MeteringService.record_event(UsageMeteringEvent(...))`. Events are
tenant-scoped, secret-sanitized, and deduped by `(source_type, source_id,
event_type)`. Connector/SDK/webhook emission is wired in the connector and
ingestion layers (see [Connectors](CONNECTORS.md) when available). No raw
secrets are ever written to metering metadata.

## Where they surface

- Tenant: Aether **Usage & Plan** (`frontend/aether/src/pages/usage-plan`) shows
  included vs. current usage per dimension.
- Operator: Kyber **Revenue Operations** surfaces usage, entitlements, invoice
  previews, and revenue-leakage signals across dimensions.

See [Outcome Pricing Dimensions](OUTCOME-PRICING-DIMENSIONS.md),
[Rate Limits & Bursts](RATE-LIMITS-AND-BURSTS.md), and
[Pricing Architecture](PRICING-ARCHITECTURE.md).
