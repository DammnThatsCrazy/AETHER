---
title: Incident Response
slug: reliability/incident-response
section: operations
visibility: I
audience: [ops, exec, architect]
status: beta
since_version: "9.0.0"
source_files:
  - Backend Architecture/aether-backend/services/reliability/service.py
  - Backend Architecture/aether-backend/services/reliability/routes.py
related:
  - reliability/operations
  - reliability/sre-runbooks
  - reliability/postmortems
canonical_owner: platform@aether
estimated_read_minutes: 5
last_synced_commit: 57bf28c
---
# Incident Response

`IncidentService` manages the full incident lifecycle and maintains an internal
audit trail for every change.

## Severity model

| Severity | Meaning |
|---|---|
| `sev1` | Critical, broad customer impact / data or security risk |
| `sev2` | Major degradation, significant customer impact |
| `sev3` | Partial/limited impact |
| `sev4` | Minor / informational |

## Status lifecycle

`open → investigating → mitigating → resolved → postmortem_pending → closed`

`resolve` stamps `resolved_at` automatically. Reaching `resolved`/`closed`
detaches the incident from its services' `open_incident_ids`.

## Capabilities

create · update status · assign owner · link affected services/tenants/
pipelines/modules · link runbook · add mitigation steps · resolve · mark
postmortem pending · close.

## Audit events

Every create/update writes an internal entry via `IncidentAuditRepository`
(`reliability_incident_audit`) and logs it. Audit writes are best-effort
(guarded) and never break the incident flow. The audit trail is internal only
and returned with `GET /v1/admin/kyber/incidents/{incident_id}`.

## APIs

- `GET /v1/admin/kyber/incidents` (optional `?status=`)
- `POST /v1/admin/kyber/incidents`
- `GET /v1/admin/kyber/incidents/{incident_id}`
- `PATCH /v1/admin/kyber/incidents/{incident_id}`

## Tenant-safe vs internal

Tenants see incidents only if they appear in `affected_tenants`, and only via the
whitelisted tenant-safe projection (`incident_id`, `title`, `status`,
`severity`, `customer_impact`, timestamps). `internal_notes`, `root_cause`,
`affected_services`, `affected_tenants`, and owner ids are **never** exposed to
tenants. This is enforced and tested.

## Known gaps

- Incidents are created manually; auto-creation from SLO/health breaches is
  planned.

## Rollout notes

- Service linkage is kept consistent automatically when `affected_services`
  changes on update.
