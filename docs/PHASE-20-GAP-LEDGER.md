---
title: Phase 20 Gap Ledger
last_synced_commit: ""
source_files: []
---

# Phase 20 Gap Ledger

Successor to `UNIVERSAL_INTELLIGENCE_GRAPH_IMPLEMENTATION.md`. Phases 1–19 are complete (PRs #351–356 merged). This ledger tracks the 24 gaps addressed in Phase 20: Canonical Multi-Hop Traversal, Path Explainability, and Graph Intelligence Productionization.

---

## Status Key

| Symbol | Meaning |
|--------|---------|
| ✅ | Done — merged to branch |
| 🚧 | In progress |
| ⏳ | Pending |

---

## Gap Ledger

| ID | Description | Priority | Status | Phase | File(s) |
|----|-------------|----------|--------|-------|---------|
| G01 | No PathNode/PathEdge/RelationshipPath/PathExplanation/TraversalSnapshot Pydantic models | P1 | ✅ | 1A | `services/operational_intelligence/models.py` |
| G02 | No versioned path-scoring system (`path_scoring.py`) | P1 | ✅ | 1B | `shared/graph/path_scoring.py` |
| G03 | No `strongest_path()` algorithm (confidence-weighted Dijkstra) | P1 | ✅ | 1D | `shared/graph/traversal.py` |
| G04 | No `k_shortest_paths()` algorithm (Yen's) | P1 | ✅ | 1D | `shared/graph/traversal.py` |
| G05 | No `multi_source_bfs()` | P1 | ✅ | 1D | `shared/graph/traversal.py` |
| G06 | `TraversalResult` lacks `ordered_node_ids`/`ordered_edge_ids` fields | P1 | ✅ | 1C | `shared/graph/traversal.py` |
| G07 | No `POST /v1/graph/paths` endpoint (PathQuery → RelationshipPath[]) | P1 | ✅ | 2A | `services/operational_intelligence/routes.py` |
| G08 | No `POST /v1/graph/paths/expand` endpoint | P1 | ✅ | 2A | `services/operational_intelligence/routes.py` |
| G09 | No `POST /v1/graph/paths/explain` endpoint | P1 | ✅ | 2A | `services/operational_intelligence/routes.py` |
| G10 | No `POST /v1/graph/snapshots` / `GET /v1/graph/snapshots/{id}` | P1 | ✅ | 2A | `services/operational_intelligence/routes.py` |
| G11 | No `POST /v1/graph/paths/jobs` / `GET /v1/graph/paths/jobs/{id}` (async deep traversal) | P2 | ✅ | 2A | `services/operational_intelligence/routes.py` |
| G12 | No `POST /v1/graph/snapshots/{id}/compare` | P2 | ✅ | 2A | `services/operational_intelligence/routes.py` |
| G13 | `TraversalSnapshotRepository` and `DeepTraversalJobRepository` missing from repos.py | P1 | ✅ | 2B | `repositories/repos.py` |
| G14 | OODA `Recommendation` lacks `path_refs: list[str]` and `snapshot_ref: str` | P2 | ✅ | 3A | `services/intelligence/decision_models.py` |
| G15 | Suggestion adapters don't populate `graphRefs` with canonical path_ids | P2 | ✅ | 3B | `services/suggestions/adapters/graph_adapter.py`, `services/suggestions/lifecycle.py` |
| G16 | No persistent `Investigation` with `snapshot_id` + `path_ids` linkage | P2 | ✅ | 3C | `services/operational_intelligence/models.py`, `services/investigation/routes.py` |
| G17 | No Silver projection reconciliation worker | P2 | ✅ | 3D | `services/silver/reconciliation.py` |
| G18 | No `PathInspector` component + TS canonical path types | P3 | ✅ | 4A/4B | `packages/shared/operational-intelligence.ts`, `frontend/kyber/src/components/graph/path-inspector.tsx`, `frontend/aether/src/components/graph/path-inspector.tsx` |
| G19 | Graph toolbar lacks target-node selector and traversal-mode control | P3 | ✅ | 4D | `frontend/kyber/src/components/graph/graph-toolbar.tsx` |
| G20 | Aether graph-page calls local BFS instead of real `/v1/graph/paths` API | P3 | ✅ | 4E | `frontend/aether/src/pages/graph/graph-page.tsx` |
| G21 | New endpoints not wired in Kyber/Aether `endpoints.ts` API clients | P3 | ✅ | 4C | `frontend/kyber/src/lib/api/endpoints.ts`, `frontend/aether/src/lib/api/endpoints.ts` |
| G22 | `GET /v1/graph/capabilities` response not updated with new capabilities | P3 | ✅ | 2A | `services/operational_intelligence/routes.py` |
| G23 | Canonical Path Intelligence Architecture docs missing | P3 | ✅ | 5 | `docs/CANONICAL-PATH-INTELLIGENCE.md`, `docs/MULTI-HOP-TRAVERSAL.md` |
| G24 | Phase-20 successor gap-ledger doc missing | P3 | ✅ | 5 | `docs/PHASE-20-GAP-LEDGER.md` (this file) |

---

## Tests Added

| File | Tests | Covers |
|------|-------|--------|
| `tests/graph/test_path_scoring.py` | 7 | G02: scoring formula, classify_path, make_path_id |
| `tests/graph/test_traversal_path_algorithms.py` | 6 | G03–G05: strongest_path, k_shortest, multi_source_bfs, tenant isolation |
| `tests/unit/test_graph_paths_routes.py` | 14 | G07–G12: all 8 new routes, snapshot isolation, async jobs |
| `tests/unit/test_silver_reconciliation.py` | 4 | G17: reconciliation worker |
| `tests/e2e/test_path_intelligence_flow.py` | 4 | E2E: find path, k_shortest, save+compare snapshot, link to investigation |
| `frontend/aether/src/test/unit/path-inspector.test.tsx` | 10 | G18: PathInspector tabs, badges, save button |
| `frontend/aether/src/test/unit/graph-page.test.tsx` | 5 | G20: real API call, PathInspector shown, traversal mode buttons |

---

## Security Invariants Verified

All invariants from the P0 security checklist are enforced:

1. `_require_read(request, tenant_id)` is the first call on all 9 new routes.
2. Snapshot ownership is fail-closed: explicit `tenant_id` comparison before any data is returned.
3. `strongest_path`, `k_shortest_paths`, and `multi_source_bfs` all use the two-set (`visited` + `accepted`) tenant isolation pattern.
4. Investigation snapshot linkage validates same-tenant ownership before attaching `snapshot_id`.
5. `PathClassification` is always derived from the worst-case `causality_class` edge (never upgraded).

---

## Pending Follow-Up Work

These items are out of scope for Phase 20 but should be tracked:

- Celery worker integration for `DeepTraversalJob` (currently executes synchronously in test/local)
- `_hydrate_graph_refs()` in `lifecycle.py` — stub needs real `shortest_path` integration with suggestion lifecycle events
- `_compute_path_refs()` base class in `recommendation_families/base.py` — default returns `[]`; production subclasses should override
- Neptune-specific `strongest_path` implementation (currently uses in-memory graph client in production too)
