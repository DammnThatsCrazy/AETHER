---
title: Data Exchange Plane — Frozen API Surface
slug: plans/data-exchange-api
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: "8.12.0"
canonical_owner: backend@aether
---

# Data Exchange Plane — Frozen API Surface

This document is the **contract freeze** for the Data Exchange Plane program
(`docs/plans/DATA_EXCHANGE_PHASES.md`). It pins the tenant-facing
`/v1/data-exchange/*` surface that milestone M1–M7 implement and that the M6
frontend builds against. It is written once, up front, so that parallel
milestone work stays shape-consistent without cross-agent coordination. The
canonical vocabulary (directions, statuses, formats, classifications, source
types) is owned by `services/data_exchange/contracts.py` and
`packages/shared/data-exchange.ts`; **this document does not redefine it.**

## Doctrine

*Many ways in — one canonical graph — many ways out — one governed portability
layer.* The Data Exchange Plane is a **control envelope over canonical seams**,
never a second ingestion path and never a parallel storage abstraction. Every
route below is one of:

- a **thin proxy** that translates Data Exchange vocabulary onto an existing
  canonical route/service and returns (mostly) the canonical payload;
- a **read adapter** that renders canonical state in the Data Exchange
  vocabulary (artifact statuses, formats, envelope contracts);
- a **net-new capability** the canonical seams do not provide today (signed
  transfer URLs, identity preview, saved import mappings, unified artifact
  history, PDF reports, settings/capabilities/usage adapters).

Where a verb already exists canonically (`/v1/imports/*`, `/v1/exports/*`), the
envelope proxies the canonical engine — it never re-implements the engine.

## Conventions

- **Prefix**: every sub-router lives under `/v1/data-exchange`. A sub-router is
  one module owning one APIRouter with its own `prefix` + `tags`.
- **Mounting / flags**: a sub-router is mounted in `main.py` only when its
  `settings.data_exchange.*` flag is ON, following the `if dq.enabled:
  app.include_router(...)` pattern at main.py ~1055–1073. Availability flags
  switch transport/surface availability only, never semantics.
  - M1 object-store artifact path: `DATA_EXCHANGE_OBJECT_STORE_ENABLED`.
  - M2 transfer routes: `DATA_EXCHANGE_SIGNED_TRANSFERS_ENABLED`.
  - M3 import envelope: `DATA_EXCHANGE_ENABLED`.
  - M4 export/artifact routes: `DATA_EXCHANGE_ENABLED` (+ parquet serializer
    behind `DATA_EXCHANGE_PARQUET_ENABLED`).
  - M5 report routes: `DATA_EXCHANGE_REPORTS_ENABLED`.
- **Tenancy & auth**: every route resolves `request.state.tenant` and requires
  the caller to hold the relevant `data_exchange.*` grant (RBAC domain
  `data_exchange` — registered by the coordinator at M3 integration; the
  `policy.py` grant list is the source of grant names). Tenant scoping is
  enforced by the proxied canonical route AND re-asserted at the envelope edge.
- **IDs**: opaque strings. The canonical engine's id (e.g. an import session id
  or export artifact id) is preserved as `canonical_id` on the envelope.
- **Errors**: canonical Aether error semantics only (`BadRequestError` etc →
  FastAPI `{"detail": ...}`). No parallel error vocabulary.
- **Format / status / classification values**: only members of the M0 contract
  tuples. No free strings on these fields.
- **Bytes**: never proxied through the envelope for large bodies. Uploads use
  the canonical capped-upload path (`/v1/imports` mid-stream cap) or the M2
  signed-transfer path. Downloads of object-store artifacts use the M2
  download URL or the existing `/v1/exports/{id}/download` byte path.
- **Deprecated/duplicate**: existing `/v1/imports`, `/v1/exports`, `/v1/jobs`
  remain canonical and mounted. The envelope may duplicate *read* verbs for the
  blueprint-native UI; it must not duplicate engine logic.

## Milestone → module ownership (route files)

| M | Route module(s) | Prefix | Flag |
|---|---|---|---|
| M1 | (no routes — storage/migration + `data_artifacts` repo) | — | — |
| M2 | `services/data_exchange/routes_transfer.py` | `/v1/data-exchange/transfers` | object store |
| M3 | `services/data_exchange/routes_import.py` (+ `saved_mappings.py`, `identity_preview.py`, `graph_preview.py`, `capabilities.py`) | `/v1/data-exchange` (subpaths) | enabled |
| M4 | `services/data_exchange/routes_export.py` + `history.py` | `/v1/data-exchange/exports`; `/v1/data-exchange/artifacts` | enabled |
| M5 | `services/reports/routes.py` | `/v1/data-exchange/reports` | reports |
| M6 | frontend only (`features/data-exchange/`, settings sections) | — | — |
| M7 | ops (jobs + harnesses) — no new tenant route surface | — | — |

The import envelope and the M4/M5 egress envelope both read/write the M1
`data_artifacts` table (via `repositories/data_artifacts.py`). **M6 consumes
only**: `GET /imports`, `GET /exports`, `GET /reports`, `GET /artifacts`,
`GET /artifacts/{artifact_id}`, the M2 download URL for available artifacts,
`POST /exports`, `POST /reports`, and the three settings read adapters
(`/settings`, `/capabilities`, `/usage`).

---

## M1 — storage migration (no routes)

Internal contract: `repositories/data_artifacts.py` owns the `data_artifacts`
metadata table (envelope fields incl. `artifact_id, tenant_id, direction,
artifact_type, object_key, filename, format, content_type, size_bytes, sha256,
classification, status, created_by, created_at, expires_at, deleted_at,
canonical_id`). Bytes live in the shared ObjectStore, never Postgres. The
`data_exchange.migrate_legacy_artifact` durable job copies a legacy BYTEA
import/export payload to ObjectStore idempotently and records the artifact row.
M1 exposes **no** `/v1/data-exchange` route.

## M2 — signed transfers (`/v1/data-exchange/transfers`)

Presigned URL capability over the shared ObjectStore (`shared/storage/
object_store.py` gains presign — the M2 agent is the sole editor of that file
in this program). `DATA_EXCHANGE_OBJECT_STORE_ENABLED`.

| Verb | Path | Request | Response (200) | Proxies / notes |
|---|---|---|---|---|
| POST | `/transfers/{artifact_id}/upload-url` | — | `{artifact_id, object_key, upload_url, upload_method:"PUT", upload_headers, expires_at, status:"upload_pending"}` | Pre-allocates object_key for a tenant artifact already in `data_artifacts` (created by import source / M3). Signed URL bound to `tenant_id + artifact_id + object_key + expiry` (short TTL). |
| POST | `/transfers/{artifact_id}/upload-complete` | `{declared_size_bytes?, declared_sha256?}` | `{artifact_id, status, verified:{size_bytes, sha256}, stored_bytes}` | **Server-side verify**: head the object; assert size + sha256 (when declared) + tenant key prefix + upload token; flip artifact status. |
| GET | `/transfers/{artifact_id}/download-url` | — | `{artifact_id, download_url, download_headers, expires_at, checksum_sha256}` | Only when artifact `status ∈ {available, committed}` and within retention. Signed GET, short TTL. Logs the download audit/event the canonical `/v1/exports/{id}/download` route logs. |

Security requirements (tests must cover): token unforgeable (signed), URL bound
to tenant (a second tenant cannot use it), expiry enforced, upload-complete
verifies size/hash, revoked/expired/deleted artifacts refuse.

## M3 — import control envelope (`/v1/data-exchange/imports` etc.)

Proxies the canonical `/v1/imports` engine (import FSM + `import.commit` /
`import.replay` jobs + `rollback_by_source_tag`). `DATA_EXCHANGE_ENABLED`.

Import envelope (verb = translation of the canonical lifecycle):

| Verb | Path | Request | Response (200) | Notes |
|---|---|---|---|---|
| POST | `/imports` | `ImportSourceContract` (json body) | `{import_id, artifact_id?, status:"created", canonical_id}` | Creates canonical import session; registers the envelope artifact (ingress). |
| GET | `/imports` | query `limit, offset, direction_filter?, status_filter?, format_filter?` | `{imports:[ImportSourceContract+envelope], count}` | Read adapter over canonical sessions + `data_artifacts`. **M6 import-history source.** |
| GET | `/imports/{import_id}` | — | envelope detail (source + artifact + canonical FSM state) | — |
| POST | `/imports/{import_id}/files` | multipart/capped bytes | `{import_id, artifact_id, status:"uploaded"}` | Proxy of canonical file upload; artifact row updated. |
| POST | `/imports/{import_id}/analyze` | — | canonical analyze payload | — |
| PUT | `/imports/{import_id}/mapping` | `ImportMappingContract` | `{import_id, mapping_version}` | Translates envelope mapping → canonical mapping. |
| POST | `/imports/{import_id}/preview/identity` | `{identity_fields: [...]}` | `{decisions:[{field,index,value,decision,confidence}], summary}` | **Net-new adapter** over `IdentityResolutionService`/`/v1/identity/resolve`. |
| POST | `/imports/{import_id}/preview/graph` | `{mapping_version?}` | canonical graph-preview payload | Proxies existing `graph-preview`. |
| POST | `/imports/{import_id}/commit` | — | `{import_id, job_id, status:"processing"}` | Enqueues `import.commit`. |
| POST | `/imports/{import_id}/rollback` | `{commit_id?, reason}` | `{import_id, rolled_back_commit_id}` | Proxies rollback. |
| GET | `/import-mappings` | — | `{mappings:[...]}` | Saved ImportMappingContract list. |
| POST | `/import-mappings` | `ImportMappingContract` + `name` | `{mapping_id, import_id, version}` | **Net-new persistence** (tenant-scoped). |
| GET | `/import-mappings/{mapping_id}` | — | saved mapping | — |
| DELETE | `/import-mappings/{mapping_id}` | — | `{deleted:true}` | — |
| GET | `/settings` | — | `{imports:{...}, exports:{...}, reports:{...}, transfers:{...}, capabilities:{...}}` | **Read adapter** over `DataExchangeConfig` + storage-policy + capability state. **M6 settings source.** |
| GET | `/capabilities` | — | `{data_exchange:{enabled, flags:{...}}, available_formats, available_sources, blocked_classifications}` | **Read adapter**; drives M6 capability gating. |
| GET | `/usage` | — | `{tenant_id, imports:{count,last_30_days}, exports:{count,bytes,last_30_days}, reports:{count}, quotas:{...}}` | **Read adapter** over metering (imports/exports/reports families). |

## M4 — export envelope + unified artifact history

`DATA_EXCHANGE_ENABLED`. Proxy/translation over canonical `/v1/exports` +
`EXPORTERS` registry + parquet serializer (M4 adds pyarrow; backend only).

| Verb | Path | Request | Response (200) | Notes |
|---|---|---|---|---|
| GET | `/exports/types` | — | `{export_types, formats}` | Mirrors canonical `/v1/exports/types` incl. new exporters. |
| POST | `/exports` | `ExportSpecContract` | `{export_id, artifact_id, job_id, status:"generating"}` | **M6 create-export source.** Maps envelope spec → canonical exporter params + `format` (structured only: csv/json/ndjson/parquet), enqueues the export job. |
| GET | `/exports` | query `limit, offset, status_filter?` | `{artifacts:[...], count}` | List egress artifacts. **M6 export-history source.** |
| GET | `/exports/{export_id}` | — | envelope + manifest + canonical exporter meta | — |
| DELETE | `/exports/{export_id}` | — | `{deleted:true}` | Proxy of canonical artifact delete (revoke). |
| GET | `/artifacts` | query `limit, offset, direction?, artifact_type?, status_filter?` | `{artifacts:[...], count}` | **Unified artifact history** across imports/exports/reports/transfers from `data_artifacts`. **M6 history source.** |
| GET | `/artifacts/{artifact_id}` | — | full `DataArtifactContract` | — |

Parquet is an egress structured format via a registered parquet exporter
(`services/data_exchange/parquet.py` using pyarrow). Partitioned exports +
manifest use the canonical manifest builder (`services/export/manifest.py`).

## M5 — reports plane (`/v1/data-exchange/reports`)

`DATA_EXCHANGE_REPORTS_ENABLED`. `services/reports/` + `report.generate` job +
PDF renderer (reportlab; M5 adds the dependency). PDF is an `artifact_type=
"report"` egress artifact — **never** a structured EgressFormat.

| Verb | Path | Request | Response (200) | Notes |
|---|---|---|---|---|
| POST | `/reports` | `ReportSpecContract` | `{report_id, artifact_id, job_id, status:"generating"}` | **M6 create-report source.** Enqueues `report.generate`; template resolved from `ReportSpecContract.template`. |
| GET | `/reports` | query `limit, offset, status_filter?` | `{artifacts:[...], count}` | **M6 report-history source.** |
| GET | `/reports/{report_id}` | — | envelope + render meta | — |
| GET | `/reports/{report_id}/download` | — | bytes (application/pdf) + `X-Checksum-SHA256` | Bytes served from ObjectStore via `get`; mirrors canonical export download audit/event semantics. |
| DELETE | `/reports/{report_id}` | — | `{deleted:true}` | Revoke/expire. |

## M6 — frontend Settings → Data Exchange

New feature module `frontend/aether/src/features/data-exchange/` following the
`{api.ts, use-*.ts, index.ts}` pattern; `api.ts` zod-schema shapes match the
request/response tables above. New Settings section (stacked page sections +
sub-views) surfaces: capability-driven import/export/report/transfer controls;
artifact history (`GET /artifacts`, `GET /exports`, `GET /imports`,
`GET /reports`); export + report creation dialogs (`POST /exports`,
`POST /reports`); download affordances (download URL when available, else the
existing canonical download route). Every control is gated by
`GET /data-exchange/capabilities` and the tenant capability surface. Route/
nav rows are added to `docs/audits/FRONTEND-ROUTE-STATE-MATRIX.md`. E2E:
`frontend/aether/src/test/e2e/data-exchange.spec.ts`.

## M7 — ops & hardening

No new tenant route surface. Cleanup/reconcile/expire durable jobs over
`data_artifacts` (status `expired`/`deleted`, retention wiring via
`shared/storage/ttl.py` + lifecycle), observability meters, load/security test
harnesses, and the rollout checklist. Hardens the M2–M5 surfaces above.

---

## Shared-surface deltas the coordinator applies (not the agents)

Agents never edit these; they return proposed deltas and the coordinator lands
them at integration:

1. `main.py` — mount each sub-router behind its flag.
2. Alembic — one `YYYYMMDD_data_exchange.py` migration from the agents' DDL
   fragments (`data_artifacts`, saved mappings, report/render state).
3. `config/storage_policies.yaml` — policy rows for every new table.
4. `Backend Architecture/aether-backend/pyproject.toml` — combine pyarrow
   (M4) + reportlab (M5) once.
5. RBAC — add `data_exchange` to `GovernanceDomain` in BOTH
   `services/security/contracts.py` and `packages/shared/security-governance.ts`;
   extend `ALL_DOMAINS`/`TENANT_DOMAINS`/`ROLE_SPECS`; map `policy.py` grants.
6. Events — at first emission map onto canonical topics (`IMPORT_COMMITTED`,
   `EXPORT_READY`, `EXPORT_DOWNLOADED`); add genuinely-new `Topic` members only
   for transfer/report artifacts; SDK `event-registry.json` only for a new
   canonical family.
7. Metering — `imports`/`exports`/`reports` families via `CAPABILITY_FAMILIES`.
8. Capability flag surface (`data_exchange`) for M6 nav gating.
9. Ownership map + `make repo-doctor-fix` + `DATA_EXCHANGE_PHASES.md` ledgers.
10. `packages/shared` barrel additions only where the frontend needs new
    shared types (none beyond the M0 twin is anticipated).
