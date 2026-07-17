---
title: Unified Exploration Fabric Source of Truth
status: stable
source_files:
  - packages/shared/exploration-contract.ts
  - packages/shared/contracts/filter-field-registry.json
  - packages/shared/contracts/surface-capability-registry.json
  - packages/shared/filter-fields.ts
  - packages/shared/surface-capabilities.ts
  - Backend Architecture/aether-backend/shared/exploration/models.py
  - Backend Architecture/aether-backend/shared/exploration/generated_fields.py
  - Backend Architecture/aether-backend/shared/exploration/generated_surfaces.py
  - Backend Architecture/aether-backend/shared/contracts_models/filters.py
last_synced_commit: a500f1f
---

# Unified Exploration Fabric (PR 1 scope)

One context-preserving query/filter/presentation state for every analytical
surface. **Silent filter drops are structurally impossible**: every response
envelope carries one applicability entry per requested filter
(`applied` / `translated` / `unsupported` / `suppressed` / `not_applicable`).

## Ownership

| Concern | Canonical owner |
|---|---|
| The ONE boolean filter language | `shared/contracts_models/filters.py` (moved from `services/operational_intelligence/models.py`, which re-exports unchanged) ↔ the `FilterOperator`/`FilterExpression`/`FilterGroup` section of `packages/shared/graph-contract.ts` |
| `ExplorationContextV1` (COMPOSES FilterGroup — never a second filter system), `ApplicabilityReport`, `ExplorationResultEnvelope` (completeness/truth/execution blocks), `ContextLink` | `shared/exploration/models.py` ↔ `packages/shared/exploration-contract.ts` (parity-tested) |
| Filterable-field catalog (33 seed fields: operators ⊆ FilterOperator, sensitivity tiers, consent purposes, minimum cohort sizes — e.g. `geography.city` ≥ 25) | `packages/shared/contracts/filter-field-registry.json` → generated twins |
| Per-surface capability declarations (10 surfaces × field categories / temporal modes / views / facets / comparison / selection sets / saved views / export) | `packages/shared/contracts/surface-capability-registry.json` → generated twins |

## Rules

- New surfaces and new filterable fields register here first — a surface
  never invents its own filter vocabulary.
- URL/state codecs carry only registry field names and opaque ids — never
  raw PII.
- Truth requirements (minimum confidence, allowed dimension states,
  evidence/provenance inclusion) ride the context and use the canonical
  `shared/dimension_state.py` vocabulary.
- The planner, domain adapters, `/v1/explore/*` routes, facets, and saved
  views land in PR 3; surface migrations + shared exploration UI in PR 4
  (gate: `make exploration-readiness`, grows per PR).
