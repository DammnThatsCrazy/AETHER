---
title: Runbook — Tenant Import Failures
slug: runbooks/import-failures
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 2
source_files:
  - Backend Architecture/aether-backend/services/imports/service.py
  - Backend Architecture/aether-backend/services/imports/commit.py
  - Backend Architecture/aether-backend/services/imports/kyber_routes.py
  - Backend Architecture/aether-backend/repositories/imports_repo.py
  - Backend Architecture/aether-backend/shared/graph/graph.py
last_synced_commit: "4ce7e0fc"
---

# Runbook — Tenant Import Failures

Operate the Tenant Import Engine when an import is stuck, a commit failed, or a
tenant reports missing/duplicated data. All operator actions are on the
**Kyber** console (`/v1/kyber/imports/*`, `require_kyber_operator`); tenant data
is never exposed cross-tenant.

## Lifecycle recap

The session row's `lifecycle_state` is authoritative (the import-session FSM);
the legacy `status` column remains as a parity-safe projection so the frontend
enum keeps parsing, and retains fine-grained states (`analyzing`, `mapped`,
`review_required`, …) the FSM does not model.

Program lifecycle: `CREATED → UPLOADED → VALIDATING → VALIDATED →
NORMALIZING → COMMITTING → PROJECTING → RECONCILING → COMPLETED`.
- Failed validation lands in **REJECTED** (projected `review_required`) — never
  `validated`/`review_required` as if it passed.
- Approval enters **NORMALIZING** (projected `approved`); a cancelled session is
  **ROLLED_BACK** (projected `cancelled`).
- Hard stops: `COMMITTED`/`partially_committed`, `FAILED` (retryable up to the
  budget), `DEAD_LETTERED` (sweeper), `ROLLED_BACK`.

Only a `NORMALIZING`/`approved`, retryable `FAILED`, or stranded `COMMITTING`
session commits; the commit stages every row to Bronze
(`BronzeRepository("tenant_import")`, tagged by commit id) and to the graph
(entity/identifier/resource vertices + relationship edges, each carrying
`import_commit_id`).

## Triage

1. **Find the import.** `GET /v1/kyber/imports/timeline` (newest-first, all
   tenants) → locate the session; note its `status` and `id`.
2. **Inspect it.** `GET /v1/kyber/imports/{id}` → the session + its commit
   history (per-commit counts + `row_errors`).

## Symptoms → actions

### Import stuck in `committing`
A commit job is in-flight or its worker died mid-flight. Check the job platform:
`GET /v1/kyber/jobs/timeline?tenant_id=…` for the `import.commit` job. If the job
is `failed`/`expired`, the session is marked `FAILED` with a `failure_reason` —
recover it (below). If the job is genuinely running, wait; the commit is
idempotent (edge creation is existence-checked, Bronze ingest de-dupes on
`provider_record_id`). A `COMMITTING` session whose worker died without a record
(unrecorded crash) becomes **stranded**: after 5 minutes (`REQUEUE_COMMITTING_TIMEOUT_S`)
it is requeueable (below), and after 24 h the sweeper dead-letters it.

### Import in `failed`
The commit raised before completing. **Recover:** `POST /v1/kyber/imports/{id}/requeue`
— the FSM re-stages a `FAILED` (or stranded `COMMITTING`) session into
`COMMITTING` and re-enqueues `import.commit`. This is *not* a reset: the mapping,
validation, `failure_reason`, and `retry_count` are preserved for audit, and the
commit resumes idempotently under the same commit id. Confirm via the detail
endpoint that a new commit lands `committed`. Each requeue increments
`retry_count`; at the retry budget (5) the session becomes **dead-letterable** —
`POST /v1/kyber/imports/sweep-stranded` (or the periodic sweeper) moves it to
`DEAD_LETTERED`, and no further requeue is accepted.

### `partially_committed`
Some rows failed a transform at commit time (rare — validation runs first). The
committed rows are live; inspect `commits[].row_errors` for the failures. Options:
fix the source data and run a fresh import, or **replay** (`POST /v1/imports/{id}/replay`,
tenant-side) which revokes the prior commit's edges and re-stages.

### Tenant reports wrong/duplicated data after an import
**Roll it back:** `POST /v1/imports/{id}/rollback` (tenant admin) revokes exactly
the commit's graph edges and deletes its Bronze rows — the uploaded file bytes are
never touched, so the import can be corrected and re-committed via **replay**.
Note: upserted vertices persist (the graph client has no vertex delete; a vertex
may be shared) — revoking the edges disconnects the import's contribution.

### `POST /v1/imports` returns 409 "imports in flight (max …)"
The tenant hit the per-tenant concurrent-import cap (`MAX_CONCURRENT_IMPORTS`,
default 25 non-terminal sessions). Have them finish, cancel, or roll back an
existing import. This is a fail-closed guard, not a bug.

### Upload rejected `unsupported_format`
Only CSV / JSON / JSONL are accepted; xlsx / parquet / zip are refused by
extension **and** content sniff (the zip-bomb class is eliminated — no archive
support). Have the tenant export to CSV/JSON.

## Escalation

A `FAILED` session is dead-lettered once its `retry_count` reaches the retry
budget (5) — `POST /v1/kyber/imports/sweep-stranded` runs one sweeper pass, or
the periodic sweeper handles it. If a requeue does not resolve a `failed` import
before then, capture the commit's `row_errors` and the `import.commit` job's
`job_events`, and escalate to `platform@aether` — do not hand-edit graph edges,
Bronze rows, or a session's `lifecycle_state`.
## Rollback vertex garbage collection

Rollback and replay now attempt conservative vertex cleanup after revoking the
commit's edges. A vertex is deleted only when it was created by that import
commit, has no active edge references, and has no ownership/history from another
commit. Shared or historically foreign vertices are retained and reported in
`vertices_retained`; safely orphaned vertices are reported in
`vertices_deleted`. Repeating rollback is idempotent. Operators must never
force-delete a retained vertex to make the counts match.
