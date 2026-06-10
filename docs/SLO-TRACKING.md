---
title: SLO Tracking
slug: reliability/slo-tracking
section: operations
visibility: I
audience: [ops, exec, architect]
status: beta
since_version: "9.0.0"
source_files:
  - Backend Architecture/aether-backend/services/reliability/definitions.py
  - Backend Architecture/aether-backend/services/reliability/service.py
related:
  - reliability/operations
canonical_owner: platform@aether
estimated_read_minutes: 4
last_synced_commit: a64bf52
---
# SLO Tracking

Service Level Objectives are **internal objectives** used to manage reliability.
They are **not** external SLA commitments and must not be presented as such.

## SLO model

| Field | Notes |
|---|---|
| `slo_id` | Stable id |
| `service_key` | Service the SLO measures |
| `metric_key` | Metric being tracked |
| `target` | Objective threshold (floor or ceiling) |
| `window` | `1h` / `24h` / `7d` / `30d` / `90d` |
| `current_value` | Latest observed value (set via API) |
| `status` | `meeting` / `at_risk` / `breached` / `unknown` |
| `error_budget_remaining` | 0..1 fraction of budget left |

## Status computation

`compute_slo_status` classifies metrics as lower-is-better (latency, freshness,
age — `target` is a ceiling) or higher-is-better (availability/ratio — `target`
is a floor). Error budget is the normalized headroom; `< 0` → `breached`,
`< 0.2` → `at_risk`, else `meeting`. `None` current value → `unknown`.

## Initial SLOs

API availability, SDK ingestion latency, event-to-graph mutation latency,
recommendation generation latency, action dispatch delivery latency, outcome
ledger freshness, audit export generation time, billing metering freshness,
Kyber dashboard freshness.

## APIs

- `GET /v1/admin/kyber/reliability/slos`

## Tenant-safe vs internal

SLOs are **internal only**. Tenants never see SLO targets, current values, or
error budgets. No external SLA is implied.

## Known gaps

- `current_value` is set manually via `SLOService.set_current_value`; an
  automatic metric pipeline and burn-rate alerting are planned.

## Rollout notes

- SLOs seed lazily and report `unknown` until a current value is supplied.
