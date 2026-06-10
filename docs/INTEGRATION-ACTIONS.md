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
last_synced_commit: a64bf52
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
