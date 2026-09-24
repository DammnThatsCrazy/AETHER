---
title: Unified Web2/Web3 Canonical Journey — Execution State
slug: productization/unified-canonical-journey/execution-state
section: operations
visibility: I
audience: [architect, ops, buyer]
status: beta
since_version: 0.1.0
source_files: [services/backend/services/measurement/engine/journey_compiler.py, services/backend/services/measurement/repositories/activity_repo.py, services/backend/services/measurement/repositories/journey_step_repo.py, services/backend/services/measurement/silver_adapters.py, services/backend/alembic/versions/20260627_canonical_activity.py, services/backend/alembic/versions/20260725_ai_referral_attribution.py]
source_hashes:
  "services/backend/alembic/versions/20260627_canonical_activity.py": "sha256:aa34efcf5f337e4430e6727001ee26ca8d657b5d6be9ca7de85b7f151ee668d8"
  "services/backend/alembic/versions/20260725_ai_referral_attribution.py": "sha256:09bcc2502136159d1b50a74181c1d06a7eed30c57ffc9c15da6e900776196189"
  "services/backend/services/measurement/engine/journey_compiler.py": "sha256:53c760d1ef1a8c9efdd63665039287f033904f4c29e665341ffc6e5efdd40b4e"
  "services/backend/services/measurement/repositories/activity_repo.py": "sha256:8ef772fda45e4364b7529e4c4f12724a88116fdc9f9021727c6e9cd91ae6ab06"
  "services/backend/services/measurement/repositories/journey_step_repo.py": "sha256:b5ded116782e70397b8e3009c15ec8cd30490ecdf52bd7c580f0a81806804ec6"
  "services/backend/services/measurement/silver_adapters.py": "sha256:1488ee3e52430dcc49ac07a280b54f1297434c8d79bfe1c084e4aa3fd862be92"
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
- **JourneyCompiler v2.0**: consumes all activity families, deterministic sort, cross-rail transition taxonomy, typed profile/cluster/anonymous lineage, and atomic version+step publication
- **Acquisition evidence**: source class, AI/referral mediation, verification, confidence, classifier version, and eligibility flow from canonical activity into eligible journey steps; excluded source noise remains auditable and counted
- **Silver adapters**: 11 adapter functions covering all silver tables → canonical_activity; the shared `_base` path now also carries canonical-envelope `surface` and the zero-padded `sequence_key` ordering key (populating the previously write-less column the compiler's ORDER BY already used)
- **API**: `/v1/journeys/{id}/steps`, `/v1/journeys/{id}/transitions`, `/v1/journeys/{id}/explain`, `/v1/journeys/{id}/rebuild`
- **Profile360**: `GET /v1/profile/{user_id}/unified-journey`
- **Aether UI**: `JourneyExplorerPage`, `JourneyTimeline`, `JourneyStepCard`, `JourneyFilterBar`, `JourneyTransitionBadge`
- **Kyber UI**: Extended `JourneyExplorerPage` with steps panel, transitions panel, explain panel, rebuild action
- **Tests**: 6 core journey test files covering 57 collected scenarios, including tenant and typed-identity collision isolation
- **Metrics**: `canonical_activities_ingested_total`, `journey_compile_duration_seconds`, `cross_rail_transition_count`, `web3_reorg_corrections_total`, `late_event_insertions_total`

## Pre-existing Failures (not in scope)

None. The previously noted `No module named 'numpy'` repo-doctor failure was resolved in the fraud intelligence PR (claude/aether-web2-web3-fraud-6hu2ou) by making the numpy import in `services/ml/common/feature_contracts.py` conditional.
