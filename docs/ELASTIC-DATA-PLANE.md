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
the foundation shipped by FT-7-STORAGE-DESCRIPTORS — the storage-policy
registry, the universal storage descriptor, the object-store protocol, the
policy-driven storage manager, and the reconciler — plus the FT-8 layer built
on top of it: object-backed Bronze compaction, historical read routing, and
cross-store lifecycle propagation (retention / deletion / DSR / legal holds).

## The pieces

| Piece | Where | What it is |
|---|---|---|
| Policy registry | `config/storage_policies.yaml` | One declarative policy per persistent resource type |
| Storage descriptor | `shared/storage/descriptor.py` | Immutable, checksummed handle for any externalized object |
| Object store protocol | `shared/storage/object_store.py` | `put/get/head/delete/list` over S3 or in-memory |
| Manager + reconciler | `shared/storage/manager.py`, `shared/storage/reconciler.py` | Policy-enforced externalize/hydrate; descriptor-vs-object drift detection |
| Bronze compaction (FT-8) | `shared/storage/compaction.py` | Packs cold Bronze payloads into objects; hot searchable metadata stays; hydration routing |
| Cross-store lifecycle (FT-8) | `shared/storage/lifecycle.py` | Retention / deletion / DSR / legal holds across row store + object store + descriptor index |
| Runtime worker (FT-8) | `services/storage_lifecycle/worker.py` | Supervised compaction sweep + scheduled reconciler |

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
`storage_reconcile_checksum_drift_total`). Descriptors tombstoned by the
FT-8 lifecycle (object bytes lawfully removed, structural stub retained) are
excluded — a tombstone is not a missing object. The reconciler never
mutates — remediation is an operator decision. Scheduled execution is gated
by `STORAGE_RECONCILER_ENABLED` (default **off**) and runs on the
`bronze_object_compaction` worker loop.

## Object-backed Bronze (FT-8)

`BronzeObjectCompactor` (`shared/storage/compaction.py`) is the flag-gated
write path that turns the FT-7 foundation on for the Bronze tier
(`bronze_sdk_events`, the typed table written by ingestion V2):

- **Compaction sweep** — rows older than `BRONZE_COMPACTION_MIN_AGE_HOURS`
  whose payload is still hot are packed **per tenant** through
  `StorageManager.externalize("bronze_sdk_events", ...)` (policy codec
  `zstd`, format `jsonl`, per-type permission + master flag enforced there).
  Each packed record carries `bronze_id` plus the subject identifiers
  (`user_id` / `anonymous_id` / `entity_id`) so historical routing can
  address one row's payload and DSR erasure can re-pack an object without a
  subject even after the subject's hot rows are gone.
- **Hot searchable metadata is never deleted.** After the object and its
  descriptor are durable, the row keeps every typed column (event ids,
  types, timestamps, session/anonymous/user/entity ids, `payload_hash`);
  only `payload` is replaced with `{}` while `payload_externalized`,
  `payload_descriptor_id` (typed columns, migration
  `20260727_object_backed_bronze`), and `payload_locator` point at the
  descriptor.
- **Crash safety** — externalize first, strip second: a crash between the
  two duplicates storage (rows still hot + one unreferenced object) but
  never loses data; the retention lifecycle ages the stray object out.
- **Historical routing** — `read_payload(row)` returns hot payloads
  directly and hydrates externalized rows through the descriptor with
  sha256 verification (`ChecksumMismatchError` on drift;
  `BronzePayloadUnavailableError` when the descriptor is missing/tombstoned
  or the row is absent from the packed object).

The sweep runs as the supervised `bronze_object_compaction` WorkerSpec
(`services/runtime/specs.py`, owned by the `materializer` role in
`services/runtime/roles.py`), which also schedules the FT-7 reconciler when
`STORAGE_RECONCILER_ENABLED` is on.

## Lifecycle: retention, deletion, DSR, legal holds (FT-8)

`StorageLifecycle` (`shared/storage/lifecycle.py`) applies the policy
registry's lifecycle fields consistently across **all three stores** an
externalized resource spans — row store, object store, and descriptor index.
`config/storage_policies.yaml` is the only policy source.

- **Retention** (`retention_class`) — `standard` resources age out after
  `STORAGE_RETENTION_STANDARD_DAYS` (objects by descriptor `created_at`,
  never-externalized Bronze rows by `received_at`); `legal` resources are
  never swept by this lifecycle (compliance-owned); `preserve` behavior is
  never swept. The pass rides the existing maintenance retention worker
  (`services/security/retention_worker.py`) behind
  `STORAGE_LIFECYCLE_RETENTION_ENABLED`.
- **Deletion** (`delete_behavior`) — `hard_delete` removes rows, object
  bytes, and descriptor rows entirely; `tombstone` removes the payload bytes
  and subject identifiers but retains structural stubs (rows keep their ids;
  descriptors keep their checksummed audit trail with `tombstoned: true`).
- **DSR erasure** — `dsr_erase_subject(tenant_id, subject_ref)` removes the
  subject's rows per `delete_behavior` and **re-packs** every object
  containing the subject WITHOUT the subject's records (new descriptor with
  lineage to the old one; surviving rows re-pointed); an object owned
  entirely by the subject is deleted outright. Re-pack deliberately
  overrides the master externalization flag — erasure is a compliance
  operation that must work even when the write path is off (the per-type
  policy is still enforced). DSAR cascades reach this path through the
  `object_store:bronze_sdk_events` step in
  `shared/privacy/retention.py::DeletionPlan.build_standard_plan`, executed
  by `ExternalizedBronzeDSRAdapter`.
- **Legal holds** — `storage_legal_holds`
  (`StorageLegalHoldRepository`, migration `20260727_object_backed_bronze`)
  scope to a tenant, optionally one resource type and/or one subject.
  Active holds **block every deletion path** until released: retention
  (which cannot know which subjects live inside a packed object) is blocked
  by any matching hold; a DSR is blocked only by holds covering its subject
  or subject-unscoped holds — re-packing removes only that subject, so a
  hold on a different subject is unaffected. Placing a hold on a type whose
  policy has `legal_hold_supported: false` fails closed
  (`StoragePolicyViolationError`); unknown types fail closed
  (`UnknownResourceTypeError`).

## Runtime flags

`settings.storage_plane` (`StoragePlaneConfig`, `config/settings.py`):

| Env var | Default | Meaning |
|---|---|---|
| `STORAGE_EXTERNALIZATION_ENABLED` | `false` | Master switch for `StorageManager.externalize()` |
| `STORAGE_RECONCILER_ENABLED` | `false` | Scheduling switch for the storage reconciler (runs on the compaction worker) |
| `STORAGE_OBJECT_BUCKET` | `""` | S3 bucket for externalized objects (`OBJECT_BACKEND=s3`) |
| `BRONZE_OBJECT_COMPACTION_ENABLED` | `false` | FT-8 Bronze compaction sweep (also requires the master externalization flag) |
| `BRONZE_COMPACTION_MIN_AGE_HOURS` | `72` | Only rows older than this are packed |
| `BRONZE_COMPACTION_BATCH_SIZE` | `500` | Rows claimed per compaction pass |
| `BRONZE_COMPACTION_INTERVAL_S` | `3600` | Compaction worker sweep interval |
| `STORAGE_LIFECYCLE_RETENTION_ENABLED` | `false` | Retention worker additionally sweeps externalized objects + Bronze rows |
| `STORAGE_RETENTION_STANDARD_DAYS` | `365` | Age applied to `retention_class: standard` by the storage lifecycle |

All default OFF/inert in local; the policy registry and its CI gate are
always enforced regardless of flag state.

## Testing

`tests/unit/test_storage_descriptors.py` exercises descriptor round-trips,
fail-closed policy resolution, externalize/hydrate with checksum
verification and mismatch rejection, the in-memory object store protocol,
reconciler detection of all three drift classes, and the coverage-gate
self-test (every persistent type has a policy; the inventory derives from
the repo, not a hardcoded list). `tests/unit/test_object_backed_bronze.py`
exercises the FT-8 layer: compaction pack → descriptor → hot-metadata-kept,
flag-off no-op, age thresholds, historical routing round trips with
checksum-mismatch rejection, reconciler cleanliness after compaction,
hard_delete vs tombstone retention across stores, legal-class immunity, DSR
re-pack-without-subject propagation (row + object + descriptor), legal-hold
block/release, the DeletionPlan adapter path, and the worker/role/flag
wiring. No S3, zstd, or database is required.
