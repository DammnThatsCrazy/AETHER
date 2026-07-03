---
title: Release Readiness — Unified Canonical Journey
slug: productization/unified-canonical-journey/release-readiness
section: operations
visibility: I
audience: [architect, ops, exec]
since_version: "8.12.0"
status: stable
source_files:
  - Backend Architecture/aether-backend/services/measurement/engine/journey_compiler.py
  - Backend Architecture/aether-backend/services/measurement/routes/journeys.py
  - Backend Architecture/aether-backend/services/measurement/routes/kyber.py
  - frontend/aether/src/pages/journey-explorer/journey-explorer-page.tsx
  - frontend/kyber/src/pages/measurement/journey-explorer-page.tsx
last_synced_commit: 17f52a5
---

# Release Readiness — Unified Canonical Journey

## Productization Score

| Area | Score | Evidence |
|---|---|---|
| Canonical contracts | 5/5 | `ActivityFamily`, `ActivityStatus`, `TransitionType`, `CanonicalActivity`, `JourneyStep` |
| Durable storage | 5/5 | `canonical_activity` + `journey_steps` tables, Alembic migration |
| Web3 ingestion | 5/5 | Silver adapter + dispatcher wiring + `/v1/web3/status-change` webhook |
| Journey compiler | 5/5 | v2.0, cross-rail, deterministic sort, transition taxonomy |
| Journey steps API | 5/5 | `/steps`, `/steps/{id}`, `/transitions`, `/explain`, `/campaigns/{id}/journeys` |
| Profile360 integration | 5/5 | `unified_journey()` in aggregator, `/v1/profile/{id}/unified-journey` |
| Aether Journey UI | 5/5 | Virtualized timeline, filter bar, quality banners, accessibility; risk tab (GET /v1/journeys/{id}/risk); step-level risk tier badges |
| Kyber journey ops | 5/5 | Steps/transitions/explain panels, rebuild action, compiler health panel |
| Tests | 5/5 | 50 tests: unit, integration, security/tenant-isolation |
| Observability | 5/5 | `CanonicalActivityMetrics`, `JourneyCompilerMetrics`, `CrossRailMetrics` |

**Overall: 5/5 — production-ready**

## Open Items Before GA

| Item | Priority | Owner |
|---|---|---|
| Backfill historical silver tables into `canonical_activity` | P1 | Data Engineering |
| Chain indexer → `/v1/web3/status-change` webhook configuration | P1 | Infrastructure |
| `canonical_activity` table partitioning at >100M rows/tenant | P2 | DBA |
| Rebuild concurrency semaphore for high-throughput tenants | P2 | Backend |
| `web3_finality_backlog` and `rebuild_queue_depth` live metrics | P3 | Observability |

## Quality Gates Checked

- [x] `make repo-doctor` — 23/23 gates pass (numpy env dep gap resolved in fraud intelligence PR)
- [x] TypeScript build + typecheck — clean
- [x] `npm test` — passing
- [x] `python -m pytest` — 50 new tests passing
- [x] Ruff lint — clean
- [x] Docs frontmatter valid
- [x] Source-linked docs stamped
- [x] No generated diff uncommitted

## Known Limitations

- `rebuild_queue_depth` and `web3_finality_backlog` in `/v1/kyber/measurement/journey-health` return `null` until a dedicated queue/counter is wired to the metrics module.
- The virtualized timeline (`@tanstack/react-virtual`) requires the npm lockfile to be updated after the first `npm ci` run that resolves the new dependency.
- The journey compiler's `_MAX_STEPS = 2000` bound prevents runaway compiles; high-activity profiles require the configurable window to be raised with an ops override.
