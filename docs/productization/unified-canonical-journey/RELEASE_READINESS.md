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
last_synced_commit: "22c9879"
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
| Source evidence | 5/5 | Versioned source classification, eligibility filtering, verified referral provenance, and operator repair controls |
| Tests | 5/5 | 57 core journey tests: unit, integration, security/tenant-isolation, and typed-identity collision coverage |
| Observability | 5/5 | `CanonicalActivityMetrics`, `JourneyCompilerMetrics`, `CrossRailMetrics` |

**Readiness evidence: 5/5 for the implemented surfaces.** This score is not a
release certification. GA still depends on the open operational items below
and a passing canonical `make release-gate` scorecard for the release candidate.

## Open Items Before GA

| Item | Priority | Owner |
|---|---|---|
| Backfill historical silver tables into `canonical_activity` | P1 | Data Engineering |
| Chain indexer → `/v1/web3/status-change` webhook configuration | P1 | Infrastructure |
| `canonical_activity` table partitioning at >100M rows/tenant | P2 | DBA |
| Rebuild concurrency semaphore for high-throughput tenants | P2 | Backend |
| Run tenant-scoped source-classification repair and validate recomputed-run reconciliation | P1 | Measurement Operations |
| `web3_finality_backlog` and `rebuild_queue_depth` live metrics | P3 | Observability |

## Quality Gates Checked

- [x] `make repo-doctor` — 23/23 gates pass (numpy env dep gap resolved in fraud intelligence PR)
- [x] TypeScript build + typecheck — clean
- [x] `npm test` — passing
- [x] Core journey suite — 57 tests collected; exact release-candidate results must be recorded by the release gate
- [x] Ruff lint — clean
- [x] Docs frontmatter valid
- [x] Source-linked docs stamped
- [x] No generated diff uncommitted

## Known Limitations

- `rebuild_queue_depth` and `web3_finality_backlog` in `/v1/kyber/measurement/journey-health` return `null` until a dedicated queue/counter is wired to the metrics module.
- The virtualized timeline (`@tanstack/react-virtual`) requires the npm lockfile to be updated after the first `npm ci` run that resolves the new dependency.
- The journey compiler's `_MAX_STEPS = 2000` bound prevents runaway compiles; high-activity profiles require the configurable window to be raised with an ops override.
- Source classification repair is tenant-scoped and durable, but large repair batches can create attribution recompute load that requires operator monitoring.
