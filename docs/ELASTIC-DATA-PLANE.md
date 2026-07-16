---
title: Elastic Data Plane
slug: data/elastic-data-plane
section: data
visibility: I
audience: [dev-senior, architect, ops]
status: beta
since_version: "8.12.0"
canonical_owner: data@aether
estimated_read_minutes: 7
toc_depth: 3
---

# Elastic Data Plane

The Elastic Data Plane is the storage foundation that lets Aether move
high-volume persistent data between the hot database path and cheap object
storage **without losing lineage, integrity, retention semantics, or the
ability to reason about every persistent resource type**. This page covers
the foundation shipped by FT-7-STORAGE-DESCRIPTORS: the storage-policy
registry, the universal storage descriptor, the object-store protocol, the
policy-driven storage manager, and the reconciler. Object-backed Bronze and
cross-store lifecycle propagation build on this in FT-8.

## The four pieces

| Piece | Where | What it is |
|---|---|---|
| Policy registry | `config/storage_policies.yaml` | One declarative policy per persistent resource type |
| Storage descriptor | `shared/storage/descriptor.py` | Immutable, checksummed handle for any externalized object |
| Object store protocol | `shared/storage/object_store.py` | `put/get/head/delete/list` over S3 or in-memory |
| Manager + reconciler | `shared/storage/manager.py`, `shared/storage/reconciler.py` | Policy-enforced externalize/hydrate; descriptor-vs-object drift detection |

## Storage policy registry

Every persistent resource type — every BaseRepository-backed store declared
in `Backend Architecture/aether-backend/repositories/repos.py` and every
table created by an Alembic migration — has exactly one policy entry in
`config/storage_policies.yaml` declaring:

- **Placement** — `authoritative_store`, `metadata_store`,
  `projection_stores`
- **Encoding** — `codec` (`zstd | none`), `format` (`jsonl | row`)
- **Lifecycle** — `retention_class` (`standard | legal`), `delete_behavior`
  (`hard_delete | tombstone | preserve`), `legal_hold_supported`
- **Capabilities** — `allow_object_externalization`,
  `allow_adaptive_materialization`, `allow_historical_table_storage`
- **Privacy semantics** — `requires_consent_invalidation`,
  `requires_permission_hash`

The registry is `enforcement_status: enforced`. The CI gate
(`scripts/release/check_storage_policies.py`, wired into
`make ci-check` via `scripts/repo_doctor.py` and runnable directly as
`make validate-storage-policies`) derives the persistent-type inventory
**from the repo itself** — `repositories/repos.py` store names plus tables
created across `alembic/versions/*.py` (literal DDL and loop-style
`TABLES = [...]` migrations) — and fails when:

- a persistent resource type has no policy (adding a repository or a
  migration-created table without a policy breaks CI),
- a policy names a resource type that no longer exists (stale/typo),
- a policy is missing schema fields, duplicates a type, uses an unknown
  `delete_behavior`/`codec`, or pairs `retention_class: legal` with
  `hard_delete`.

## Storage descriptor

`StorageDescriptor` (frozen dataclass) is the canonical handle for any
object externalized out of the hot path. Fields: `resource_type`,
`tenant_id`, `locator` (object key), `codec` **actually applied**,
`format`, `checksum_sha256`, `size_bytes`, `record_count`, `lineage`
(source ids), `created_at`, `schema_version`, `descriptor_id`.

Descriptors persist through `StorageDescriptorRepository`
(`repositories/repos.py`, table `storage_descriptors`, BaseRepository shape:
`id TEXT PK, data JSONB, tenant_id, created_at, updated_at`; migration
`20260726_storage_descriptors`). Payload bytes never live in that table —
descriptors keep object metadata queryable while the bytes live in the
object store.

## Object store protocol

`ObjectStore` is a minimal protocol: `put / get / head / delete / list`.

- `S3ObjectStore` — production; boto3 is imported **lazily** and is never
  required for local dev or tests. Bucket comes from
  `STORAGE_OBJECT_BUCKET` (fail-closed: required when selected).
- `InMemoryObjectStore` — local/dev/tests; one shared per-process store so
  the manager and reconciler observe consistent objects.

Selection follows `settings.runtime.object_backend` (`"s3" | "memory"`,
env `OBJECT_BACKEND`) via `get_object_store()`. Mirroring the repository
layer: missing boto3 falls back to in-memory **only** in
`AETHER_ENV=local`; non-local environments fail closed.

## Storage manager

`StorageManager` is the single policy-enforced write/read path:

- `policy_for(resource_type)` — loads the registry once per process;
  unknown types **fail closed** with `UnknownResourceTypeError`
  (a `KeyError`).
- `externalize(resource_type, tenant_id, records | payload, lineage=...)` —
  refuses when the policy forbids externalization
  (`allow_object_externalization: false` raises
  `StoragePolicyViolationError`) or when the master flag
  (`STORAGE_EXTERNALIZATION_ENABLED`, default **off**) is disabled. Records
  are packed as canonical jsonl, compressed per the policy codec — `zstd`
  via lazy import with a stdlib-gzip fallback when the module is absent
  locally, and the descriptor records the codec **actually used** — then
  written to the object store, sha256-checksummed, and indexed through the
  descriptor repository.
- `hydrate(descriptor)` — fetches the object, verifies the stored bytes
  hash to the descriptor's checksum (`ChecksumMismatchError` on any drift),
  reverses the recorded codec, and decodes jsonl back to records.

## Reconciler

`reconcile(descriptors, object_checksums)` is a **pure function** — no IO,
no S3 — that classifies every divergence between the descriptor index and
the object store:

- **missing objects** — descriptor exists, object is gone
- **orphan objects** — object exists, no descriptor claims it
- **checksum drift** — both exist, bytes no longer hash to the descriptor

It returns a typed `ReconciliationReport` (counts + sorted locator tuples +
`is_clean`). `reconcile_object_store(...)` is the thin IO wrapper that
gathers both sides, runs the core, and emits metrics
(`storage_reconcile_run_total`, `storage_reconcile_missing_object_total`,
`storage_reconcile_orphan_object_total`,
`storage_reconcile_checksum_drift_total`). The reconciler never mutates —
remediation is an operator decision, and scheduled execution is gated by
`STORAGE_RECONCILER_ENABLED` (default **off**).

## Runtime flags

`settings.storage_plane` (`StoragePlaneConfig`, `config/settings.py`):

| Env var | Default | Meaning |
|---|---|---|
| `STORAGE_EXTERNALIZATION_ENABLED` | `false` | Master switch for `StorageManager.externalize()` |
| `STORAGE_RECONCILER_ENABLED` | `false` | Scheduling switch for the storage reconciler |
| `STORAGE_OBJECT_BUCKET` | `""` | S3 bucket for externalized objects (`OBJECT_BACKEND=s3`) |

All default OFF/inert in local; the policy registry and its CI gate are
always enforced regardless of flag state.

## Testing

`tests/unit/test_storage_descriptors.py` exercises descriptor round-trips,
fail-closed policy resolution, externalize/hydrate with checksum
verification and mismatch rejection, the in-memory object store protocol,
reconciler detection of all three drift classes, and the coverage-gate
self-test (every persistent type has a policy; the inventory derives from
the repo, not a hardcoded list). No S3, zstd, or database is required.
