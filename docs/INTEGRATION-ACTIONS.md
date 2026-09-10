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
source_hashes:
  "Backend Architecture/aether-backend/services/intelligence/decision_models.py": "sha256:95d33e7eee251e14114ba3f538f78f32ffe2d1e3cdb9c122ddec7b80086e8e25"
  "Backend Architecture/aether-backend/services/intelligence/routes.py": "sha256:8a705ad12ff7176d486afa586ba3f794da14017b9f9c108a3f9b6313da94884b"
---
# Integration Actions

Integration-ready actions let tenants log governed action targets without forcing irreversible autonomous execution.

## API

`POST /v1/intelligence/actions/integration-ready`

Supported targets: Slack, signed webhook, ticketing (delegates to Linear or Jira), agent-assist. CRM and marketing automation targets require a concrete provider config; they fail closed with `InvalidPayloadError` until configured.

Dispatch reserves an optional idempotency key within the authenticated tenant
and action before calling a connector. Replays return the existing durable
dispatch and cannot invoke an external side effect twice. A concrete delivered
receipt must contain a real external ID; simulation-shaped receipts are
rejected. If a target adapter is not implemented, the reserved dispatch stays
an auditable `queued` plan and is handed to the canonical delivery worker seam
when available, with `planned: true` and `external_side_effect: false` in the
response. Connector failures remain durable and retryable rather than silently
creating a second dispatch. See [ADR-001](architecture/adr-001-canonical-delivery-pipeline.md).

## Controls

Integration actions require an approved decision before queued or executed status. Elevated and critical actions still require `authorization_metadata.approval_id`. Every action creates an `ActionFeedback` record, emits the action lifecycle event, supports later outcome observation, preserves tenant isolation, and remains auditable.

When the action originated from a finding-backed investigation, its optional
`finding_id` and `investigation_id` links are inherited from the decision and
recommendation for end-to-end audit tracing.

## Audit export readiness

Action dispatch evidence is available through `action_dispatch_audit`, including actions, dispatches, delivery receipts, authorization metadata presence, status transitions, and idempotency keys. Connector secrets remain redacted and tenant-scoped.

## Metering and RevOps

Integration deliveries and premium connector usage should emit usage metering events. Observed value from integration actions can create value-created events for internal invoice preview and expansion analysis.

## Reliability & Operational Resilience

Reliability, SRE, incident response, SLOs, runbooks, and tenant-safe system
status are documented in [Reliability Operations](RELIABILITY-OPERATIONS.md) and
related docs ([Incident Response](INCIDENT-RESPONSE.md),
[SLO Tracking](SLO-TRACKING.md), [SRE Runbooks](SRE-RUNBOOKS.md),
[Tenant System Status](TENANT-STATUS.md), [Pipeline Health](PIPELINE-HEALTH.md),
[Queue & Worker Health](QUEUE-WORKER-HEALTH.md), [Postmortems](POSTMORTEMS.md)).
These controls are additive and do not weaken tenant isolation, governance,
auditability, or security. No external SLA or certification is claimed.
