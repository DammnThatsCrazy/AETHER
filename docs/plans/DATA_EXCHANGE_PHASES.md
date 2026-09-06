---
title: Data Exchange Plane — Day-1 Implementation Program
slug: plans/data-exchange-phases
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: "8.12.0"
canonical_owner: backend@aether
---

# Data Exchange Plane — Day-1 Implementation Program

This is the implementation program for **Aether's Data Exchange Plane**, the
governed, tenant-facing import/export layer whose doctrine is *many ways in —
one canonical graph — many ways out — one governed portability layer*. The
governing specification is the external **"Aether Import / Export Settings &
Data Exchange Plane — Full Drop-In Implementation Blueprint / Build
Specification"** (sections 0–46 reviewed at M0 time; a full source-of-truth
capture of the blueprint is deferred until the complete source text is
available). This document records the gap between the repository and that
blueprint, orders the work into milestones, and is the ledger for what ships.
Canonical exchange contracts live in
[`services/data_exchange/contracts.py`](../../Backend%20Architecture/aether-backend/services/data_exchange/contracts.py)
with TS twin
[`packages/shared/data-exchange.ts`](../../packages/shared/data-exchange.ts).

**The program's central finding: the Data Exchange Plane is not greenfield.**
The blueprint was written against an older mental model in which the import
and export engines were naive BYTEA shops and durable jobs, rollback, identity
resolution, retention, quotas, and RBAC had to be "created." In the real
repository those seams already exist and are mature — the import engine already
implements Bronze → plan → `GraphMutationGateway` → Silver with lineage and
source-tag rollback (`services/imports/commit.py`), the durable jobs platform
already runs `import.commit` / `import.replay` / `export.generate` on a
lease/retry/DLQ worker (`services/jobs/`), identity resolution already returns
new / matched / ambiguous / conflicting semantics
(`services/identity/`), and `shared/storage/` is a whole flag-gated object/data
plane rather than a bare `ObjectStore`. The Data Exchange Plane is therefore a
**control layer that composes onto these seams** — never a second ingestion
path, never a parallel storage abstraction, never a third import state machine.

Completion of the whole program is gated by the repository's canonical gate
(`make ci-check`), not by this document.

## Program base

Branch `feat/data-exchange-plane` in worktree `/Users/osazehunt/aether-data-exchange`,
cut from `origin/main` @ `bfea2e93` (2026-09-04). Independent lane, sibling to
the other domain programs; unrelated to the in-flight `feat/financial-normalization`
work.

## Central mapping: Data Exchange terms → canonical Aether seams

Every Data Exchange concept in the blueprint is expressed through an existing
canonical seam. New vocabulary (the envelope) is declared in
`services/data_exchange/contracts.py` + `packages/shared/data-exchange.ts`;
the canonical engine underneath stays authoritative.

| Blueprint term (§) | Data Exchange contract | Canonical Aether seam |
|---|---|---|
| Import lifecycle state machine (§7) | `dataArtifactStatuses` (artifact envelope) | Existing `ImportSessionState` FSM + legacy `ImportStatus` (no third vocabulary) |
| Identity preview (§10) | adapter calling resolution | `IdentityResolutionService` (`/v1/identity/resolve`) decision/confidence/conflict |
| Import commit / rollback / replay (§13–14) | control surface passthrough | `import.commit` / `import.replay` durable jobs + `rollback_by_source_tag` |
| Export generation (§15) | exporter registry envelope | `EXPORTERS` registry in `services/export/service.py` + `export.generate` |
| Storage (§4) | `data_artifacts` metadata + `ObjectStore` bytes | shared `get_object_store()` + storage-plane policy registry (`config/storage_policies.yaml`) |
| Signed transfer (§5) | `ObjectTransferService` | new presign capability over `ObjectStore` (net-new) |
| Events (§29) | `events.py` dotted catalog | `Topic` enum + `CANONICAL_EVENT_TYPES` (registered at first emission) |
| RBAC permissions (§23) | `data_exchange.*` grants | `GovernanceDomain` registry + `ROLE_SPECS` (registered at M3) |
| Quotas / usage (§26) | capability/usage adapters | billing `EntitlementService` / `MeteringService` |
| Retention (§25) | retention policy | `shared/storage/ttl.py` + `StorageLifecycle` + `DataRetentionService` |
| Analysis classification | artifact labels | import column sensitivity + `shared/privacy/classification.py` |

## Milestones

All surface availability is flag-gated OFF until its milestone flips it on;
flags only switch transport/storage/surface availability, never semantics.

| M | Theme | Blueprint § | Ships (dark until) | Exit gate |
|---|---|---|---|---|
| **M0** | Scaffold + contracts + mapping | 3, 39 | `services/data_exchange/` contracts/policy/events skeleton, `packages/shared/data-exchange.ts` twin + parity, `DataExchangeConfig` flags OFF, this plan, ownership registration | `make ci-check` green |
| **M1** | Storage-plane migration | 4, 36 | `ObjectStoreImportStorage`, ObjectStore artifact path, `data_artifacts` table + repo, `data_exchange.migrate_legacy_artifact` idempotent job; BYTEA retained through compat window | green + migration tests |
| **M2** | Signed transfers | 5, 27 | `ObjectTransferService`, upload-url / upload-complete / download endpoints, server-side verify (size/hash/tenant prefix/token), short-TTL signed URLs | green + security tests |
| **M3** | Import control plane | 6–14, 21–22 | `/v1/data-exchange/imports*` envelope over the existing engine, identity-preview + graph-preview adapters, saved-mappings CRUD, capabilities/usage/settings adapters | green |
| **M4** | Export control plane | 15–17, 19, 21 | DataArtifact egress, exporter-registry extraction, parquet serializer, partitioned exports + manifest, unified artifact history, audit-exports compat | green |
| **M5** | Reports plane | 18 | `services/reports/` + `report.generate` job + PDF renderer as `artifact_type="report"` egress | green |
| **M6** | Frontend Settings → Data Exchange | 30–35 | Settings section + subpages, export/report dialogs, capability-driven controls, `features/data-exchange/` | green + Playwright E2E |
| **M7** | Ops + hardening | 25, 42–46 | reconcile / expire / cleanup jobs, retention wiring, observability, load/security tests, rollout checklist | green + release-gate |

## M0 ledger (this milestone)

Declared-but-dark. No route, table, or job consumes the contracts yet.

- `Backend Architecture/aether-backend/services/data_exchange/__init__.py`
- `Backend Architecture/aether-backend/services/data_exchange/contracts.py` — directions, artifact statuses (+ terminal set), ingress/egress formats, source types, classifications (+ blocked-by-default set), and the five canonical contracts.
- `Backend Architecture/aether-backend/services/data_exchange/policy.py` — intended classification + RBAC grants (unregistered until M3).
- `Backend Architecture/aether-backend/services/data_exchange/events.py` — dotted topic catalog (unregistered until first emission).
- `Backend Architecture/aether-backend/config/settings.py` — `DataExchangeConfig` (`DATA_EXCHANGE_*` flags, all OFF).
- `packages/shared/data-exchange.ts` + `packages/shared/index.ts` barrel + `packages/shared/data-exchange.test.ts`.
- `Backend Architecture/aether-backend/tests/data_exchange/test_contracts.py` and `tests/contracts/test_data_exchange_parity.py`.
- `docs/source-of-truth/repo_consistency_ownership.json` (+ `REPO_CONSISTENCY_OWNERSHIP.md`) — `data_exchange_plane` category.

## M1 ledger (shipped — one working tree, single deferred gate)

M1 moves artifact payload bytes onto the shared ObjectStore while Postgres BYTEA
stays canonical for the legacy window (compat, not cutover). The metadata
registry is net-new; payload migration is an idempotent durable job.

- `Backend Architecture/aether-backend/services/data_exchange/storage.py` — ObjectStore import-storage seam + `object_key_for` tenant-scoped key scheme.
- `Backend Architecture/aether-backend/repositories/data_artifacts.py` — `data_artifacts` metadata repo (in-memory fallback enables DB-free tests).
- `Backend Architecture/aether-backend/services/data_exchange/jobs_migrate.py` — `data_exchange.migrate_legacy_artifact` idempotent durable job (canonical-id + object-existence probes; bytes-then-row ordering; orphan-safe retry).
- `Backend Architecture/aether-backend/alembic/versions/20260905_data_exchange.py` — `data_artifacts` (+ M3 `data_exchange_saved_mappings`, M5 `report_renders`) schema, `DATA_ARTIFACTS_DDL` string-identical to the repo constant.
- `config/storage_policies.yaml` — policy rows for `data_artifacts`, `data_exchange_saved_mappings`, `report_renders`.
- `Backend Architecture/aether-backend/main.py` — flag-gated lifespan registration + router mounts (shared-surface, coordinator-applied).
- `Backend Architecture/aether-backend/tests/data_exchange/test_storage_migration.py` (+ repo tests).
- Exit: migration tests green DB-free; full `make ci-check` deferred.

## M2 ledger (shipped)

M2 adds short-TTL **presigned URL** transfers over the shared ObjectStore so
artifact bytes move directly between tenant client and store, with server-side
verification on upload-complete.

- `Backend Architecture/aether-backend/shared/storage/object_store.py` — net-new presigned PUT/GET capability (`create_presigned_put_url` / `create_presigned_get_url`, memory + S3 impls).
- `Backend Architecture/aether-backend/services/data_exchange/transfers.py` — `ObjectTransferService` orchestration (upload-url / upload-complete / download-url) + size/hash/tenant-prefix/token verification + canonical export-download audit mirror.
- `Backend Architecture/aether-backend/services/data_exchange/routes_transfer.py` — `/v1/data-exchange/transfers` router (`upload-url` `write`, `upload-complete` `write`, `download-url` `admin`).
- `Backend Architecture/aether-backend/services/data_exchange/events.py` → `Topic` (shared-surface): `DATA_EXCHANGE_ARTIFACT_UPLOADED` (net-new) + reuse of canonical `EXPORT_DOWNLOADED`.
- `Backend Architecture/aether-backend/tests/data_exchange/test_transfers.py` (security-focused).
- Exit: security tests green DB-free.

## M3 ledger (shipped)

M3 is the import control envelope over the *existing* canonical import engine
(no third state machine): `/v1/data-exchange/imports*` proxies import FSM +
`import.commit` / `import.replay` / `rollback_by_source_tag`; previews adapt the
canonical identity-resolution and graph-preview seams; saved mappings and
settings/capabilities/usage read adapters are net-new.

- `services/data_exchange/routes_import.py` (`/v1/data-exchange/imports*`), `identity_preview.py`, `graph_preview.py`, `saved_mappings.py` (+ `data_exchange_saved_mappings` repo module), `capabilities.py` (`/v1/data-exchange/settings|capabilities|usage`).
- RBAC (shared-surface): `data_exchange` added to `GovernanceDomain` twins (`services/security/contracts.py` + `packages/shared/security-governance.ts`) and `ALL_DOMAINS`/`TENANT_DOMAINS`; `policy.py` grants extended 10→13 (`transfer.upload`, `transfer.download`, `report.delete`); `services/data_exchange/authz.py` resolves each dotted grant *or* its legacy single-word alias — envelope gate never weaker than the canonical seam it proxies.
- `Backend Architecture/aether-backend/tests/data_exchange/test_authz.py`, `test_import_envelope.py`, `test_saved_mappings.py` (repo-root `tests/contracts/test_data_exchange_parity.py` is M0's twin gate, still green).
- Exit: envelope + authz parity tests green DB-free.

## M4 ledger (shipped)

M4 is the export control envelope + egress history over the canonical exporter
registry; `parquet` joins the structured formats via pyarrow.

- `services/data_exchange/routes_export.py` (`/v1/data-exchange/exports*`), `exporters.py` (control envelope over the canonical `EXPORTERS` registry), `parquet.py` (pyarrow serializer), `history.py` (`/v1/data-exchange/artifacts` read adapter).
- `Backend Architecture/aether-backend/pyproject.toml` — `data_exchange` optional extra (`pyarrow>=15`, `reportlab>=4.1`), pulled into `all` (shared-surface, coordinator-combined).
- `Backend Architecture/aether-backend/tests/data_exchange/test_export_envelope.py`, `test_parquet.py`.
- (coordinator close-out, landed with M7) canonical `SUPPORTED_FORMATS`/`serialize_rows` parquet + the egress-completion bridge that materializes envelope rows — see the M7 ledger.
- Exit: export/parquet tests green DB-free.

## M5 ledger (shipped)

M5 is the reports plane — human-readable PDF report artifacts through the same
`data_artifacts` / ObjectStore substrate (`artifact_type="report"` egress), a
`report_renders` metadata table, and `report.generate` job handlers. PDF is a
report render, never a structured export format.

- `services/reports/` — `service.py` (request/render orchestration over `data_artifacts` + `report_renders`), `routes.py` (`/v1/data-exchange/reports*`), PDF renderer (`renderers/pdf.py`, reportlab), report job handlers + `register()`.
- `shared/events/events.py` `Topic` (shared-surface): `REPORT_REQUESTED` / `REPORT_AVAILABLE` / `REPORT_FAILED` / `REPORT_DOWNLOADED` (net-new members; emitters no-op until registered — now registered).
- `Backend Architecture/aether-backend/tests/reports/`.
- Exit: reports tests green DB-free.

## M6 ledger (shipped — frontend, gate deferred)

M6 is the tenant **Settings → Data Exchange** surface: feature module + section
mounts + export/report dialogs + capability-driven controls, verified by unit /
component tests and a Playwright E2E spec at the deferred gate.

- `frontend/aether/src/features/data-exchange/` (`api.ts`, `use-*.ts`, `index.ts`), `frontend/aether/src/pages/settings/data-exchange-section.tsx` + `settings-page.tsx` mount, `frontend/aether/src/app/router.tsx` nav, `docs/audits/FRONTEND-ROUTE-STATE-MATRIX.md` rows.
- `frontend/aether/src/test/unit/data-exchange.test.ts`, `frontend/aether/src/test/component/data-exchange-section.test.tsx`, `frontend/aether/src/test/e2e/data-exchange.spec.ts`.
- Exit: unit/component/e2e at the deferred gate (repo precedent: network-enabled run).

## M7 ledger (shipped — ops/hardening)

M7 hardens the `data_artifacts` / ObjectStore plane: retention decisioning plus
four durable tenant-scoped sweeps (expire / reconcile / cleanup /
finalize-pending-egress) with strict object-key shape validation, and an M7
metrics family.  It also lands the **M4 egress-completion delta** the M4 module
docstrings deferred to the coordinator: the canonical `export.generate` handler
now invokes the egress bridge (mirror bytes to the envelope object key + flip
`generating` → `available`), and `finalize_pending_egress` reconciles that
best-effort bridge's crash-window stragglers.

- `services/data_exchange/retention.py` — DB-free `decide_artifact_retention` (HARD_DELETE / TOMBSTONE / PRESERVE) backed by the shared storage-policy registry (`shared/storage/manager.policy_for`).
- `services/data_exchange/jobs_ops.py` — `data_exchange.expire_artifacts` / `reconcile_artifacts` / `cleanup_artifacts` / `finalize_pending_egress` durable jobs + idempotent `register()` (wired in the main.py lifespan under `settings.data_exchange.enabled` at integration). Paged per-tenant sweeps; deletion gated by a strict key-shape validator (tenant prefix + `direction/artifact_id` scheme) — never out-of-tenant.
- `services/data_exchange/egress.py` — M4 egress-completion bridge: `finalize_egress_envelope` writes verified bytes to the row's own tenant-scoped key then `mark_available`s it (terminal-absorbing; object-key mismatch refused); `try_finalize_egress_envelope` is the best-effort entry the canonical handler calls.
- `repositories/data_artifacts.py` — `mark_available` transition (verified sha256/size + `materialized: true`; idempotent on `available`, never resurrects a terminal row).
- `services/data_exchange/metrics.py` — authoritative M7 `data_exchange_ops_*` metric-name set + `register_metrics()` seam (the shared collector auto-registers; no repo-wide allowlist edit needed).
- `services/export/service.py` (coordinator delta) — `parquet` added to `SUPPORTED_FORMATS`; canonical `serialize_rows` delegates it to `parquet.py` (pyarrow lazy at call time). Envelope `_enqueue_export_job` now proxies canonical `request_export` for every format.
- `Backend Architecture/aether-backend/tests/data_exchange/test_jobs_ops.py`, `test_ops_security.py`, `test_ops_metrics.py` (61 tests), `test_egress_bridge.py` (7) and the `serialize_rows`-parquet seam tests in `test_parquet.py`.
- Exit: ops/security/metrics/bridge tests green DB-free; full `make ci-check` at the deferred gate.

## Notes for later milestones

- PDF is never a structured export format: `ReportSpecContract` produces a PDF
  artifact through the same `DataArtifactContract` (`direction="egress"`,
  `artifact_type="report"`). The existing audit-export `pdf_summary` placeholder
  stays a placeholder until M5 wires a real renderer.
- `make ci-check` registration points that bite (from M0 experience): the
  ownership-map category, authored `docs/BACKEND-API.md` once routes land,
  `config/storage_policies.yaml` for every new persistent type, `Topic` +
  `events.ts` + `CANONICAL_EVENT_TYPES` parity for events, meter-name
  registration for metrics, and committing regenerated generated docs in the
  same change.
