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
last_synced_commit: "b30af06"
---

# Runbook — Tenant Import Failures

Operate the Tenant Import Engine when an import is stuck, a commit failed, or a
tenant reports missing/duplicated data. All operator actions are on the
**Kyber** console (`/v1/kyber/imports/*`, `require_kyber_operator`); tenant data
is never exposed cross-tenant.

## Lifecycle recap

`created → files_pending → uploaded → analyzing → analyzed → mapping → mapped →
validating → validated → review_required → approved → committing →
committed | partially_committed`. Terminal: `committed`, `partially_committed`,
`failed`, `cancelled`, `rolled_back`. Only an **approved** import commits; the
commit stages every row to Bronze (`BronzeRepository("tenant_import")`, tagged by
commit id) and to the graph (entity/identifier/resource vertices + relationship
edges, each carrying `import_commit_id`).

## Triage

1. **Find the import.** `GET /v1/kyber/imports/timeline` (newest-first, all
   tenants) → locate the session; note its `status` and `id`.
2. **Inspect it.** `GET /v1/kyber/imports/{id}` → the session + its commit
   history (per-commit counts + `row_errors`).

## Symptoms → actions

### Import stuck in `committing`
A commit job is in-flight or its worker died mid-flight. Check the job platform:
`GET /v1/kyber/jobs/timeline?tenant_id=…` for the `import.commit` job. If the job
is `failed`/`expired`, the import session will be `failed` — recover it (below).
If the job is genuinely running, wait; the commit is idempotent (edge creation is
existence-checked, Bronze ingest de-dupes on `provider_record_id`).

### Import in `failed`
The commit raised before completing. **Recover:** `POST /v1/kyber/imports/{id}/requeue`
— this resets the session to `approved` and re-enqueues `import.commit`. The
mapping and validation are stored and unchanged, so the replay is safe. Confirm
via the detail endpoint that a new commit lands `committed`.

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

If a requeue does not resolve a `failed` import after two attempts, capture the
commit's `row_errors` and the `import.commit` job's `job_events`, and escalate to
`platform@aether` — do not hand-edit graph edges or Bronze rows.
## Rollback vertex garbage collection

Rollback and replay now attempt conservative vertex cleanup after revoking the
commit's edges. A vertex is deleted only when it was created by that import
commit, has no active edge references, and has no ownership/history from another
commit. Shared or historically foreign vertices are retained and reported in
`vertices_retained`; safely orphaned vertices are reported in
`vertices_deleted`. Repeating rollback is idempotent. Operators must never
force-delete a retained vertex to make the counts match.
