# Cross-Surface Exports + Operability Hardening — Release Train Closeout

**Date**: 2026-07-11
**Branch**: `claude/aether-production-readiness-uerbv8`
**Platform**: v8.12.0

---

## Executive summary

This is the final PR of the production-readiness release train. It closes the two
remaining cross-surface gaps and completes the operability documentation, holding
the platform's core invariant: **no operation is reported successful/valid/
delivered without durable, tenant-scoped, auditable evidence, and there are no
placeholder or fake-success paths.**

Two domains that previously only echoed export JSON inline — targeting
recommendation packages and governance evidence packs — now route through the
durable export service, gaining a verified, checksummed, TTL-bounded artifact.
Three operational runbooks and the jobs-platform source-of-truth doc are added,
and the repo-consistency ownership map is extended so future changes to the jobs,
import, and measurement subsystems are forced to move with their derived surfaces.

Landed green at `make repo-doctor` (25 gates, 0 failed), including the full root
pytest and both frontend builds.

---

## What shipped

### 1. Cross-surface exports route through the durable export service

Two exporters are registered in `services/export/service.py` alongside the
reference audit-log domain (they self-register by decorator on import):

- **`targeting_package`** — exports persisted targeting recommendation packages
  (`services/targeting_intelligence`). `params.export_id` selects one (404 if it
  belongs to another tenant); otherwise the tenant's recent packages are exported.
- **`governance_evidence_pack`** — exports a tenant's own governance evidence
  packs (`services/security/evidence_packs`). `params.evidence_pack_id` /
  `params.pack_type` filter; platform-wide (tenant-less) packs and the operator
  cross-tenant listing stay on the admin route.

Both exporters are **read-only and tenant-scoped** — they never build or mutate,
and every read is scoped to the requesting tenant, so a durable export can never
cross a tenant boundary. Producing a *new* package/pack stays on its originating
route (which persists + audits); this path turns an existing record into a
downloadable artifact.

Registering by decorator (not an explicit call) means every fresh module
identity in the full suite's `sys.modules` churn carries all three exporters —
so a test never reads a partially-populated `EXPORTERS`. `GET /v1/exports/types`
now lists all three
domains; `POST /v1/exports {"export_type": "targeting_package"}` produces a
verified artifact via the same job → serialize → manifest → **checksum-verify** →
download pipeline. No new route or storage code — the job handler already owns
bytes, manifest, verification, and TTL.

**Tests** (`tests/integration/test_export_domain_exporters.py`, 8): registration +
idempotency, tenant-scoped listing, id selection, cross-tenant 404, and an
end-to-end that drives `generate_export_artifact` to a verified artifact whose
bytes contain the exported record.

### 2. Operational runbooks

- **`docs/runbooks/EXPORT_FAILURES.md`** — stuck/failed export jobs, the 32 MB
  cap, the checksum-verify fail-closed guard, download 403/404 (expired/deleted
  tombstones), and the 7-day TTL sweep.
- **`docs/runbooks/IDENTITY_REPAIR.md`** — fragment-aware split (preview →
  execute, three modes, `campaign_only_sameness_blocked`), survivor redirects,
  repo↔graph reconciliation (`missing_in_graph` / `missing_in_repo`), recompute,
  and the identity health check.
- **`docs/runbooks/STAGING_PREFLIGHT.md`** — the preflight gate (env / db /
  redis / http / contracts), the `--dry-run` self-test that proves the gate fails
  closed, and the `/v1/ready` readiness endpoint (advisory workers, 503 semantics).

Each carries `source_files` frontmatter and a reviewed `last_synced_commit`.

### 3. Jobs-platform source of truth

`docs/source-of-truth/JOBS_PLATFORM.md` documents the durable jobs platform
(claim via `FOR UPDATE SKIP LOCKED` + lease, idempotent enqueue, states, DLQ, the
`@register_handler` contract, tenant + Kyber surfaces, scheduler) and — critically
— the **deliberate boundary**: the Redis-backed agent runtime
(`services/agent/*`) is intentionally *not* routed through this Postgres-backed
platform, because agent execution has a different actor/approval model and latency
profile than durable batch jobs.

### 4. Repo-consistency ownership map extended

`docs/source-of-truth/repo_consistency_ownership.json` gains three change
categories — `jobs_platform`, `import_engine`, `measurement_integrity` — so a
future change to any of those subsystems must move with its derived surfaces
(source-linked docs/runbooks, contract twins, generated docs, tests) or the
consistency validator fails. The companion doc and validator tests are updated in
step (`test_all_required_commands_available` now asserts every declared command
across all categories resolves).

---

## Compatibility & guarantees

- **Additive.** The inline targeting/evidence routes are untouched; the export
  service gains two domains without changing any existing surface. No migrations.
- **Tenant isolation absolute.** Both exporters read only the requesting tenant's
  records; a cross-tenant id lookup is a 404, never a silent leak.
- **No fake success.** An export with zero rows produces a real, verified,
  durable empty artifact — an honest record of zero, not a placeholder.
- **Ownership additions are inert for this PR** (it touches export + docs + tests,
  not jobs/imports/measurement source) and only constrain future changes.

---

## Verification

- `make repo-doctor` — 25 gates, 0 failed (full root pytest + npm build/typecheck/
  test + all validators).
- New/updated tests: `tests/integration/test_export_domain_exporters.py` (8),
  `tests/unit/test_consistency_ownership.py` (release-train categories + all
  required commands available). Existing export tests (`test_export_flow`,
  `test_export_artifacts`) remain green; backend imports and registers all three
  exporters at startup.
- Docs: frontmatter validator (325 files, 0 errors), `docs_drift` (0 stale, 0
  missing paths), generated docs regenerated and committed.

This closes the production-readiness release train.
