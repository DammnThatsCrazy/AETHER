---
title: Live Telemetry Wiring
slug: operations/live-telemetry-wiring
section: operations
visibility: I
audience: [architect, dev-senior, ops]
status: beta
since_version: "8.9.0"
flags:
  - AETHER_DATA_QUALITY_ENABLED
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# Live Telemetry Wiring

Readiness signals across onboarding, customer success, billing/revops,
reliability, and data quality read from real internal signals where data exists,
while preserving local mock/dev mode. Nothing requires external services to run
locally.

## Principles

- **Flag-guarded with in-memory fallback.** Each surface degrades gracefully to
  deterministic local values when live signals are unavailable.
- **Adapter interfaces.** Where no real stream exists yet, services expose
  `report_*` adapters (e.g. reliability `pipeline.report`, data-quality
  `report_score` / `detect_contamination`) so deployment telemetry can push real
  values without changing the read API.
- **Governance coupling is live.** Critical contamination detected by data
  quality escalates immediately into the Security audit ledger.

## Where telemetry is wired

| Surface | Live signal | Fallback |
| --- | --- | --- |
| Onboarding readiness | required events, graph activation, recommendation/playbook readiness | template defaults |
| Customer success | usage, decision/action/outcome rates, adoption, health/expansion/renewal scores | seeded scores |
| Billing / RevOps | usage summaries feed invoice previews; provider sync status | internal usage summaries |
| Reliability | service/pipeline/queue health, incidents, SLOs, tenant impact | seeded registries |
| Data quality | per-dimension monitors, drift, contamination | deterministic baselines |

## Local vs deployment

Local mocked mode uses MSW (frontends) and in-memory repositories (backend).
Deployment uses env-driven API URLs and the same adapters backed by real streams.
See [Local Development](LOCAL-DEVELOPMENT.md) and
[Deployment & Hosting Readiness](DEPLOYMENT-HOSTING-READINESS.md).
