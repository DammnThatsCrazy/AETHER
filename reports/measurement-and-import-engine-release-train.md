# Measurement Integrity Plane + Tenant Import Engine — Release Train Report

**Date**: 2026-07-11
**Branch**: `claude/aether-production-readiness-uerbv8`
**Platform**: v8.12.0

---

## Executive summary

This train hardens two subsystems to the platform's core invariant — **no operation
is reported successful/valid/committed without durable, tenant-scoped, auditable
evidence, and no placeholder or fake-success paths.** It landed as a sequence of
individually-green PRs (each passing `make repo-doctor` at 25 gates, 0 failed):

1. **Measurement Integrity Plane** — a metric is never a bare `0` when the data is
   missing or insufficient; results are immutable and correctable only by an
   auditable restatement.
2. **Tenant Import Engine** — a tenant's file becomes graph + Bronze data only after
   analyze → map → validate → approve → commit, with fully reversible rollback and a
   Kyber operator console.

Both are scored **4/5** in `scripts/production_status.py` (release-ready with minor
gaps; 5 requires production traffic at scale) — see the scorecard and
`docs/productization/aether_productization_audit.md`, updated together per the
CLAUDE.md production-claims rule.

---

## What shipped, by PR

| PR | Title | State |
|---|---|---|
| #429 | Measurement Integrity Plane + Import Engine understand-half | merged |
| #430 | Import Engine commit / replay / rollback (Bronze + graph, lineage) | merged |
| #431 | Import Engine Kyber operator ops + concurrency cap + runbook | merged |
| (follow-on) | Tenant Import UI (frontend) | in review |
| (follow-on) | Production-readiness capstone (Noesis read-only constraints + scorecard + this report) | in review |

### Measurement Integrity Plane (#429)
- `shared/measurement/` — `ValueState` (observed/estimated/insufficient_data/
  not_applicable/missing_inputs/degraded); calculators return `(value|None, state)`.
  Frozen `MeasurementContext` + deterministic `context_hash`. `MeasurementResult`
  enforces the value/value_state invariant (finite value iff the state allows one;
  NaN/inf/out-of-bounds/negative counts rejected). In-code metric registry
  (`allows_probability` gate). Wilson + seeded bootstrap uncertainty.
- `repositories/measurement_results_repo.py` + migration `20260716` — immutable
  `measurement_results` (partial unique index: one active result per
  `(tenant, metric, version, context_hash)`); **supersession is the only mutation**
  (stamp `superseded_by` + insert new + `measurement_restatements` record, atomic
  under Postgres). DDL string-identical to the migration (parity-tested).
- Routes `/v1/measurement/{definitions,results,results/{id}/explain}` — tenant-scoped;
  explain returns value + value_state, lineage, sufficiency, uncertainty, and the
  restatement chain.

### Tenant Import Engine (#429 understand-half, #430 mutation-half, #431 ops)
- Contract twins `packages/shared/imports.ts` ⇄ `services/imports/contracts.py`
  (parity-tested): lifecycle, 9 primitives + field registry, transforms, column
  types, governance sensitivity.
- Analyze (stdlib CSV/JSON/JSONL + PII/secret/identifier/governance detection;
  xlsx/parquet/zip rejected — zip-bomb class eliminated), map + template drift,
  validate (dry-run, capped row errors, governance review gate).
- Commit stages each row to **Bronze** (`BronzeRepository("tenant_import")`, tagged
  by commit id) and upserts entity/identifier/resource vertices + relationship edges
  into the **graph** with `import_commit_id` lineage, idempotently, on the durable
  jobs platform (`import.commit` / `import.replay`). **Rollback** revokes exactly the
  commit's edges + deletes its Bronze rows (source bytes untouched); **replay**
  re-stages under a fresh commit. `partially_committed` for mixed outcomes.
- Persistence: `import_files` direct-SQL BYTEA store (DDL parity-tested vs migration
  `20260718`); JSONB session/schema/mapping/template/validation/commit/rollback
  records (`20260719`), tenant-isolated at the repo boundary.
- Operability: per-tenant `MAX_CONCURRENT_IMPORTS` cap; Kyber console
  `/v1/kyber/imports` (timeline / detail / failed-import requeue, `require_kyber_operator`);
  `docs/runbooks/IMPORT_FAILURES.md`.

---

## Migrations (single alembic head preserved throughout)

`20260716_measurement_integrity` → `20260718_import_engine` → `20260719_import_commit`.
Each direct-SQL BYTEA/immutable repo carries a DDL constant string-identical to its
migration, asserted by a parity test. BaseRepository-shaped tables use the exact
`_ensure_table` shape so `alembic upgrade head` and runtime auto-create converge.

## Contracts

- `packages/shared/imports.ts` ⇄ `services/imports/contracts.py` — const-array parity
  test (`tests/contracts/test_imports_parity.py`).
- No SDK / event / consent schema changes in the import/measurement train.

## Compatibility & flags

- Additive throughout: new routers mounted, no existing route/contract changed.
- No new runtime feature flags required; the import engine is always-on and
  tenant-scoped. Object storage is Postgres BYTEA behind an `ImportStorageAdapter`
  Protocol (the S3 seam).

## Tests

- Full root suite: **2486 passed** (import engine adds contract parity, analyzer,
  validation, mapping, BYTEA repo DDL parity, commit/replay/rollback e2e, Kyber ops,
  concurrency cap; measurement adds contract, repo, and integration suites).
- Robustness: diagnosed and fixed a recurring cross-module test-isolation class
  (lazy in-memory store resolution, module-level job handlers, pinned repo accessors)
  — all no-ops in production's single-module-identity world, verified under the full
  xdist suite.

## Verification commands

```bash
make repo-doctor                 # 25 gates, 0 failed (full pytest + npm + validators)
make production-status           # scorecard incl. the two new 4/5 areas
python -m pytest tests -q        # 2486 passed
# reference scenario (AETHER_ENV=local): create import → upload CSV → analyze →
# map → validate → approve → commit → verify Bronze + graph edges + lineage →
# rollback → verify edges revoked + Bronze deleted; run a measurement supersession
# and read the restatement chain via /v1/measurement/results/{id}/explain.
```

## Limitations (honest)

- **Measurement**: registry is in-code (no generated `metric-registry.json` TS twin
  yet); Campaign360 calculators do not yet thread `MeasurementContext` end-to-end.
- **Imports**: Silver import projector deferred (commit stages Bronze + graph
  directly); rollback revokes edges + deletes Bronze but does not delete upserted
  vertices (the graph client exposes no vertex delete; a vertex may be shared);
  validation is inline (files are size-capped). A tenant UI is the follow-on frontend PR.
- Neither subsystem has carried production traffic at scale — hence 4/5, not 5/5.

## Risks & mitigations

- **Migration/runtime shape divergence** → DDL-parity tests + BaseRepository-shape
  match; single-head regression test.
- **Graph mutation correctness** → idempotent (existence-checked) edge creation;
  recorded `created_edges` enable exact rollback; in-memory graph parity in tests.
- **Governance leakage** → identifier/governance-fact/PII mappings force
  `review_required`; approval needs admin + a passing validation; Kyber routes are
  `require_kyber_operator`-gated (repo-wide boundary test enforces this).

## Evidence per acceptance criterion (no fake success)

- *"A metric is never 0 on missing data"* → `ValueState` + `MeasurementResult`
  value/value_state invariant + `test_missing_is_not_zero` (only OBSERVED/ESTIMATED
  are value-bearing).
- *"Corrections are auditable"* → supersession-only mutation + `measurement_restatements`
  + restatement-chain read.
- *"Nothing imported without evidence"* → uploaded bytes carry sha256; commit records
  real per-primitive counts; `partially_committed` never masks failures.
- *"Reversible"* → rollback revokes exactly the recorded edges + deletes the commit's
  Bronze rows; test asserts both.
- *"Tenant isolation absolute"* → every repo read is tenant-scoped (cross-tenant →
  NotFoundError); Kyber cross-tenant surfaces are operator-gated.
