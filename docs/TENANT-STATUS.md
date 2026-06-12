---
title: Tenant System Status
slug: reliability/tenant-status
section: operations
visibility: P
audience: [buyer, ops, architect]
status: beta
since_version: "9.0.0"
source_files:
  - Backend Architecture/aether-backend/services/reliability/routes.py
  - Backend Architecture/aether-backend/services/reliability/tenant_impact.py
  - frontend/aether/src/pages/system-status/system-status-page.tsx
related:
  - reliability/operations
  - reliability/incident-response
canonical_owner: platform@aether
estimated_read_minutes: 4
last_synced_commit: 24892a7
---
# Tenant System Status

Tenants get a safe, scoped view of their own workspace health in Aether's
**System Status** page. It exposes only the calling tenant's data and never any
internal infrastructure detail.

## What tenants can see

- Tenant-safe overall status
- Data freshness and recommendation freshness
- Outcome capture status
- Integration status
- Audit export status
- Active and resolved **tenant-impacting** incidents (whitelisted fields)

## What tenants can never see

Internal queue/worker details, pipeline internals, other tenants, infrastructure
metadata, security-sensitive internals, incident `internal_notes`, `root_cause`,
`affected_services`, `affected_tenants`, or owner ids.

## APIs (tenant-scoped, `require_permission("read")`)

- `GET /v1/status` — overall tenant status summary
- `GET /v1/status/incidents` — `{ active, resolved }` tenant-impacting incidents
- `GET /v1/status/data-freshness` — freshness/recommendation/outcome/audit status
- `GET /v1/status/integrations` — integration health

All routes resolve the tenant from the auth context (`request.state.tenant`) and
are strictly single-tenant. No cross-tenant data is reachable.

## Model

`TenantStatusSummary` — see `services/reliability/models.py`. Overall status is
derived from active incident count + data freshness.

## Known gaps

- No tenant notifications/subscriptions yet (planned).

## Rollout notes

- Tenant-safe incident projection is enforced by a field whitelist and covered by
  no-leakage backend tests.
