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
  - Backend Architecture/aether-backend/services/exploration/operations.py
  - Backend Architecture/aether-backend/services/exploration/session.py
  - Backend Architecture/aether-backend/services/exploration/store.py
  - Backend Architecture/aether-backend/services/exploration/adapters/__init__.py
  - Backend Architecture/aether-backend/services/exploration/adapters/base.py
  - Backend Architecture/aether-backend/services/exploration/adapters/graph.py
  - Backend Architecture/aether-backend/services/exploration/adapters/projection.py
last_synced_commit: "99736fed"
---

# Unified Exploration Fabric — source of truth (backend)

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
| Per-surface capability declarations (16 surfaces × field categories / temporal modes / views / facets / comparison / selection sets / saved views / export) | `packages/shared/contracts/surface-capability-registry.json` → generated twins |

## Rules

- New surfaces and new filterable fields register here first — a surface
  never invents its own filter vocabulary.
- URL/state codecs carry only registry field names and opaque ids — never
  raw PII.
- Truth requirements (minimum confidence, allowed dimension states,
  evidence/provenance inclusion) ride the context and use the canonical
  `shared/dimension_state.py` vocabulary.
- Landed in PR 3: the planner, domain adapters, `/v1/explore/*` routes,
  facets, and saved views. Since then the fabric grew **exploration sessions +
  operations** (S5 — `operations.py` / `session.py` + the `/sessions*` routes,
  below) which compose context-preserving pivots and lens/temporal frames over
  the S1 projection engine, and the 360 surfaces gained **projection-backed
  adapters** (S6 — `outcome360`/`economic360`/`infrastructure360`, then the
  context-360 leaves `temporal360` (Phase 2) and `population360` (Phase 3) —
  `adapters/projection.py`, below).
  Frontend seams for the projection-backed surfaces live in `frontend/aether` +
  `frontend/kyber` (`features/projection-360/`), rendering typed projection
  section states — never recomputing them; UI-less surfaces remain legal.

## Backend (`services/exploration/`, flag-gated `AETHER_EXPLORATION_ENABLED`)

| Module | Responsibility |
|---|---|
| `planner.py` | Validates every leaf filter in an `ExplorationContextV1` against `FILTER_FIELDS` and the target surface's capabilities, emitting exactly one applicability disposition per submitted filter. Zero silent drops is asserted in-planner (`assert_complete`) and by the golden corpus. |
| `adapters/` | One adapter per backed surface — `graph`, `profile360`, `cluster360`, `timeline`, `geo`, `campaign360` (honest projections over the graph plane; `graph` delegates to Universal Graph Query `/v1/graph/query`). The implemented 360 surfaces — `outcome360`, `economic360`, `infrastructure360`, and the context-360 leaves `temporal360` (dedicated surface, Phase 2) and `population360` (dedicated surface, Phase 3) — are backed by `adapters/projection.py::ProjectionSurfaceAdapter` (the S1 migration seam: maps the surface to its intelligence-projection id, runs it tenant-scoped through the projection engine `ProjectionRuntime` → `ProjectionExecutor` → fail-isolated `ProviderRegistry`, and reshapes the engine result into the `AdapterResult` envelope — digest, per-section state, degradation; fail-isolated + content-free degradation, `populated=False` on a missing provider, never an echoed provider diagnostic). Only thin per-surface subclasses for 360s that previously had no adapter are registered, so `profile360`/`campaign360`/`geo`/… are never shadowed (a context-360 leaf owns its own surface rather than riding `comparison_workbench`/`cluster360`/`timeline`/`temporal_observatory`). Deferred surfaces (`comparison_workbench`, `journeys`, `product_intelligence`, `temporal_observatory`, `connection360`) have no adapter and yield an explicit not-available state. |
| `service.py` | Plans, executes an adapter, and wraps the result in the canonical `ExplorationResultEnvelope` (applicability attached to EVERY envelope, whether or not a surface has a backend). Also owns session orchestration: `create_session` / `load_session` / `list_sessions` / `delete_session` / `execute_operation` (composing engine lens sets + the executor for projection surfaces, degrading content-free via `_compose_projection`). |
| `operations.py` | PURE context transforms — `apply_operation` dispatches one `ExplorationOperation` (`OPEN\|PIVOT\|EXPAND\|COLLAPSE\|FILTER_ADD\|FILTER_REMOVE\|LENS_ADD\|TIME_TRAVEL\|DRILL_DOWN\|RESET\|SAVE\|LOAD`) onto a per-op transform (`_pivot`, `_depth`, `_filter_add`, `_filter_remove`, `_lens_add`, `_time_travel`, `_drill_down`, …) yielding the post-op `ExplorationContextV1` + `ExplorationOpResult`. `SAVE`/`LOAD` are session-repository operations handled by the service layer, not pure transforms. Every submitted filter stays accounted for (no silent drops). |
| `session.py` | `ExplorationSessionRepository(BaseRepository)` — JSONB store of `ExplorationSession` (id, tenant-qualified, surface, seed + current context, lens set / temporal mode, op history with per-op `applied\|rejected\|degraded` status); mirrors `ExplorationViewRepository`; no alembic migration. |
| `facets.py` | Conditioned facets with cohort-minimum suppression — buckets below a field's registry-declared `minimum_cohort_size` (e.g. `geography.city` ≥ 25) are suppressed with a reason. |
| `routes.py` | `/v1/explore` `validate` / `query` / `facets` / `views` + `links/resolve` (ContextLink retargeting) + sessions & operations: `POST /sessions`, `GET /sessions`, `GET /sessions/{session_id}`, `DELETE /sessions/{session_id}`, `POST /sessions/{session_id}/operations`. Flag-gated inside every handler (off → honest 404), tenant-scoped; reads require `read`, writes `write`. |
| `store.py` | Saved views on a `BaseRepository` JSONB store (tenant-qualified ids, no alembic migration). |

- Meters use the pre-registered `exploration_*` canonical names
  (`scripts/validate_meter_names.py`). The `/v1/explore` prefix is classified in
  `config/route_registry.yaml` and mounted in `main.py`'s Unified Intelligence
  Plane block. Nothing is production-claimed here — the plane ships flag-off.
