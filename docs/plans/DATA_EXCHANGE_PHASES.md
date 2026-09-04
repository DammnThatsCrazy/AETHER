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
