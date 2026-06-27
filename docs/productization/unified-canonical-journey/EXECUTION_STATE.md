---
title: Unified Web2/Web3 Canonical Journey — Execution State
slug: productization/unified-canonical-journey/execution-state
section: operations
visibility: I
audience: [architect, ops, exec]
since_version: "8.12.0"
status: beta
source_files:
  - Backend Architecture/aether-backend/services/measurement/engine/journey_compiler.py
  - Backend Architecture/aether-backend/services/measurement/repositories/activity_repo.py
  - Backend Architecture/aether-backend/services/measurement/repositories/journey_step_repo.py
  - Backend Architecture/aether-backend/services/measurement/silver_adapters.py
  - Backend Architecture/aether-backend/alembic/versions/20260627_canonical_activity.py
last_synced_commit: 6c7de2c
---

# Unified Web2/Web3 Canonical Journey — Execution State

## Phase Completion Status

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Pre-flight / baseline | ✅ Complete |
| 1 | Migration + contracts | ✅ Complete |
| 2 | Activity repo + silver adapters + base projector | ✅ Complete |
| 3 | Extended journey compiler v2.0 | ✅ Complete |
| 4 | API extensions (steps, transitions, explain, rebuild) | ✅ Complete |
| 5 | Profile360 integration (unified_journey method) | ✅ Complete |
| 6 | Aether customer UI (journey explorer page + components) | ✅ Complete |
| 7 | Kyber operator UI (health panel + rebuild action + steps panel) | ✅ Complete |
| 8 | Tests (unit + integration + security) | ✅ Complete |
| 9 | Observability (metrics module) | ✅ Complete |
| 10 | Documentation | ✅ Complete |

## Key Deliverables

- **`canonical_activity`** table: single source of truth for all cross-rail activity
- **`journey_steps`** table: first-class individually queryable ordered steps
- **JourneyCompiler v2.0**: consumes all activity families, deterministic sort, cross-rail transition taxonomy
- **Silver adapters**: 11 adapter functions covering all silver tables → canonical_activity
- **API**: `/v1/journeys/{id}/steps`, `/v1/journeys/{id}/transitions`, `/v1/journeys/{id}/explain`, `/v1/journeys/{id}/rebuild`
- **Profile360**: `GET /v1/profile/{user_id}/unified-journey`
- **Aether UI**: `JourneyExplorerPage`, `JourneyTimeline`, `JourneyStepCard`, `JourneyFilterBar`, `JourneyTransitionBadge`
- **Kyber UI**: Extended `JourneyExplorerPage` with steps panel, transitions panel, explain panel, rebuild action
- **Tests**: 6 test files covering all scenarios including tenant isolation
- **Metrics**: `canonical_activities_ingested_total`, `journey_compile_duration_seconds`, `cross_rail_transition_count`, `web3_reorg_corrections_total`, `late_event_insertions_total`

## Pre-existing Failures (not in scope)

- `make repo-doctor` ML manifest fails: `No module named 'numpy'` — pre-existing, unrelated to this work
