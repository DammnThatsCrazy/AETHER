---
title: Continuous Relationship Decision Intelligence Source of Truth
status: stable
source_files:
  - packages/shared/contracts/comparison-registry.json
  - packages/shared/comparison-contract.ts
  - Backend Architecture/aether-backend/services/intelligence/comparison/contracts.py
  - Backend Architecture/aether-backend/services/intelligence/comparison/generated_vocabulary.py
  - Backend Architecture/aether-backend/services/intelligence/comparison/engine.py
  - Backend Architecture/aether-backend/services/intelligence/comparison/baselines.py
  - Backend Architecture/aether-backend/services/intelligence/comparison/alignment.py
  - Backend Architecture/aether-backend/services/intelligence/comparison/materiality.py
  - Backend Architecture/aether-backend/services/intelligence/comparison/collection.py
  - Backend Architecture/aether-backend/services/intelligence/comparison/findings.py
  - Backend Architecture/aether-backend/services/intelligence/comparison/watchlists.py
  - Backend Architecture/aether-backend/services/intelligence/comparison/scenarios.py
  - Backend Architecture/aether-backend/services/intelligence/comparison/jobs.py
  - Backend Architecture/aether-backend/services/intelligence/comparison/routes.py
  - Backend Architecture/aether-backend/services/intelligence/comparison/store.py
last_synced_commit: a500f1f
---

# Continuous Relationship Decision Intelligence (PR 3 scope — engine landed)

The fundamental unit is a **finding**: a material, evidence-backed
difference between an observed state and a relevant baseline that may
require monitoring, investigation, decision, or action.

## Ownership

| Concern | Canonical owner |
|---|---|
| Vocabularies: 6 comparison modes, 8 baseline types, 10 alignment outcomes, 12 run states, 5 severities, 7 dispositions, 10 fact-linkage states, 7 causal-claim levels, 20 comparison dimensions, 14 materiality components | `packages/shared/contracts/comparison-registry.json` → generated TS/Py twins |
| `ComparisonSubject` / `BaselineSpec` / `ComparisonDefinition` / `ComparisonRun` / `ComparisonFinding` contracts | `services/intelligence/comparison/contracts.py` ↔ `comparison-contract.ts` (parity-tested) |

## Rules

- `services.intelligence` never imports the comparison package eagerly
  (contract-tested) — zero cost until `AETHER_COMPARISON_INTELLIGENCE_ENABLED`.
- Missing data is never equality: preflight data-truth states and
  fact-linkage vocabularies make "empty vs empty" refusals explicit.
- Every conclusion states its epistemic level via the causal-claim ladder
  (observed → … → causally_supported); correlated/temporal evidence is never
  presented as proven causation.
- The engine (semantic alignment, materiality with hard severity overrides,
  versioned baselines/cohorts, read-only counterfactual scenarios,
  watchlists + noise controls, findings → investigations/recommendations/
  Outcome Ledger) landed in PR 3 on the existing jobs/intelligence planes —
  never a parallel finding or outcome system.

## PR 3 engine (`services/intelligence/comparison/`, flag-gated `AETHER_COMPARISON_INTELLIGENCE_ENABLED`)

| Module | Responsibility |
|---|---|
| `engine.py` | Drives a `ComparisonRun` through the 12 registry run states. Data-truth preflight is load-bearing: empty-vs-empty is an explicit refusal (typed reason + fact-linkage states), never "no difference"; a run whose every dimension refuses completes as `suppressed`, not `completed`. |
| `baselines.py` | Versioned resolution of the 8 baseline types; statistical types delegate to the expectations plane, stored (manual/policy) baselines live in a versioned JSONB store. An unresolvable baseline yields an explicit unresolved result, never a fabricated empty one. |
| `collection.py` | Per-dimension observation collection from the analytics events plane; a dimension with no real source is honestly `uncollectable`. |
| `alignment.py` / `materiality.py` | Typed alignment outcomes and materiality scoring with hard severity overrides. |
| `findings.py` / `watchlists.py` | Findings carry a `causal_claim` from the 7-level ladder (correlation/temporal evidence never labelled above its level); watchlists apply noise controls. |
| `scenarios.py` | Read-only counterfactual scenarios — persist nothing. |
| `jobs.py` / `routes.py` / `store.py` | Runs execute as `comparison.run` jobs on the durable jobs plane; `/v1/intelligence/comparisons` is flag-gated inside every handler; persistence is a `BaseRepository` JSONB store (no alembic migration). |

- `services.intelligence` still never imports the comparison package eagerly
  (contract-tested lazy import). Nothing is production-claimed here — the plane
  ships flag-off.
