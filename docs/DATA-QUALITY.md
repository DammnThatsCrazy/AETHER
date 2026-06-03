---
title: Data Quality & Intelligence Quality
slug: data/data-quality
section: data
visibility: I
audience: [ai, architect, dev-senior, ops]
status: beta
since_version: "8.9.0"
flags:
  - AETHER_DATA_QUALITY_ENABLED
  - KYBER_INTELLIGENCE_QUALITY_ENABLED
canonical_owner: platform@aether
estimated_read_minutes: 6
---

# Data Quality & Intelligence Quality

Graph-native data-quality, drift detection, and intelligence reliability for the
Aether platform. Tenants see the health of their own intelligence pipeline;
Olympus operators (Kyber) see aggregate quality and drift across all tenants.

This system is additive and reads from existing signals (ingestion, identity
resolution, graph mutation, Profile 360, recommendations, outcomes, playbooks).
It is deterministic in local/mock mode, so dashboards render without external
services, and exposes `report_*` adapters for live telemetry in deployment.

## Feature flags

| Flag | Default | Effect |
| --- | --- | --- |
| `AETHER_DATA_QUALITY_ENABLED` | `false` | Mounts tenant `/v1/data-quality/*` routes |
| `KYBER_INTELLIGENCE_QUALITY_ENABLED` | `false` | Mounts Kyber `/v1/admin/kyber/intelligence-quality/*` routes |

Both default off. Routes mount only when enabled (see `config/settings.py`
`DataQualityConfig` and the conditional mount in `main.py`).

## Intelligence Quality Score

`IntelligenceQualityScore` rolls up eight normalized (0..1) dimension scores into
an `overall_intelligence_quality_score` with a status band
(`healthy`/`watch`/`degraded`/`critical`):

- event quality, schema stability, identity resolution, graph quality,
  Profile 360 quality, recommendation quality, outcome-feedback quality,
  playbook quality.

## Tenant routes (single-tenant, tenant-safe)

`GET /v1/data-quality/{overview,events,schema,identity,graph,profile,recommendations,outcomes,playbooks}`

Each returns the tenant's own dimension report. Tenant overview never surfaces
platform-wide drift internals or other tenants.

## Kyber routes (operator-gated, aggregate-only)

`GET /v1/admin/kyber/intelligence-quality/{overview,tenants,drift-events,schema-drift,identity,graph,recommendations,outcomes,playbooks,contamination}`
plus `POST .../drift-events/{id}/acknowledge` and `POST .../drift-events/{id}/resolve`.

Kyber views are aggregate-only and never expose raw tenant-private payloads.
Access requires the fail-closed Olympus operator gate; mutations additionally
require the `admin` permission.

## Isolation & escalation

Critical `tenant_data_contamination` drift escalates into the Security &
Governance audit ledger (`services/security/audit_ledger.py`) rather than being
silently surfaced. No secrets are written to drift metadata — the ledger
sanitizes metadata before persistence.

## Related systems

See [Drift Detection](DRIFT-DETECTION.md),
[Graph Intelligence Reliability](GRAPH-INTELLIGENCE-RELIABILITY.md),
[Tenant Data Contamination](TENANT-DATA-CONTAMINATION.md), and
[Live Telemetry Wiring](LIVE-TELEMETRY-WIRING.md).
