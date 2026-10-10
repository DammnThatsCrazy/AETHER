---
title: Unified Web2/Web3 Canonical Journey — Execution State
slug: productization/unified-canonical-journey/execution-state
section: operations
visibility: I
audience: [architect, ops, buyer]
status: beta
since_version: 0.1.0
source_files: [services/backend/services/measurement/engine/journey_compiler.py, services/backend/services/measurement/repositories/activity_repo.py, services/backend/services/measurement/repositories/journey_step_repo.py, services/backend/services/measurement/silver_adapters.py, services/backend/alembic/versions/20260627_canonical_activity.py, services/backend/alembic/versions/20260725_ai_referral_attribution.py, services/backend/alembic/versions/20261010_economic_operation_journey_refs.py]
source_hashes:
  "services/backend/alembic/versions/20260627_canonical_activity.py": "sha256:aa34efcf5f337e4430e6727001ee26ca8d657b5d6be9ca7de85b7f151ee668d8"
  "services/backend/alembic/versions/20260725_ai_referral_attribution.py": "sha256:09bcc2502136159d1b50a74181c1d06a7eed30c57ffc9c15da6e900776196189"
  "services/backend/alembic/versions/20261010_economic_operation_journey_refs.py": "sha256:78479dca594fb9ac8f2ce19f317de933afae3ed1211d8c0c45120c9b023ea87a"
  "services/backend/services/measurement/engine/journey_compiler.py": "sha256:32bad8c530ae3e357a5820af0e45542611ee4cfb0176c9e2c25c6f2078f6e564"
  "services/backend/services/measurement/repositories/activity_repo.py": "sha256:fa144dfc1aa0ddeffbb55b3f93707267bd5b7a95f852a445316adf373149ae9e"
  "services/backend/services/measurement/repositories/journey_step_repo.py": "sha256:b6ae724521d9e8aea583549eba3db22d38ca1ef50bcc1be190e0be8eecda9d0d"
  "services/backend/services/measurement/silver_adapters.py": "sha256:39d39d5de1c893eae5688cdb5f1cc07966468617979970eb0631ff64dcf42d41"
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
| 11 | SDK transaction verification + Journey surface | ✅ Connected; provider-backed release evidence open |
| 12 | Exact-reference commerce operation evidence | ✅ Connected; live settlement/refund proof open |

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
- **Web3 transaction verification**: SDK transaction references are matched to tenant-scoped Silver facts, checked against registered-chain read-only RPC, persisted as separate execution evidence, and reflected in Journey status/evidence summary; settlement is not inferred
- **Kyber UI verification action**: Journey Explorer can request an RPC check for an observed Web3 step and labels chain execution independently from payment settlement
- **Economic operation continuity**: source-supplied `commerce_order_ref` persists through canonical activity and Journey step evidence; tenant-scoped Journey and Economic360 surfaces show exact-reference commerce operation links without copying amounts or asserting settlement
- **Knowledge-time evidence**: commerce order revisions and first-seen payment observations can be reconstructed with an explicit, timezone-qualified `as_of` cutoff
- **Tests**: 6 core journey test files covering 57 collected scenarios, including tenant and typed-identity collision isolation
- **Metrics**: `canonical_activities_ingested_total`, `journey_compile_duration_seconds`, `cross_rail_transition_count`, `web3_reorg_corrections_total`, `late_event_insertions_total`

## Pre-existing Failures (not in scope)

None. The previously noted `No module named 'numpy'` repo-doctor failure was resolved in the fraud intelligence PR (claude/aether-web2-web3-fraud-6hu2ou) by making the numpy import in `services/ml/common/feature_contracts.py` conditional.
