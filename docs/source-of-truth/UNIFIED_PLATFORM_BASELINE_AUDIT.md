---
title: Unified Intelligence Plane — Baseline Audit
status: stable
---

# Unified Intelligence Plane — Baseline Audit

Program baseline recorded before PR 1 implementation began.

- **Documented spec baseline**: `main@929cdf6d` (provenance reference only).
- **Actual starting SHA**: `main@c59e15a` — ~104 commits ahead of the spec
  baseline. Implementation targets actual `main`; every spec-claimed defect
  below was re-verified against it.

## Spec-claimed defects verified STILL LIVE at c59e15a (PR assignment)

| Defect | Verified location | Fixed in |
|---|---|---|
| Naive timestamps accepted at ingestion | `services/ingestion/batch.py` `validate_timestamp` (fromisoformat-only) | PR 1 (shadow machinery) → PR 2 (enforce cutover) |
| No temporal authority / policy registry / viewer timezone preference | repo-wide: zero hits | PR 1 |
| `TemporalEnvelope` TS-only; no Py mirror or parity test | `packages/shared/graph-contract.ts:311` vs `shared/graph/graph_contract.py` | PR 1 |
| No shared frontend time layer; ad-hoc `toLocaleString` in 75+ files | `frontend/{aether,kyber}/src` | PR 1 (layer + freeze) → PR 4 (migration to zero) |
| GeoIP only on deprecated ingest alias; no trusted-proxy handling; raw IP persisted | `services/ingestion/routes.py::_enrich_ip`; raw IP in `services/export/routes.py`, `services/consent/audit_routes.py` | PR 1 |
| Geo routes are unconditional `not_provisioned` stubs | `services/geo/routes.py` | PR 3 |
| Profile360 synthesizes generic `RELATED_TO` edges; ad-hoc readiness vocab | `services/profile/composer.py::_compose_graph` | PR 2 |
| No graph mutation ledger / fact versions / universal mutation gateway | 32 direct-writer files (frozen by `scripts/validate_graph_write_paths.py`); `shared/cis/mutation_gateway.py` used only by agent staging | PR 2 |
| `/v1/graph/temporal` hardcodes limit=100; frontend live graph = sampled assembly w/ 200-cap | `services/operational_intelligence/routes.py`; `frontend/aether/src/features/graph/use-graph-data.ts` | PR 3 (backend) / PR 4 (frontend) |
| Cytoscape instance destroyed+recreated per data change | both `graph-canvas.tsx` copies | PR 4 |
| Broken deep link Cluster360 → `/graph?cluster=` | `cluster-360-page.tsx` vs `graph-page.tsx` | PR 4 |
| `FilterGroup` parity-tested but no UI constructs one; divergent duplicate `frontend/shared/src/types/graph-layers.ts` | `packages/shared/graph-contract.ts` / frontend | PR 4 |
| No ContextCapsule/session-context service; no sessionization | repo-wide: zero hits | PR 1 (contracts) → PR 2 (lifecycle) |
| No comparison engine / findings / watchlists; no projector-ownership registry; no stage receipts | repo-wide: zero hits | PR 1 (contracts) → PR 2/3 |
| ClickHouse DDL split-brain (`DateTime64(3,'UTC')` vs bare `DateTime`) | `deploy/clickhouse/schemas/` vs `Data Lake Architecture/**/schemas/gold_*.py` (15 files frozen by allowlist) | PR 2 |

## Spec-claimed defects SUPERSEDED by main before this program (do NOT re-fix)

| Spec claim | Superseded by |
|---|---|
| Weak/duplicated ingestion durability | Typed Bronze + transactional outbox + `/v1/batch` V2 (#444) |
| Missing consent enforcement at ingestion | Server-authoritative consent (#444) |
| Missing SDK contract governance | Truth Kernel contract spine + SDK parity gates (#434–#437) |
| Missing metric-honesty layer | Measurement Integrity Plane (#429–#432) |
| No import path | Tenant Import Engine (#429–#432) |
| Unstructured route authorization | Route-policy registry + consolidated fail-closed Kyber gate (#440) |
| No reconciliation expectations | Per-dimension expectation registry + `/reconciliation` (#426–#428) |

## Program integration constraints discovered at baseline

- Release evidence must integrate with the #454 system
  (`scripts/release/collect_evidence.py`, `release_manifest.py`) — no
  parallel release machinery.
- Worker registration must respect the #452 `ConsumerSpec` registry.
- The non-Alembic `Backend Architecture/migrations/*.sql` tree is legacy
  (derivatives/stablecoin foundations), applied outside the Alembic chain —
  out of scope for this program; do not extend it.
- The duplicate backend test tree (`Backend Architecture/aether-backend/tests/`)
  is not part of the `make ci-check` lane (root `tests/` is); consolidation is
  follow-up work outside this program's declared scope.
- Merged PR #454 carried 23 unresolved review findings (19 P1, 4 P2);
  remediation is delivered as the program's PR 0 on
  `claude/aether-unified-platform-6azcl7-pr0`. Closed PR #453's content was
  verified fully absorbed into main via #454's branch.
