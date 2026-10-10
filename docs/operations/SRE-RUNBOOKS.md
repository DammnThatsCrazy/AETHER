---
title: SRE Runbooks
slug: reliability/sre-runbooks
section: operations
visibility: I
audience: [ops, architect]
status: beta
since_version: "0.1.0"
source_files:
  - services/api/governance/reliability/definitions.py
  - services/api/governance/reliability/service.py
related:
  - reliability/operations
  - reliability/incident-response
canonical_owner: platform@aether
estimated_read_minutes: 5
source_hashes:
  "services/api/governance/reliability/definitions.py": "sha256:c8fd781bb882c1306acf959751c9c4b7535227bc67544d6e41c4d72b6a33728e"
  "services/api/governance/reliability/service.py": "sha256:71fe39c503316a915a02f154dececd6385e7e07ed074ddea7ddb24915551d20c"
---
# SRE Runbooks

Operational runbooks are reusable response procedures for known failure classes.
They are seeded as static definitions (`RUNBOOK_DEFINITIONS`) and editable via
the Kyber admin API. Custom runbooks can also be created.

## Runbook model

| Field | Notes |
|---|---|
| `runbook_id` | Stable id (seeded ids prefixed `rb_`) |
| `title` | Human-readable name |
| `incident_type` | Service/category the runbook applies to |
| `severity_hint` | `sev1`..`sev4` default severity |
| `detection_signals` | What triggers this runbook |
| `diagnostic_steps` | How to confirm/diagnose |
| `mitigation_steps` | How to mitigate/recover |
| `escalation_paths` | Who to escalate to, in order |
| `customer_comms_template` | Optional tenant-safe comms text |
| `postmortem_required` | Whether a postmortem is mandatory |

## Seeded runbooks

`rb_sdk_ingestion_degraded`, `rb_event_schema_validation_spike`,
`rb_identity_resolution_failure`, `rb_graph_mutation_backlog`,
`rb_recommendation_generation_failure`, `rb_decision_action_lifecycle_failure`,
`rb_action_dispatch_failure`, `rb_outcome_feedback_failure`,
`rb_audit_export_failure`, `rb_billing_metering_failure`,
`rb_security_audit_event_failure`, `rb_kyber_dashboard_degraded`,
`rb_aether_tenant_app_degraded`, `rb_semantic_classification_degraded`.

## APIs

- `GET /v1/admin/kyber/runbooks`
- `POST /v1/admin/kyber/runbooks`
- `PATCH /v1/admin/kyber/runbooks/{runbook_id}`

## Tenant-safe vs internal

Runbooks are **internal only**. The only tenant-facing element is the optional
`customer_comms_template`, which is surfaced via incident `customer_impact`
messaging — never the diagnostic/mitigation/escalation content.

## Known gaps

- No automatic runbook selection from detection signals yet (manual linkage via
  incident `runbook_id`).

## Rollout notes

- Seeded runbooks are idempotent; editing a seeded runbook persists the edited
  copy. New seeds are added only when missing.
