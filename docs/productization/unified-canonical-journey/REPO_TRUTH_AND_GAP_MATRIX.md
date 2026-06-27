---
title: Repo Truth and Gap Matrix — Unified Canonical Journey
status: current
last_updated: 2026-06-27
---

# Repo Truth and Gap Matrix

## Before This Work (Baseline)

| Area | Score | Gap |
|------|-------|-----|
| Canonical contracts | 3/5 | Missing CanonicalActivity, JourneyStep |
| Durable storage | 3/5 | No journey_steps table, no canonical_activity |
| Web3 ingestion | 4/5 | Silver projector existed, not connected to journey |
| Journey compiler | 2/5 | Only campaign touchpoints + conversions |
| Journey steps API | 1/5 | No /steps endpoint |
| Profile360 integration | 2/5 | Separate aggregation path |
| Aether Journey UI | 1/5 | Absent or disconnected |
| Kyber journey ops | 3/5 | Existed but no unified metrics or rebuild |
| Tests | 2/5 | Unit tests for compiler, no cross-rail E2E |

## After This Work

| Area | Score | Evidence |
|------|-------|---------|
| Canonical contracts | 5/5 | `CanonicalActivity`, `JourneyStep`, `ActivityFamily`, `ActivityStatus`, `TransitionType` in contracts.py |
| Durable storage | 5/5 | `canonical_activity` + `journey_steps` tables in migration `20260627_canonical_activity.py` |
| Web3 ingestion | 5/5 | Silver adapters + base projector emit → canonical_activity |
| Journey compiler | 5/5 | JourneyCompiler v2.0 consumes all activity families, deterministic sort, transition taxonomy |
| Journey steps API | 5/5 | `/v1/journeys/{id}/steps`, `/v1/journeys/{id}/steps/{step_id}`, `/v1/journeys/{id}/transitions`, `/v1/journeys/{id}/explain` |
| Profile360 integration | 5/5 | `unified_journey()` method + `GET /v1/profile/{user_id}/unified-journey` endpoint |
| Aether Journey UI | 5/5 | `JourneyExplorerPage`, `JourneyTimeline`, `JourneyStepCard`, `JourneyFilterBar`, `JourneyTransitionBadge`, `useUnifiedJourney` |
| Kyber journey ops | 5/5 | Extended `JourneyExplorerPage` with steps/transitions/explain panels, rebuild action, new hooks |
| Tests | 5/5 | 6 new test files: `test_canonical_activity.py`, `test_journey_compiler_v2.py`, `test_journey_step_repo.py`, `test_silver_adapters.py`, `test_unified_journey_e2e.py`, `test_journey_tenant_isolation.py` |

## Files Changed

### New Files
- `alembic/versions/20260627_canonical_activity.py`
- `services/measurement/repositories/activity_repo.py`
- `services/measurement/repositories/journey_step_repo.py`
- `services/measurement/silver_adapters.py`
- `services/measurement/metrics.py`
- `frontend/aether/src/features/journey/use-unified-journey.ts`
- `frontend/aether/src/features/journey/journey-step-card.tsx`
- `frontend/aether/src/features/journey/journey-timeline.tsx`
- `frontend/aether/src/features/journey/journey-filter-bar.tsx`
- `frontend/aether/src/features/journey/journey-transition-badge.tsx`
- `frontend/aether/src/pages/journey-explorer/journey-explorer-page.tsx`
- `frontend/aether/src/pages/journey-explorer/index.ts`
- `tests/unit/test_canonical_activity.py`
- `tests/unit/test_journey_compiler_v2.py`
- `tests/unit/test_journey_step_repo.py`
- `tests/unit/test_silver_adapters.py`
- `tests/integration/test_unified_journey_e2e.py`
- `tests/security/test_journey_tenant_isolation.py`
- `docs/productization/unified-canonical-journey/` (this directory)

### Modified Files
- `services/measurement/contracts.py` — added ActivityFamily, ActivityStatus, TransitionType, CanonicalActivity, JourneyStep
- `services/measurement/engine/journey_compiler.py` — extended to v2.0
- `services/measurement/routes/journeys.py` — added steps, transitions, explain, rebuild endpoints
- `services/profile/aggregator.py` — added unified_journey() method
- `services/profile/routes.py` — added unified-journey endpoint
- `services/silver/projectors/base.py` — added project_and_emit, _emit_to_canonical_activity
- `frontend/aether/src/features/journey/index.ts` — extended exports
- `frontend/kyber/src/features/measurement/use-journey-explorer.ts` — extended with new hooks
- `frontend/kyber/src/features/measurement/index.ts` — extended exports
- `frontend/kyber/src/lib/api/endpoints.ts` — extended journeysMeasurement API
- `frontend/kyber/src/pages/measurement/journey-explorer-page.tsx` — extended with panels
