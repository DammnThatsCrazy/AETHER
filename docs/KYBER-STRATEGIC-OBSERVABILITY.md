---
title: Kyber Strategic Observability
slug: kyber/strategic-observability
section: kyber
visibility: I
audience: [exec, ops, architect]
status: beta
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/intelligence/routes.py
  - Backend Architecture/aether-backend/services/intelligence/outcome_ledger.py
flags:
  - KYBER_RECOMMENDATION_OBSERVABILITY_ENABLED
related:
  - ai/outcome-ledger
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 3
last_synced_commit: "74086291"
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

## Data boundaries

Kyber may show tenant-level account health to Olympus Labs operators with `admin` permission. Cross-tenant views must remain aggregate, anonymized, or internal operational diagnostics. Raw tenant-private evidence, graph intelligence, and tenant-specific investigation content are not exposed across tenants.

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
[SECURITY-GOVERNANCE-CONTROLS.md](./SECURITY-GOVERNANCE-CONTROLS.md).

## Reliability & Operational Resilience

Reliability, SRE, incident response, SLOs, runbooks, and tenant-safe system
status are documented in [Reliability Operations](RELIABILITY-OPERATIONS.md) and
related docs ([Incident Response](INCIDENT-RESPONSE.md),
[SLO Tracking](SLO-TRACKING.md), [SRE Runbooks](SRE-RUNBOOKS.md),
[Tenant System Status](TENANT-STATUS.md), [Pipeline Health](PIPELINE-HEALTH.md),
[Queue & Worker Health](QUEUE-WORKER-HEALTH.md), [Postmortems](POSTMORTEMS.md)).
These controls are additive and do not weaken tenant isolation, governance,
auditability, or security. No external SLA or certification is claimed.
