---
title: Universal Intelligence Graph — Implementation Ledger
slug: plans/universal-intelligence-graph-implementation
section: architecture
visibility: I
audience: [architect, dev-senior, ai]
status: experimental
since_version: "8.10.0"
canonical_owner: graph@aether
---
# Universal Intelligence Graph — Implementation Ledger

## Baseline

| Field | Value |
|-------|-------|
| Branch | `claude/serene-curie-mfbwhm` |
| Baseline SHA | `1e18a45` |
| Platform version | 8.10.0 |
| Date started | 2026-06-25 |

## Relevant Open PRs
PR #354 — Universal Intelligence Graph (this branch).

---

## Phase Checklist

| Phase | Title | Status |
|-------|-------|--------|
| 0 | Repository Baseline and Gap Inventory | ✅ Complete |
| 1 | Tenant Isolation Hardening | ✅ Complete |
| 2 | Canonical Universal Graph Contract | ✅ Complete |
| 3 | Temporal and Lifecycle Foundation | ✅ Complete |
| 4 | Canonical Universal Graph Query Service | ⬜ Pending |
| 5 | Identity, Population, Clusters, Cluster360 | ⬜ Pending |
| 6 | Campaign, Attribution, Journey, Causality | ⬜ Pending |
| 7 | Economic Segmentation, Value, Flow of Funds | ⬜ Pending |
| 8 | Fraud, Risk, Investigations | ⬜ Pending |
| 9 | Geography, Device, Session, Platform Context | ⬜ Pending |
| 10 | Agentic Intelligence | ⬜ Pending |
| 11 | Predictions, Recommendations, Outcome Feedback | ⬜ Pending |
| 12 | Aether Tenant Graph Experience | ⬜ Pending |
| 13 | Kyber Platform Graph and Operator Experience | ⬜ Pending |
| 14 | Storage, Performance, Caching, Scale | ⬜ Pending |
| 15 | Environment Readiness | ⬜ Pending |
| 16 | Observability, SLOs, Incident Response | ⬜ Pending |
| 17 | Testing Strategy and CI | ⬜ Pending |
| 18 | Documentation | ⬜ Pending |
| 19 | Final Cleanup and Completion Audit | ⬜ Pending |

---

## Phase 0 — Baseline (Complete)

### Existing Implementation Inventory
- **Graph client:** `Backend Architecture/aether-backend/shared/graph/graph.py` — in-memory + Neptune, VertexType (20+ types), EdgeType (40+ types)
- **Layers:** `shared/graph/relationship_layers.py` — H2H/H2A/A2H/A2A + EXCLUDED, strict mode in staging/production
- **Traversal:** `shared/graph/traversal.py` — BFS with depth/limit/cycle detection
- **Write validator:** `shared/graph/write_validator.py` — consent gating, required properties
- **API routes:** `services/operational_intelligence/routes.py` — `/v1/graph/{traverse,path,temporal,overlay,filter,contracts,health}`
- **NLP query:** `services/noesis/` — `/v1/noesis/query`
- **TS contracts:** `packages/shared/graph-contract.ts`, `graph-relationships.ts`, `provenance.ts`, `temporal-intelligence.ts`
- **Frontend:** Aether `pages/graph/graph-page.tsx`, `features/graph/use-graph-data.ts`; Kyber `features/noesis/`
- **Tests:** `tests/graph/` (8 files), `tests/security/` (4 files), `Backend Architecture/.../tests/graph/` (3 files)

### Confirmed Gaps (35 items — see plan for full table)
Key P0 gaps:
- G11: `use-graph-data.ts` derives layers from string prefixes (forbidden)
- G06: Missing `/v1/graph/query`, `/v1/graph/facets`, `/v1/graph/compare`, `/v1/graph/replay`, `/v1/graph/explain`, `/v1/graph/export`, `/v1/graph/capabilities`
- G07: No boolean filter language
- G08: No cursor pagination
- G09: No query budget enforcement
- G03: Universal envelopes missing
- G15: No Cluster360 in Aether
- G18: No Kyber fleet graph
- G20: No privileged tenant entry with audit
- G21: No bitemporal storage
- G32: No mixed-tenant adversarial tests in root `tests/security/`

---

## Phase 1 — Tenant Isolation Hardening (Complete)

### Files Changed
- [x] `frontend/aether/src/features/graph/use-graph-data.ts` — fix G11 (string-prefix layer derivation replaced with `classifyEdgeType()` from `@aether/shared`)
- [x] `frontend/aether/vite.config.ts` — extend `commonjsOptions.include` so Rollup resolves `@aether/shared` CJS exports
- [x] `Backend Architecture/aether-backend/shared/graph/traversal.py` — added `tenant_id` param to BFS/path/temporal; two-set approach (visited + accepted)
- [x] `Backend Architecture/aether-backend/services/operational_intelligence/routes.py` — `graph_filter` now filters by tenantId; traversal calls pass `tenant_id`
- [x] `tests/security/test_graph_tenant_isolation.py` — 8 adversarial tests; all pass
- [x] `docs/plans/UNIVERSAL_INTELLIGENCE_GRAPH_IMPLEMENTATION.md` — this ledger
- [x] `docs/FRONTEND-ARCHITECTURE.md` — stamped after Phase 1 review

### Phase 1 Gate
- [x] `use-graph-data.ts` no longer uses string prefix matching
- [x] Unknown edge types fail closed (null + warning log) not silently default to H2H
- [x] Mixed-tenant adversarial tests pass (8/8)
- [x] `make repo-doctor` exits 0 (23/23 gates)

---

## Phase 2 — Canonical Universal Graph Contract

### Files Changed
- [ ] `packages/shared/graph-contract.ts`
- [ ] `packages/shared/provenance.ts`
- [ ] `Backend Architecture/aether-backend/shared/graph/graph.py`
- [ ] `Backend Architecture/aether-backend/shared/graph/graph_contract.py`
- [ ] `tests/unit/test_graph_contract_parity.py`

---

## Phase 3 — Temporal and Lifecycle Foundation (Complete)

### Files Changed
- [x] `Backend Architecture/aether-backend/shared/graph/edge_properties.py` — added `BITEMPORAL_EDGE_PROPERTIES` frozenset; added `valid_to`, `recorded_at`, `superseded_at` to `OPTIONAL_EDGE_PROPERTIES`; extended `build_edge_properties()` signature
- [x] `Backend Architecture/aether-backend/shared/graph/traversal.py` — `temporal_bfs()` enhanced with bitemporal valid-time filtering (`valid_from <= as_of` + `valid_to > as_of`); falls back to `created_at` for pre-Phase-3 edges
- [x] `Backend Architecture/aether-backend/services/operational_intelligence/routes.py` — added `POST /v1/graph/compare` route with two-snapshot BFS diff; updated `/contracts` route listing
- [x] `Backend Architecture/aether-backend/services/operational_intelligence/models.py` — added `GraphCompareRequest`, `GraphCompareNodeDiff`, `GraphCompareEdgeDiff`, `GraphCompareResult` models
- [x] `tests/graph/test_graph_temporal_integration.py` — 7 new tests; all pass (7/7)

### Phase 3 Gate
- [x] `temporal_bfs` applies bitemporal valid-time window filtering (not just `created_at`)
- [x] Point-in-time replay returns materially different node sets at T1 vs T4
- [x] Expired nodes/edges (valid_to ≤ as_of) excluded from temporal results
- [x] `POST /v1/graph/compare` computes added/removed/changed nodes and edges
- [x] Cross-tenant vertices invisible across all time points
- [x] All 7 temporal integration tests pass (1409/1409 total Python tests pass)

---

## Phase 4 — Canonical Universal Graph Query Service

### Files Changed
- [ ] `Backend Architecture/aether-backend/services/operational_intelligence/models.py`
- [ ] `Backend Architecture/aether-backend/services/operational_intelligence/routes.py`
- [ ] `packages/shared/graph-contract.ts`
- [ ] `tests/unit/test_graph_filter_language.py`
- [ ] `tests/integration/test_graph_query_api.py`

---

## Phase 5 — Cluster360

### Files Changed
- [ ] `Backend Architecture/aether-backend/shared/graph/graph.py`
- [ ] `Backend Architecture/aether-backend/services/identity/routes.py` (or new cluster service)
- [ ] `frontend/aether/src/features/cluster360/` (new)
- [ ] `frontend/aether/src/pages/cluster360/cluster-360-page.tsx` (new)

---

## Remaining Phases (6–19)
_Will be filled as each phase is entered._

---

## Performance Measurements
_To be filled after Phase 14._

## Security Test Results
_To be filled after Phase 1 + 17._

## Final Acceptance Evidence
_To be filled after Phase 19._
