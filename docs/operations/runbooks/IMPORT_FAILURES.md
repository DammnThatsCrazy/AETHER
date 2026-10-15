---
title: Runbook — Tenant Import Failures
slug: runbooks/import-failures
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: 0.1.0
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 2
source_files: [services/api/ingestion/imports/service.py, services/api/ingestion/imports/commit.py, services/api/ingestion/imports/rights_admission.py, services/api/ingestion/imports/kyber_routes.py, services/api/repositories/imports_repo.py, services/api/repositories/graph_mutation_ledger.py, services/api/shared/graph/graph.py, services/api/shared/graph/mutation_gateway.py]
reviewed_source_commits:
  - commit: "30d10ccb6"
    reason: "Reviewed the CSV Rights Authority import-admission change. This runbook now describes the required purposes/source grant, fail-closed no-write behavior, persisted attempt history, and recovery path."
  - commit: "af851e21c"
    reason: "Reviewed commit failure and retry handling for missing graph-ledger Rights ancestry, including repair of an already projected same-commit edge."
source_hashes:
  "services/api/ingestion/imports/commit.py": "sha256:8c9a53efb8ff51e7a28a301ca2d047d91c8732bc49782608ac547c1f596a9cf8"
  "services/api/ingestion/imports/kyber_routes.py": "sha256:72539f001ee0853b94b1c2abce5d8f2eb98231b2676bf124e6f9c2e84bdeb749"
  "services/api/ingestion/imports/rights_admission.py": "sha256:32d5bcdec7c74afc55e6c86e45b89f6930169a912bf185099d90fe27db3f3f7a"
  "services/api/ingestion/imports/service.py": "sha256:6d9c346282442e8af10b462367ebb187ca0d574521fe5f13b2f68152aeeacd98"
  "services/api/repositories/graph_mutation_ledger.py": "sha256:b347022c798f92360a89fb13cae1a2086792510cd37cb9b92c3ddc9988640f31"
  "services/api/repositories/imports_repo.py": "sha256:6bdc0f6089e66d63b93456e5cf99b79653b896a338e3548f19551c48ae3c4f0e"
  "services/api/shared/graph/graph.py": "sha256:cf8d68c1c10b1432ee9febf3d5368b88087ffc2255c4e80d8c73382bc8fafb24"
  "services/api/shared/graph/mutation_gateway.py": "sha256:f67610c8c7f70fb131c7d1cc531dd0477050d0e2969bdc91d392f5bac56820dc"
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

Mapped email and phone identifiers are additionally persisted as observed claims
under tenant- and upload-scoped CSV source identities. Claims retain stable
import/file/row provenance and stay unresolved until the identity resolver has
independent person-level link authorization. The candidate adapter requires the
claim's exact commit to be the import's current, completed commit and excludes
rolled-back, failed, and in-progress commits. Tenant import approval alone does
not authorize identity stitching. Email and phone claim values are stored as
tenant/type-scoped HMAC digests only; their raw values are not persisted in
identity-claim rows. Failure to persist this evidence fails the commit, and
retry uses the same source namespace and row keys to avoid duplicates.

An interrupted replay preserves its replacement `active_commit_id` and marks
the session `FAILED`. Requeue resumes that replay under the same commit ID.
The superseded commit is already marked rolled back, and candidate lookup keeps
both the prior evidence and the incomplete replacement hidden until the resumed
commit row is durable and the session returns to `COMPLETED`.

If a staging rehearsal is being torn down after an import-related probe, do
not use the import rollback path as a substitute for tenant deletion. The
admin cleanup operation removes only graph projection vertices and edges owned
by the run-scoped tenant (including legacy `tenant_id` edge tags) and leaves
unscoped/system vertices and append-only import or audit evidence intact. A
backend error is a hard stop; rerun cleanup after the graph backend is healthy.

The **authoritative** lifecycle is the import-session FSM (`lifecycle_state`:
`CREATED → UPLOADED → VALIDATING → VALIDATED → NORMALIZING → COMMITTING →
PROJECTING → RECONCILING → COMPLETED`, plus `REJECTED`, `FAILED`, and the
terminals `DEAD_LETTERED` / `ROLLED_BACK`). The lowercase `status` above is a
**parity-locked legacy projection** (`services/api/value/card_linked_payments/import_session.py`),
kept so the frontend and existing commit/approve surfaces keep parsing. When the
two could disagree, trust `lifecycle_state`.

The graph preview is non-mutating and is the import-to-graph lineage seam. It
reports the mapping version, source/session checksum, per-file checksums and
row/mapped/error counts. Its `rights_context` is deliberately
`authorization_status: not_evaluated` with `activation_allowed: false` and
`reason: preview_only`; only the approved commit path can activate data.

## Triage

1. **Find the import.** `GET /v1/kyber/imports/timeline` (newest-first, all
   tenants) → locate the session; note its `status` and `id`.
2. **Inspect it.** `GET /v1/kyber/imports/{id}` → the session + its commit
   history (per-commit counts + `row_errors`).

## Symptoms → actions

### Import stuck in `committing`
A commit job is in-flight or its worker died mid-flight. Check the job platform:
`GET /v1/kyber/jobs/timeline?tenant_id=…` for the `import.commit` job. If the job
is `failed`, the import session is `failed` too (the handler marks it) — recover
it (below). If the job is genuinely running, wait; the commit is idempotent
(edge creation is existence-checked, Bronze ingest de-dupes on
`provider_record_id`). A session that has sat in `committing` past its requeue
window with no live worker is **stranded**: the commit can only be *resumed*, never
restarted. `commit_import` re-enters `COMMITTING` (its re-entrant self-arc) under
the preserved commit id (`active_commit_id`) and resumes idempotently, so a
re-run never double-applies staging. Note the Kyber status-requeue endpoint
below accepts only sessions whose legacy `status` is `failed`; a stranded
`committing` / mid-finalization session is resumed by re-driving the
`import.commit` job (its own retry path), not by that status route.

A session stranded **mid-finalization** (`projecting` / `reconciling` — a
transient failure *between* finalization transitions, after staging succeeded)
is resumable the same way: re-running `commit_import` advances only the remaining
lifecycle arcs to `completed` — nothing is re-staged and the commit row is never
re-created, so the resume cannot double-apply projections/commits.

### Import stuck in `validating`
A transient failure during the validation dry-run (file retrieval, parsing,
schema construction, or `validate_mapping`) returns the session to `uploaded`
with the reason recorded in `failure_reason` — it is never left pinned in
`validating`. A retry re-enters `validating` legally and completes the
dry-run. A session observed in `validating` with no job activity is still
in-flight; the fallback above means a wedged `validating` session should not
occur.

### Import in `failed`
The commit raised before completing. **Recover:** `POST /v1/kyber/imports/{id}/requeue`
(accepts only sessions whose legacy `status` is `failed`) — it resets the
session's `status` to `approved` and re-enqueues `import.commit`; when the job
runs, `commit_import` re-enters `COMMITTING` (legacy `status` projects
`committing`) and resumes under the preserved commit id. The mapping and
validation are stored and unchanged, so the replay is safe; `failure_reason` and
`retry_count` are preserved for audit. A **stranded** `committing` session (worker
died mid-commit) is resumed — never restarted — only when the `import.commit` job
is re-driven (see above); the status-requeue endpoint itself never accepts a
`committing` session. Confirm via the detail endpoint that the session lands
`committed`.

If the `import.commit` job reports
`import_graph_mutation_rights_ancestry_not_durable`, the Rights Authority
admission succeeded, but the graph mutation ledger did not durably retain a
required decision reference. The graph gateway is in shadow mode for CSV
projection, so the graph write can succeed before its ledger append fails. The
commit is not recorded as complete. Requeue the failed import under its
preserved `active_commit_id`; Bronze and vertex writes are idempotent, and an
already projected edge owned by this commit is repaired in the ledger without
being projected again. Do not delete graph rows or edit ledger rows manually.
If the referenced ledger row is missing or has no durable `rdec_*` reference,
the retry fails closed; escalate the durable ledger/rights evidence for review.

If the commit fails with a `Conflict` raised by a graph vertex write
(`VertexOwnershipError`), a mapped vertex id already exists in the graph under
another tenant, under no tenant, or with `tenantId` and `tenant_id` naming
different tenants. Graph writes never change a vertex's owner, so a requeue
fails the same way. Do not edit the vertex; escalate with the vertex id so its
ownership can be reviewed.

### Import commit denied by consent policy (`import_consent_policy_denied`)
The WS-B3 T-class commit gate runs **before any Bronze write** (after staging,
so a denial fails the commit closed with no partial Bronze). It scrubs
secret-key columns from the persisted Bronze payload copy (graph-building
records keep the governor-approved mapped values) and can deny the commit when
the staged rows fingerprint or map a tenant-prohibited data class. Denials
raise `ConflictError("import_consent_policy_denied:...")`, land the session
`failed`, and record the reason in `failure_reason`. Causes:

- `mapping_source_column_unresolved` — a mapping `source_column` is empty or
  does not resolve against the **real** staged columns. Default-deny: a client
  cannot launder prohibited content under a label no policy ever sees.
- `fingerprinting_not_authorized` / `data_classification_denied` — the staged
  rows carry fingerprinting fields or a data class the tenant compliance
  profile prohibits (`evaluate_data_policy` is default-allow, so a tenant with
  no profile only ever trips on fingerprinting).
- `enforcement_disabled` — `IMPORTS_CONSENT_POLICY_ENABLED=false`. Disabling
  the flag does **not** bypass the gate; OFF **denies** the commit, because an
  import must never skip data-policy.

A requeue re-runs the gate and re-denies (each attempt increments
`retry_count`, walking the session toward dead-letter), so this is **not** a
transient commit failure: fix the source data / mapping (`source_column` must
be a real staged column) or the tenant compliance profile, then re-drive.

### Import commit denied by Rights Authority (`import_rights_denied`)

CSV commit also requires durable allowed Rights Authority decisions for
`tenant_lake`, `write_tenant_graph`, and `tenant_insights`, plus one active
grant for the exact tenant and import `source_id`. The grant is held against
revocation while the commit writes. This admission runs before identity,
Bronze, Silver, or graph writes; import approval and consent checks do not
replace the required source grant.

Inspect the tenant-scoped import detail and its
`session.rights_admissions[commit_id]` history for the attempt status,
`reason_codes`, source grant reference, and any durable `rdec_*` references.
Common reasons include `approver_missing`, `source_grant_missing_or_ambiguous`,
`source_grant_revoked_or_changed`, `rights_decision_missing`,
`rights_decision_scope_invalid`, `durable_decision_ref_missing`,
`rights_authority_unavailable`, `grant_store_not_durable`, and
`grant_store_unavailable`. Policy-specific denial codes may also be present.

Have the tenant administrator establish or restore an active grant for the
exact source through the Rights Authority workflow, or have the platform owner
repair the configured durable rights store. Then requeue the failed import so
the retry records fresh decisions. Do not edit import rows or rights ledgers
directly. A refusal before data writes is expected fail-closed behavior; a
successful HTTP or job acknowledgement alone is not proof of graph hydration.

### `partially_committed`
Some rows failed a transform at commit time (rare — validation runs first). The
committed rows are live; inspect `commits[].row_errors` for the failures. Options:
fix the source data and run a fresh import, or **replay** (`POST /v1/imports/{id}/replay`,
tenant-side) which revokes the prior commit's edges and re-stages.

### Tenant reports wrong/duplicated data after an import
**Roll it back:** `POST /v1/imports/{id}/rollback` (tenant admin) revokes exactly
the commit's graph edges and deletes its Bronze rows for the authenticated
tenant — the uploaded file bytes are never touched, so the import can be
corrected and re-committed via **replay**. A commit with more than 10,000
matching Bronze rows is refused before graph or Bronze mutation; escalate the
case for an approved recovery plan rather than deleting rows directly.
This import rollback does not remove the commit's best-effort
`silver_import_facts` projection; do not treat rollback success as proof of
Silver cleanup. Escalate any required Silver cleanup for an approved recovery
plan.
Upserted vertices are never force-deleted: rollback garbage-collects only vertices
the backend proves orphaned and owned by this commit (see below) — shared or
historically foreign vertices persist, and revoking the edges disconnects the
import's contribution.

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
`platform@aether` — do not hand-edit graph edges or Bronze rows. A session that
exhausts its retry budget is **dead-lettered** (`lifecycle_state` =
`DEAD_LETTERED`, terminal — `status` projects `failed`) and has no transition
out: it needs an operator decision (root-cause, then re-drive), never a silent
auto-retry.
## Rollback vertex garbage collection

Rollback and replay now attempt conservative vertex cleanup after revoking the
commit's edges. A vertex is deleted only when it was created by that import
commit, has no active edge references, and has no ownership/history from another
commit. Shared or historically foreign vertices are retained and reported in
`vertices_retained`; safely orphaned vertices are reported in
`vertices_deleted`. Repeating rollback is idempotent. Operators must never
force-delete a retained vertex to make the counts match.
