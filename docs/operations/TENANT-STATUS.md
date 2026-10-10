---
title: Tenant System Status
slug: reliability/tenant-status
section: operations
visibility: P
audience: [buyer, ops, architect]
status: beta
since_version: "0.1.0"
source_files:
  - services/api/governance/reliability/routes.py
  - services/api/governance/reliability/tenant_impact.py
  - apps/aether-web/src/pages/system-status/system-status-page.tsx
related:
  - reliability/operations
  - reliability/incident-response
canonical_owner: platform@aether
estimated_read_minutes: 4
source_hashes:
  "apps/aether-web/src/pages/system-status/system-status-page.tsx": "sha256:6d0e8550d17d6b6ce4e4f95b74e87ac4b28e5690c9ee161922f74b040465b3ba"
  "services/api/governance/reliability/routes.py": "sha256:aa8f7b1739acbda7065e85fd6c9a1e60805e542d4f60563adf3010ed7f35ee54"
  "services/api/governance/reliability/tenant_impact.py": "sha256:7df9e077f7672c7ccd4d2cdd537c411fb84217a1fac6bb37dd54bb8ee7b509ac"
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

`TenantStatusSummary` — see `services/api/governance/reliability/models.py`. Overall status is
derived from active incident count + data freshness.

## Known gaps

- No tenant notifications/subscriptions yet (planned).

## Rollout notes

- Tenant-safe incident projection is enforced by a field whitelist and covered by
  no-leakage backend tests.
