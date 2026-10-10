---
title: Release Readiness — Unified Canonical Journey
slug: productization/unified-canonical-journey/release-readiness
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [services/backend/services/measurement/engine/journey_compiler.py, services/backend/services/measurement/routes/journeys.py, services/backend/services/measurement/routes/kyber.py, services/backend/alembic/versions/20261010_economic_operation_journey_refs.py, apps/aether/src/pages/journey-explorer/journey-explorer-page.tsx, apps/kyber/src/pages/measurement/journey-explorer-page.tsx]
source_hashes:
  "apps/aether/src/pages/journey-explorer/journey-explorer-page.tsx": "sha256:0e849243710c8ebac6d61906811ccd02b48f62dac0e4e519ffdecaddbc48b6aa"
  "apps/kyber/src/pages/measurement/journey-explorer-page.tsx": "sha256:c6a5887e51223aee851e1ed4b500f484e183d78d9565d0774819fe2d9093a362"
  "services/backend/alembic/versions/20261010_economic_operation_journey_refs.py": "sha256:78479dca594fb9ac8f2ce19f317de933afae3ed1211d8c0c45120c9b023ea87a"
  "services/backend/services/measurement/engine/journey_compiler.py": "sha256:32bad8c530ae3e357a5820af0e45542611ee4cfb0176c9e2c25c6f2078f6e564"
  "services/backend/services/measurement/routes/journeys.py": "sha256:191c2d0f513a37729ae087d07a71f58230dbffef0693240a8d4047178043694e"
  "services/backend/services/measurement/routes/kyber.py": "sha256:c1676ae3c3dd86f71404f94dfaa08cd7a63772526bf0e7869fc6eed92f5ab0c7"
---

# Release Readiness — Unified Canonical Journey

## Productization Score

| Area | Score | Evidence |
|---|---|---|
| Canonical contracts | 5/5 | `ActivityFamily`, `ActivityStatus`, `TransitionType`, `CanonicalActivity`, `JourneyStep` |
| Durable storage | 5/5 | `canonical_activity` + `journey_steps` tables, Alembic migration |
| Web3 ingestion | 5/5 | Silver adapter + dispatcher wiring + `/v1/web3/status-change` webhook + tenant-scoped SDK transaction verification |
| Journey compiler | 5/5 | v2.0, cross-rail, deterministic sort, transition taxonomy |
| Journey steps API | 5/5 | `/steps`, `/steps/{id}`, `/transitions`, `/explain`, `/economic-operations`, `/campaigns/{id}/journeys` |
| Profile360 integration | 5/5 | `unified_journey()` in aggregator, `/v1/profile/{id}/unified-journey` |
| Aether Journey UI | 5/5 | Virtualized timeline, filter bar, quality banners, accessibility; risk tab (GET /v1/journeys/{id}/risk); step-level risk tier badges; source-linked economic operation evidence with no inferred amount or settlement claim |
| Kyber journey ops | 5/5 | Steps/transitions/explain panels, rebuild action, compiler health panel, and per-transaction RPC verification action |
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
| Configure a tenant RPC endpoint and capture controlled EVM/SVM execution, reorg, and correction evidence | P1 | Infrastructure / Measurement Operations |
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
- The journey compiler applies a fixed `_MAX_JOURNEY_STEPS = 2000` input limit. Raising it requires a code change; this source does not expose an ops override.
- The SDK verification action checks EVM receipts with a server-set confirmation threshold and SVM transactions at finalized commitment. It records chain execution only; payment settlement remains owned by the relevant payment source. Reorg and provider-specific production behavior still require controlled release evidence.
- Source classification repair is tenant-scoped and durable, but large repair batches can create attribution recompute load that requires operator monitoring.
