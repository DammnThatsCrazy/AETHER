---
title: Reliability Operations
slug: reliability/operations
section: operations
visibility: I
audience: [exec, ops, architect]
status: beta
since_version: "9.0.0"
source_files:
  - Backend Architecture/aether-backend/services/reliability/models.py
  - Backend Architecture/aether-backend/services/reliability/service.py
  - Backend Architecture/aether-backend/services/reliability/routes.py
  - Backend Architecture/aether-backend/services/reliability/tenant_impact.py
  - frontend/kyber/src/pages/reliability/reliability-page.tsx
  - frontend/aether/src/pages/system-status/system-status-page.tsx
related:
  - reliability/sre-runbooks
  - reliability/incident-response
  - reliability/slo-tracking
  - reliability/tenant-status
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
last_synced_commit: "99da74c0"
---
# Reliability Operations

Aether's reliability layer makes the platform **operationally credible for
enterprise and government use** without overclaiming SLAs or certifications. It
is built **additively** on existing health checks, the event bus, repositories,
integration actions, audit exports, billing metering, and Kyber admin systems —
it is **not** a separate product layer.

Two audiences, two strictly-separated surfaces:

| Surface | Audience | Routes | Visibility |
|---|---|---|---|
| Reliability Command Center | Olympus Labs operators (Kyber) | `/v1/admin/kyber/reliability/*`, `/incidents`, `/runbooks`, `/postmortems` | Internal — full detail |
| System Status | Tenants (Aether) | `/v1/status*` | Tenant-safe — single tenant, no infra internals |

## Tenant-safe vs internal visibility

The tenant surface only ever exposes the caller's own workspace and a
**whitelisted** set of fields (see `TenantImpactAnalyzer._safe_incident`). It
**never** exposes: internal queue/worker details, pipeline internals, other
tenants, infrastructure metadata, security-sensitive internals, incident
`internal_notes`, `root_cause`, `affected_services`, `affected_tenants`, or owner
ids. Backend tests assert the absence of these keys on `/v1/status*` payloads.

The internal surface is gated by `_require_kyber_operator`, which delegates
to the canonical fail-closed `require_kyber_operator` gate — a regular tenant
holding only the `admin` permission is not a Kyber operator.

## Implemented reliability controls

- **Service health registry** — 19 services, heartbeat/status/metadata/last-job
  updates, open-incident linkage. (See `PIPELINE-HEALTH.md`, `QUEUE-WORKER-HEALTH.md`.)
- **Pipeline health** — 13 critical pipelines with throughput, latency, error
  rate, retry/dead-letter counts, freshness, and affected-tenant counts.
- **Queue/worker health** — 7 queues with depth, oldest-message age, worker
  counts, retry/dead-letter counts, processing latency (adapter/mock-backed).
- **Incident management** — full lifecycle with internal audit trail and service
  linkage. (See `INCIDENT-RESPONSE.md`.)
- **Runbooks** — 14 seeded operational runbooks plus custom runbook CRUD.
  (See `SRE-RUNBOOKS.md`.)
- **SLO tracking** — 12 internal SLOs with status + error-budget computation.
  (See `SLO-TRACKING.md`.)
- **Tenant impact analysis** — per-tenant impact with tenant-safe and internal
  projections.
- **Kyber Reliability Command Center UI** and **Aether System Status UI**.

## Planned reliability controls

- Live metric ingestion from real queue/worker backends (current queue records
  are adapter/mock-seeded until a real queue abstraction exists).
- Automated incident creation from SLO breaches and health-signal thresholds.
- Paging/alerting integrations and on-call schedules.
- Status-page subscriptions/notifications for tenants.
- Historical SLO trend storage and error-budget burn-rate alerting.

## Models

See dedicated docs for each model:
`PIPELINE-HEALTH.md`, `QUEUE-WORKER-HEALTH.md`, `INCIDENT-RESPONSE.md`,
`SLO-TRACKING.md`, `SRE-RUNBOOKS.md`, `POSTMORTEMS.md`, `TENANT-STATUS.md`.

## Known gaps

- Queue/worker metrics are not yet sourced from a live broker.
- SLO `current_value` must be set via `SLOService.set_current_value` (no
  automatic metric pipeline yet).
- No external SLA/uptime commitments are made or implied anywhere.

## Rollout notes

- All records seed lazily on first read, so dashboards render immediately with
  `unknown`/baseline values in a fresh environment.
- Local/dev uses in-memory repositories; staging/production use asyncpg JSONB
  tables auto-created by `BaseRepository`.
- No external SLA or certification is claimed unless explicitly configured.
