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
  - Backend Architecture/aether-backend/services/exploration/planner.py
  - Backend Architecture/aether-backend/services/exploration/facets.py
  - Backend Architecture/aether-backend/services/exploration/service.py
  - Backend Architecture/aether-backend/services/exploration/routes.py
  - Backend Architecture/aether-backend/services/exploration/store.py
  - Backend Architecture/aether-backend/services/exploration/adapters/base.py
  - Backend Architecture/aether-backend/services/exploration/adapters/graph.py
last_synced_commit: a500f1f
---

# Unified Exploration Fabric (PR 3 scope — backend landed)

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
| Per-surface capability declarations (14 surfaces × field categories / temporal modes / views / facets / comparison / selection sets / saved views / export) | `packages/shared/contracts/surface-capability-registry.json` → generated twins |

## Rules

- New surfaces and new filterable fields register here first — a surface
  never invents its own filter vocabulary.
- URL/state codecs carry only registry field names and opaque ids — never
  raw PII.
- Truth requirements (minimum confidence, allowed dimension states,
  evidence/provenance inclusion) ride the context and use the canonical
  `shared/dimension_state.py` vocabulary.
- The planner, domain adapters, `/v1/explore/*` routes, facets, and saved
  views landed in PR 3 (see below); surface migrations + shared exploration UI
  in PR 4 (gate: `make exploration-readiness`, grows per PR).

## PR 3 backend (`services/exploration/`, flag-gated `AETHER_EXPLORATION_ENABLED`)

| Module | Responsibility |
|---|---|
| `planner.py` | Validates every leaf filter in an `ExplorationContextV1` against `FILTER_FIELDS` and the target surface's capabilities, emitting exactly one applicability disposition per submitted filter. Zero silent drops is asserted in-planner (`assert_complete`) and by the golden corpus. |
| `adapters/` | One adapter per backed surface — `graph`, `profile360`, `cluster360`, `timeline`, `geo`, `campaign360`. The graph adapter delegates to the Universal Graph Query plane (`/v1/graph/query`: boolean filter, budgets, cursors, tenant isolation); the others are honest projections over the same real plane. Deferred surfaces (`comparison_workbench`, `journeys`, `product_intelligence`, `temporal_observatory`, `outcome360`, `economic360`, `connection360`, `infrastructure360`) have no adapter and yield an explicit not-available state. |
| `facets.py` | Conditioned facets with cohort-minimum suppression — buckets below a field's registry-declared `minimum_cohort_size` (e.g. `geography.city` ≥ 25) are suppressed with a reason. |
| `service.py` | Plans, executes an adapter, and wraps the result in the canonical `ExplorationResultEnvelope` (applicability attached to EVERY envelope, whether or not a surface has a backend). |
| `routes.py` | `/v1/explore` `validate` / `query` / `facets` / `views` + `links/resolve` (ContextLink retargeting). Flag-gated inside every handler (off → honest 404), tenant-scoped. |
| `store.py` | Saved views on a `BaseRepository` JSONB store (tenant-qualified ids, no alembic migration). |

- Meters use the pre-registered `exploration_*` canonical names
  (`scripts/validate_meter_names.py`). The `/v1/explore` prefix is classified in
  `config/route_registry.yaml` and mounted in `main.py`'s Unified Intelligence
  Plane block. Nothing is production-claimed here — the plane ships flag-off.
