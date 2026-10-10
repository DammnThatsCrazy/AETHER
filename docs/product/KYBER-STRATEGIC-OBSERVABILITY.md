---
title: Kyber Strategic Observability
slug: kyber/strategic-observability
section: operations
visibility: I
audience: [buyer, ops, architect]
status: beta
since_version: 0.1.0
source_files: [services/api/intelligence/intelligence/routes.py, services/api/governance/admin/routes.py, services/api/intelligence/intelligence/outcome_ledger.py]
flags: []
related: [ai/outcome-ledger]
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 3
source_hashes:
  "services/api/governance/admin/routes.py": "sha256:448866155ff0ffee0857e0843e3ac9c25dec4c32a9a1c30ba1b749e3eb4c168c"
  "services/api/intelligence/intelligence/outcome_ledger.py": "sha256:8edf9b6a8db71127202f8225cb8b03330eef96f058ae555eb38a7a576cdbf206"
  "services/api/intelligence/intelligence/routes.py": "sha256:46f4df5f21914056a91810cb1c0a490183ed144e99a9568b8aedf170f3b05e29"
---
# Kyber Strategic Observability

Kyber strategic observability uses backend aggregate endpoints to show Olympus Labs operators which tenants are receiving value, which loops are broken, and which recommendation families or playbooks are performing.

## APIs

- `GET /v1/admin/kyber/recommendation-health`
- `GET /v1/admin/kyber/tenant-value-health`
- `GET /v1/admin/kyber/outcome-capture-health`
- `GET /v1/admin/kyber/playbook-performance`
- `GET /v1/admin/kyber/model-confidence-drift`
- `GET /v1/admin/kyber/vertical-solution-signals`
- `GET /v1/admin/kyber/expansion-opportunities`

`recommendation-health` and `expansion-opportunities` are served by `services/api/intelligence/intelligence/routes.py`. The other five are served by `services/api/governance/admin/routes.py` and accept a `window` parameter; an older copy of each in `services/api/intelligence/intelligence/routes.py` was shadowed by it and is deleted.

## Data boundaries

Kyber may show tenant-level account health to Olympus Labs operators with `admin` permission. Cross-tenant views must remain aggregate, anonymized, or internal operational diagnostics. Raw tenant-private evidence, graph intelligence, and tenant-specific investigation content are not exposed across tenants.

The aggregate routes also apply the graph boundary before capping results:
neighbours are accepted only when their normalized `tenantId`/`tenant_id`
ownership marker matches the requested tenant. Missing ownership is not treated
as a wildcard, and action-delivery metrics distinguish queued plans and failed
connectors from provider-confirmed delivery.

## Packaging command extensions

Kyber now includes enterprise/government packaging and deployment readiness command views: solution packages, package detail, package readiness, deployment modes, deployment readiness, audit export health, and tenant-package fit. Government entries are planning tracks only and do not claim certification.


## GTM, pricing, and sales readiness
Kyber now includes internal GTM surfaces for pricing architecture, materials catalog, buyer personas, ROI calculator definitions, and sales readiness aggregation. These surfaces support Olympus Labs sales execution without changing Aether tenant-facing architecture.

## Security & Governance Command Center
Kyber now includes a Security & Governance Command Center with nine views:
Security Overview, Policy Decision Log, Audit Event Explorer, Tenant Isolation
Dashboard, Operator Access Dashboard, Break-Glass Access Board, Data Retention
Dashboard, Data Request Queue, and Governance Evidence Packs. These are operator
surfaces under `/v1/admin/kyber/security/*` and are **aggregate-only** for
cross-tenant data — a single tenant's private records require an assigned role or
an approved break-glass grant. See
[SECURITY-GOVERNANCE-CONTROLS.md](../operations/SECURITY-GOVERNANCE-CONTROLS.md).

## Reliability & Operational Resilience

Reliability, SRE, incident response, SLOs, runbooks, and tenant-safe system
status are documented in [Reliability Operations](../operations/RELIABILITY-OPERATIONS.md) and
related docs ([Incident Response](../operations/INCIDENT-RESPONSE.md),
[SLO Tracking](../operations/SLO-TRACKING.md), [SRE Runbooks](../operations/SRE-RUNBOOKS.md),
[Tenant System Status](../operations/TENANT-STATUS.md), [Pipeline Health](../operations/PIPELINE-HEALTH.md),
[Queue & Worker Health](../operations/QUEUE-WORKER-HEALTH.md), [Postmortems](../operations/POSTMORTEMS.md)).
These controls are additive and do not weaken tenant isolation, governance,
auditability, or security. No external SLA or certification is claimed.
