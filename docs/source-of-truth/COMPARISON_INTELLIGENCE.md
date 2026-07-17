---
title: Continuous Relationship Decision Intelligence Source of Truth
status: stable
source_files:
  - packages/shared/contracts/comparison-registry.json
  - packages/shared/comparison-contract.ts
  - Backend Architecture/aether-backend/services/intelligence/comparison/contracts.py
  - Backend Architecture/aether-backend/services/intelligence/comparison/generated_vocabulary.py
last_synced_commit: a500f1f
---

# Continuous Relationship Decision Intelligence (PR 1 scope)

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
  Outcome Ledger) lands in PR 3 on the existing jobs/intelligence planes —
  never a parallel finding or outcome system.
