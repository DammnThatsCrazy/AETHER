---
title: Incident Response
slug: ops-incident-response
section: operations
visibility: I
audience: [ops, architect, security]
status: experimental
since_version: "0.1.0"
source_files:
  - services/api/governance/reliability/models.py
  - services/api/governance/reliability/routes.py
  - services/api/governance/reliability/service.py
  - services/api/governance/reliability/tenant_impact.py
related: [reliability/operations, reliability/sre-runbooks, reliability/postmortems]
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 3
---

# Incident Response

This runbook describes the incident record and response workflow available in
Kyber. It is an operator workflow, not a paging service or a declaration of
response-time commitments. Follow the organization’s current on-call and
security escalation policy alongside these steps.

## Severity

The incident API accepts these levels:

| Severity | Meaning |
|---|---|
| `sev1` | Critical, broad customer impact, data loss, or security risk |
| `sev2` | Major degradation or significant customer impact |
| `sev3` | Partial or limited impact |
| `sev4` | Minor or informational |

The service stores the selected severity; it does not enforce acknowledgement
deadlines or page responders.

## Incident lifecycle

`open → investigating → mitigating → resolved → postmortem_pending → closed`

An incident can be created in `open` or another supported status. The API does
not enforce this exact transition sequence. Moving an incident to `resolved`
automatically records `resolved_at` if one has not already been set. Moving it
to `resolved` or `closed` removes it from the affected services’ open-incident
lists. Changing `affected_services` keeps those lists in sync.

## Response procedure

1. **Confirm and scope the signal.** Check `/v1/health`, the Kyber reliability
   overview, affected pipeline or service health, and the applicable
   [SRE runbook](SRE-RUNBOOKS.md). Record what is observed and when. A dashboard
   value marked unknown or unverified is not evidence of healthy operation.
   For agent telemetry, record the tenant, deployment, source run/event
   reference, and observation time; use the
   [Operations Runbook](OPERATIONS-RUNBOOK.md) for projection and graph checks.
2. **Open an incident in Kyber.** Create a record with a concise title,
   severity, observed impact, affected services and tenants, owner, and the
   relevant runbook. The create route is operator-gated.
3. **Investigate and contain.** Set the status to `investigating`, record the
   known facts and customer impact, and use the linked runbook for diagnosis
   and approved containment steps. Record each mitigation in `mitigation_steps`
   and update the incident as evidence changes.
4. **Restore and resolve.** Confirm service recovery using the relevant health
   and customer-impact evidence. Set status to `resolved`; the backend stamps
   `resolved_at` and detaches the incident from affected services’ open lists.
5. **Review and close.** If a postmortem is required, set status to
   `postmortem_pending`, create the postmortem record, and complete its review
   using the [postmortem workflow](POSTMORTEMS.md). Close the incident after
   required follow-up is recorded.

## Kyber operator API

All incident management routes require the canonical Kyber operator gate. A
tenant’s ordinary `admin` permission is not sufficient.

| Method and route | Purpose |
|---|---|
| `GET /v1/admin/kyber/incidents` | List incidents; supports an optional `status` filter |
| `POST /v1/admin/kyber/incidents` | Create an incident |
| `GET /v1/admin/kyber/incidents/{incident_id}` | Read incident details and its internal audit trail |
| `PATCH /v1/admin/kyber/incidents/{incident_id}` | Update status, owner, impact, notes, services, or mitigation steps |

The request model supports title, severity, status, affected services, tenants,
pipelines and modules, detection time, owner, runbook, summary, customer impact,
internal notes, root cause, and mitigation steps. For runbook and postmortem
management, see the routes and procedures documented in
[SRE Runbooks](SRE-RUNBOOKS.md) and [Postmortems](POSTMORTEMS.md).

## Audit and tenant visibility

Incident changes attempt to write an internal audit entry with the actor,
action, details, and timestamp. Audit persistence is best-effort: a failed
audit write is logged and does not block the incident update. Treat the audit
trail as an operational record, not as a tamper-proof audit ledger.

Tenants can read only their own status projection through
`GET /v1/status/incidents`. It exposes a whitelist of incident ID, title,
status, severity, customer impact, and timestamps. Internal notes, root cause,
affected services, affected-tenant lists, owner IDs, and cross-tenant details
are not included in that projection.

## Current limits

- Incident creation from SLO breaches or health thresholds, paging, and
  on-call schedule integration are not provided by this incident API.
- No response-time target is encoded in the severity model.
- Audit writes are best-effort, as described above.
- This workflow does not establish an external SLA, security certification, or
  production incident-response exercise.

See [Reliability Operations](RELIABILITY-OPERATIONS.md) for the broader
operator and tenant status surfaces.
