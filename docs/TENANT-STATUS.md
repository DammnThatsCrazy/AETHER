---
title: Tenant System Status
slug: reliability/tenant-status
section: operations
visibility: P
audience: [buyer, ops, architect]
status: beta
since_version: "0.1.0"
source_files:
  - Backend Architecture/aether-backend/services/reliability/routes.py
  - Backend Architecture/aether-backend/services/reliability/tenant_impact.py
  - frontend/aether/src/pages/system-status/system-status-page.tsx
related:
  - reliability/operations
  - reliability/incident-response
canonical_owner: platform@aether
estimated_read_minutes: 4
source_hashes:
  "Backend Architecture/aether-backend/services/reliability/routes.py": "sha256:a28140054a4ffc46654adbf78bec26bca2934ff4d6fdde75c63cfc31adbed2b0"
  "Backend Architecture/aether-backend/services/reliability/tenant_impact.py": "sha256:8a188d25da4ba795efde29071186f35001ce6c9f7717fbdd99ac743abb136318"
  "frontend/aether/src/pages/system-status/system-status-page.tsx": "sha256:6d0e8550d17d6b6ce4e4f95b74e87ac4b28e5690c9ee161922f74b040465b3ba"
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
