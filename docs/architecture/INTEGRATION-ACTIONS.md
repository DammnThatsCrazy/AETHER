---
title: Integration Actions
slug: ai/integration-actions
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: beta
since_version: 0.1.0
source_files: [services/api/intelligence/intelligence/routes.py, services/api/intelligence/intelligence/decision_models.py, services/api/actions/delivery/worker.py, services/api/actions/delivery/adapters/jira.py, services/api/actions/agent/action_delivery_evidence.py]
flags: [AETHER_DECISION_RECORDS_ENABLED, AETHER_OUTCOME_FEEDBACK_ENABLED]
related: [ai/decision-outcome-intelligence]
canonical_owner: platform@aether
estimated_read_minutes: 4
toc_depth: 3
source_hashes:
  "services/api/actions/agent/action_delivery_evidence.py": "sha256:2885ba7a495362dc813263ad3135c967eaa669306d8e88888e838bbbe938a376"
  "services/api/actions/delivery/adapters/jira.py": "sha256:c8d4dcc9e02158e39d7c808b3fb81d3e46abda8547f009be31a1519d7d3dc051"
  "services/api/actions/delivery/worker.py": "sha256:caec7adc3a0025043b5c1567356f075050fdfdb42f1541cb8fac4f10a0e61fc2"
  "services/api/intelligence/intelligence/decision_models.py": "sha256:fa7574a7f99bcebb21ff58d6cd61ffbb761a58b0022b5a247a13387c8c9853d8"
  "services/api/intelligence/intelligence/routes.py": "sha256:389f7099cb4a4fd12c2803bd7b7495258778cdb4f5ce788294c95f7c37073464"
---
# Integration Actions

Integration-ready actions let tenants log governed action targets without forcing irreversible autonomous execution.

## API

`POST /v1/intelligence/actions/integration-ready`

Supported targets: Slack, signed webhook, ticketing (delegates to Linear or Jira), agent-assist. CRM and marketing automation targets require a concrete provider config; they fail closed with `InvalidPayloadError` until configured.

Dispatch reserves an optional idempotency key within the authenticated tenant
and action before calling a connector. Replays return the existing durable
dispatch and do not invoke the connector again. When a Journey or Risk
association was recorded, a replay must supply that same reference and match
the persisted decision/action/recommendation linkage; the association is replayed
as stored, not revalidated as a current decision. A concrete delivered receipt
must contain a real external ID; simulation-shaped receipts are rejected. If a
target adapter is not implemented, the reserved dispatch stays an auditable
`queued` plan and is handed to the canonical delivery worker seam when
available, with `planned: true` and `external_side_effect: false` in the
response. Connector failures remain durable and retryable rather than silently
creating a second dispatch. See [ADR-001](adr-001-canonical-delivery-pipeline.md).

Journey360 and Risk360 read worker delivery evidence through the canonical
intent → job → provider receipt → external-resource link chain. A receipt on
the intelligence dispatch endpoint is not itself that worker-chain evidence.
Tenant-submitted delivery outcomes remain `caller_asserted`; only callback
events whose signature and exact receipt/resource binding were verified are
exposed as verified callbacks. Neither provider delivery evidence nor a
verified callback proves an independently verified external effect.

For Jira deliveries, the worker separately re-resolves the vault credential and
reads the issue back, matching its key, project, and requested title. A durable
verification binds that observation to the exact tenant, dispatch, subject,
intent, job, receipt, provider site, payload digest, and dispatch policy decision.
Journey360 and Risk360 revalidate those bindings before reporting
`provider_resource_readback_verified`. This proves the requested Jira resource
was observed, not a successful business outcome or complete provider coverage.
Other adapters remain unsupported for independent read-back verification.

## Controls

Integration actions require tenant write permission, tenant `dispatch`
permission, an authenticated principal, and an approved decision before
dispatch. Elevated and critical actions still require
`authorization_metadata.approval_id`. The persisted allowed `action.dispatch`
decision is matched to the exact dispatch, tenant, principal, action, target,
selected action, elevation/approval context, and association before Journey360
or Risk360 treats its dispatch read as complete. This records the application
permission decision at dispatch time; it does not prove later connector
execution or an external effect. Every action creates an `ActionFeedback`
record, emits the action lifecycle event, supports later outcome observation,
preserves tenant isolation, and remains auditable.

When the action originated from a finding-backed investigation, its optional
`finding_id` and `investigation_id` links are inherited from the decision and
recommendation for end-to-end audit tracing.

## Audit export readiness

Action dispatch evidence is available through `action_dispatch_audit`, including actions, dispatches, delivery receipts, authorization metadata presence, status transitions, and idempotency keys. Connector secrets remain redacted and tenant-scoped.

## Metering and RevOps

Integration deliveries and premium connector usage should emit usage metering events. Observed value from integration actions can create value-created events for internal invoice preview and expansion analysis.

## Reliability & Operational Resilience

Reliability, SRE, incident response, SLOs, runbooks, and tenant-safe system
status are documented in [Reliability Operations](../operations/RELIABILITY-OPERATIONS.md) and
related docs ([Incident Response](../operations/incident-response.md),
[SLO Tracking](../operations/SLO-TRACKING.md), [SRE Runbooks](../operations/SRE-RUNBOOKS.md),
[Tenant System Status](../operations/TENANT-STATUS.md), [Pipeline Health](../operations/PIPELINE-HEALTH.md),
[Queue & Worker Health](../operations/QUEUE-WORKER-HEALTH.md), [Postmortems](../operations/POSTMORTEMS.md)).
These controls are additive and do not weaken tenant isolation, governance,
auditability, or security. No external SLA or certification is claimed.
