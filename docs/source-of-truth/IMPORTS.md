---
title: Tenant Import Engine Source of Truth
status: stable
source_files:
  - Backend Architecture/aether-backend/services/imports/contracts.py
  - Backend Architecture/aether-backend/services/imports/analyzer.py
  - Backend Architecture/aether-backend/services/imports/mapping.py
  - Backend Architecture/aether-backend/services/imports/validation.py
  - Backend Architecture/aether-backend/services/imports/service.py
  - Backend Architecture/aether-backend/services/imports/routes.py
  - Backend Architecture/aether-backend/services/imports/storage.py
  - Backend Architecture/aether-backend/repositories/import_files.py
  - Backend Architecture/aether-backend/repositories/imports_repo.py
last_synced_commit: pending
---

# Tenant Import Engine

A tenant uploads a file, Aether analyzes its schema, the tenant maps source
columns onto Aether's canonical primitives, a dry-run validates the mapping,
and — only after that, and only after an explicit approval when the data is
governance-sensitive — the import is eligible to commit. This document covers
the **ingest → analyze → map → validate → approve** half; the Bronze / Silver /
graph commit, replay, and rollback half lands in a separate change.

The guarantee: **nothing is reported analyzed, validated, or approved without
durable, tenant-scoped evidence.** Uploaded bytes carry a sha256; a schema
profile is stored per file; a validation result (with capped row errors) is
stored per run; a governance-sensitive mapping cannot be approved without a
passing validation.

## Contract (TS ⇄ Python twins)

`packages/shared/imports.ts` and `services/imports/contracts.py` are
hand-authored twins, parity-tested by
`tests/contracts/test_imports_parity.py` (statuses, primitives, transforms,
column types, and the barrel export).

- **Lifecycle** (`ImportStatus`): `created → files_pending → uploaded →
  analyzing → analyzed → mapping → mapped → validating → validated →
  review_required → approved → committing → committed`, with terminal states
  `committed`, `partially_committed`, `failed`, `cancelled`, `rolled_back`.
- **Primitives** (9): `entity`, `identifier`, `action`, `relationship`,
  `resource`, `evidence`, `metric`, `governance_fact`, and `unmapped_record`.
  A row that maps to no primitive is preserved as an `unmapped_record` — never
  silently dropped. Each primitive has a fixed set of target fields
  (`IMPORT_PRIMITIVE_FIELDS`); a mapping targeting an unknown field is rejected.
- **Transforms**: deterministic per-cell transforms (`trim`, `lowercase`,
  `to_timestamp`, `to_number`, `to_boolean`, `hash_sha256`, `json_parse`, …).

## Analyze

`analyzer.py` — stdlib only (`csv`, `json`), no new dependencies:

- `detect_format` accepts `csv` / `json` / `jsonl` and **refuses** xlsx,
  parquet, and zip/gzip archives (`unsupported_format`) by extension *and*
  content sniff — the archive/zip-bomb surface is eliminated by not supporting
  archives at all.
- `analyze_bytes` profiles each column: an inferred type (from
  `IMPORT_COLUMN_TYPES` — email / wallet_address / datetime / integer / …),
  nullability, distinct/null counts, sampled values, and a **sensitivity**
  (`pii` / `identifier` / `secret` / `governance` / `none`). Sensitivity drives
  governance gating downstream.
- `header_signature` is a stable hash of the (sorted, lowercased) header set —
  the key used to match reusable templates.

## Map & templates

`mapping.py` validates a full mapping structurally (unknown primitive/field,
duplicate targets, empty mapping) and computes template drift. A tenant can
save a mapping as a **template** keyed by header signature; a new file with a
matching signature surfaces the template (`GET /{id}/templates/suggest`) with
per-template drift (missing / new columns) so it can be applied or adapted.

## Validate & governance gate

`validation.py::validate_mapping` dry-runs the mapping against the uploaded rows
(no mutation): it applies each transform, checks required target fields are
present, and records **capped** per-row errors (`missing_column`,
`transform_failed`, `required_field_empty`, or a single structural
`invalid_mapping`). The result — `rows_total / rows_valid / rows_invalid`, the
capped error list, and `errors_truncated` — is persisted.

Governance: when a mapping targets a governance-sensitive primitive
(`identifier`, `governance_fact`) or a source column profiled as
`pii` / `identifier` / `secret` / `governance`, the session moves to
`review_required` instead of `validated`. Approval (`POST /{id}/approve`)
requires the `admin` permission **and** a passing validation — a
governance-sensitive import cannot slip to `approved` without both.

## Persistence

- `repositories/import_files.py` (migration `20260718_import_engine`) — the
  uploaded bytes in a direct-SQL `import_files` BYTEA table (32 MB hard cap,
  sha256, size, MIME), string-identical DDL to the migration (parity-tested),
  with an in-memory local fallback. `services/imports/storage.py` wraps it
  behind an `ImportStorageAdapter` Protocol — the S3 seam.
- `repositories/imports_repo.py` — the session lifecycle plus schema, mapping
  (versioned), template, validation, and capped row-error records over
  BaseRepository-shaped JSONB tables. Every read is tenant-scoped: a lookup that
  resolves to another tenant's row raises `NotFoundError` rather than leaking it.

## Read/write surfaces

`services/imports/routes.py`, mounted under `/v1/imports`:

| Route | Purpose |
|---|---|
| `POST /v1/imports` | create an import session |
| `GET /v1/imports` | list the tenant's imports |
| `GET /v1/imports/{id}` | session + files + schema/mapping/validation |
| `POST /v1/imports/{id}/files?filename=` | stream-upload a file (size-capped mid-stream) |
| `POST /v1/imports/{id}/analyze` | analyze uploaded files' schemas |
| `PUT /v1/imports/{id}/mapping` | set/validate a mapping (new version) |
| `POST /v1/imports/{id}/validate` | dry-run validate the latest mapping |
| `POST /v1/imports/{id}/approve` | approve for commit (admin; needs passing validation) |
| `POST /v1/imports/{id}/cancel` | cancel (terminal) |
| `GET /v1/imports/{id}/templates/suggest` | matching templates + drift |
| `POST /v1/imports/{id}/apply-template` | apply a template as the mapping |
| `GET/POST /v1/imports/templates`, `DELETE /v1/imports/templates/{id}` | template CRUD |

## Non-goals / limitations

- **Commit / replay / rollback land separately.** This change deliberately stops
  at `approved`: the Bronze (`BronzeRepository("tenant_import")`) staging, the
  Silver import projector, the idempotent graph mutation with `import_commit_id`
  lineage, and the reversible rollback (Bronze source-tag delete + graph
  edge-revoke) are the next increment.
- **No object store.** Files live in Postgres BYTEA (no shared object store
  exists); the `ImportStorageAdapter` Protocol is the seam an S3 implementation
  slots into without touching the service.
- **Validation is inline** (files are size-capped, so a full in-memory pass is
  honest and cheap). The commit step will run on the durable jobs platform.
- **Archives / spreadsheets are rejected**, not parsed (`unsupported_format`) —
  no XLSX/Parquet/zip dependencies, and the zip-bomb class is eliminated.
