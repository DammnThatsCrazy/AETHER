---
title: CI Gate Reference
slug: ci/gate-reference
section: reference
visibility: I
audience: [dev-senior, ops]
status: stable
since_version: "0.1.0"
source_files: [Makefile, .github/workflows/repo-consistency.yml, .github/workflows/repo-health.yml]
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 2
---

# CI Gate Reference

Quick reference for the Makefile targets that gate correctness, docs, and
release readiness in Aether. See `docs/ci/architecture.md` for how these fit
together in CI, and `docs/source-of-truth/REPO_CONSISTENCY_OWNERSHIP.md` for
the canonical authority statement. "Blocking" below means the target (or the
workflow job that runs it) fails closed and stops the PR/merge/release it
gates — not that every target runs on every PR.

## Primary authority gates

| Command | What it checks | When it runs | Blocking? |
|---|---|---|---|
| `make verification-disposition BASE=<base> EXECUTE=1` | Runs `scripts/verification_disposition.py`: selects the minimum verification lane via the impact graph and executes it. | Every PR and push to `main`, via `repo-consistency.yml` (`selected-verification` job); locally before opening a PR. | **Yes — the single normal-PR authority.** |
| `make ci-check` | `scripts/repo_doctor.py --ci`: full repo consistency, fails if any generator produces a diff. | On demand for local/trusted-main/nightly/release evidence; not run as a PR gate step by `repo-consistency.yml`. | No — broad evidence, reported separately, never a second PR blocker. |
| `make release-gate` | `repo_doctor.py --ci` + `production_status.py --strict` + `ops_readiness.py` + founding-tenant/control-spine, cost, delivery, SDK, and security/supply-chain checks (see below). | Manual `workflow_dispatch` of `repo-consistency.yml` (`release-gate` job); locally when a PR claims release readiness. | Yes, but **release-only** — never evaluated on a normal PR. |
| `make repo-doctor` | `scripts/repo_doctor.py --check`: full repo consistency validation, no mutations. | Ad hoc / local development; underlies `docs-check`, `ci-check`, and `release-gate`. | Not standalone — insufficient alone per `CLAUDE.md` ("must not claim a PR is complete based only on ... `make repo-doctor` alone"). |
| `make repo-doctor-fix` | `scripts/repo_doctor.py --fix`: regenerates generated docs and syncs, then validates. | Local remediation when `repo-doctor`/`docs-check` reports drift; also what `AGENTS.md`/`CLAUDE.md` mandate for fixing generated-doc drift. | N/A (mutating, not a gate). |

## Docs gates

| Command | What it checks | When it runs | Blocking? |
|---|---|---|---|
| `make docs-check` | `scripts/repo_doctor.py --check --docs-only`: docs-focused validation with shared consistency preflight. | `repo-health.yml` → `lint-docs` job, on PRs and trusted non-PR events. | Advisory on PRs (`continue-on-error: true`); not a required check. |
| `make docs-generate` (alias `docs-fix`) | `scripts/repo_doctor.py --fix --docs-only`: regenerates generated and sync-managed docs (never authored source-linked docs). | Local, before running the disposition, when docs/generator/contract inputs changed. | N/A (mutating). Required step per PR template before the disposition run. |
| `make docs-generate-changed` | `scripts/docs_drift.py --update`: updates only source-linked docs whose declared `source_files` content changed. | Local, after reviewing stale source-linked docs. | N/A (mutating) — must follow, never precede, human review of the diff. |
| `make docs-verify-idempotent` | `scripts/docs_idempotency.py`: proves two documentation-generation passes produce identical output. | Part of `ci-check`'s generator-idempotency coverage. | Part of the `ci-check` broad-evidence bundle. |
| `python scripts/docs_drift.py --strict` | Source-linked docs drift detection against declared `source_files`. | Failure diagnostics in `repo-health.yml` → `lint-docs`; ad hoc. | Advisory (diagnostic), feeds into `docs-check`. |
| `make validate-frontmatter` | YAML frontmatter on `docs/*.md` against `scripts/docs_schema.json`. | Part of `docs-check` / `repo-doctor`. | Part of the docs gate bundle. |

## Contract, SDK, and version gates

| Command | What it checks | When it runs | Blocking? |
|---|---|---|---|
| `python scripts/validate_contracts.py` | Contract consistency across the repo. | `repo-health.yml` → `main-integration` (push to `main`); part of `make docs`. | Blocking for `main-integration`, which itself is scoped to `main`, not PRs. |
| `python scripts/validate_sdk_release_alignment.py` | SDK/release alignment. | Part of `make release-gate`. | Release-only. |
| `python scripts/bump_version.py --check` | `pyproject.toml` is the canonical version source; checks alignment. | Local / ad hoc, whenever `pyproject.toml` changes. | Required by `CLAUDE.md` when the version surface changes; not a separate CI job. |
| `make validate-impact-graph` | Validates `config/impact_graph.json` and router bindings. | `repo-health.yml` → `main-integration`; ad hoc. | Blocking for `main-integration` (push to `main`). |
| `make validate-telemetry-contracts` | Repository-owned telemetry event contracts. | `repo-consistency.yml` → `classify-change` job (every PR). | Yes — part of the blocking `classify-change` job. |
| `make validate-verification-policy` | The single normal-PR verification authority policy is internally consistent. | Ad hoc / local. | Advisory unless invoked as part of a gate. |

## Test lanes (impact-graph routed)

| Command | What it checks | When it runs | Blocking? |
|---|---|---|---|
| `make test-fast` | Change-aware fast lane via `scripts/check_router.py --lane fast`. | Local, quick feedback. | No — a subset the router may select, not a standalone gate. |
| `make test-pr` | Change-aware PR lane via `scripts/check_router.py --lane pr`. | Local approximation of what a PR-scoped disposition would run. | No — same caveat; the real authority is `verification-disposition`. |
| `make test-integration` | Selected integration lane. | Local; conceptually behind `main-integration`. | No, standalone. |
| `make test-regression` | Selected regression lane. | Local; conceptually behind the nightly `repo-health.yml` `validate` job. | No, standalone. |
| `make test-release` | Selected release lane. | Local; conceptually behind `release-gate`. | No, standalone. |
| `make test` | Every Python test subsystem: root `tests/`, full backend tree, ML `tests/` (run separately to avoid conftest collisions). | Local; nightly/`workflow_dispatch` equivalents run as discrete jobs in `repo-health.yml` (`python-tests`, `backend-tests`, `ml-tests`). | No — nightly/dispatch only in CI, not a PR gate. |

## ML gates

| Command | What it checks | When it runs | Blocking? |
|---|---|---|---|
| `make ml-validate` | ML registry + contract consistency. | `repo-health.yml` → `ml-tests` (nightly/dispatch). | Blocking for that nightly/dispatch job only. |
| `make ml-docs-check` | ML documentation consistency. | `repo-health.yml` → `ml-tests` (nightly/dispatch). | Same as above. |
| `make ml-ci` | All blocking ML CI gates (`ml-validate` + `ml-test` + `ml-train-smoke` + `ml-artifact-verify` + `ml-docs-check`), excludes `ml-container-build`. | Local composite; not invoked as a single CI step by name (CI runs the constituent steps). | Local convenience wrapper. |

## Frontend / TypeScript gates

| Command | What it checks | When it runs | Blocking? |
|---|---|---|---|
| `npm run lint` / `npm run typecheck` / `npm run build` / `npm run test` | TypeScript lint, type-check, build, unit tests. | `repo-health.yml` → `typescript` (nightly/dispatch). | Blocking for that job only; not a PR gate directly (the impact-graph-selected build in `repo-consistency.yml` covers PR-scoped builds). |
| `npm run validate:ts-public-exports` | TypeScript public export/package boundary validation. | `repo-health.yml` → `typescript` (nightly/dispatch). | Same. |
| `make frontend-data-truth` | Enforces Aether/Kyber runtime source data-truth boundaries. | `repo-consistency.yml` → `selected-verification` (`npm run validate:frontend-data-truth`), every PR. | **Yes — every PR**, as a step ahead of the disposition run. |
| `make frontend-branding` | Enforces canonical brand migration seams. | `repo-consistency.yml` → `selected-verification` (`npm run validate:frontend-branding`), every PR. | **Yes — every PR.** |
| `npm run deps:circular` | Circular dependency check (madge). | `repo-health.yml` → `typescript` (nightly/dispatch). | Blocking for that job only. |
| `npm run security:secrets` / `npm run security:deps` | Secret scanning / dependency audit. | `repo-health.yml` → `typescript` (nightly/dispatch). | Blocking for that job only; see `make secret-scan` / `make supply-chain-check` for the release-gate equivalents. |

## Security / supply-chain / release-only gates

| Command | What it checks | When it runs | Blocking? |
|---|---|---|---|
| `make secret-scan` | Fail-closed secret scan of tracked files. | Part of `make security-release-check`, invoked from `make release-gate`. | Release-only. |
| `make supply-chain-check` | Fail-closed supply-chain gate: npm production CRITICAL vulns + required SBOM generation. | Part of `make release-gate`. | Release-only. |
| `make security-release-check` | Fail-closed security gate: secrets + security-control regressions. | Part of `make release-gate`. | Release-only. |
| `make ops-readiness` | One-person ops readiness gate (flags, stores, bridge fail-closed, approval gating). | Part of `make release-gate`. | Release-only. |
| `make production-status` | Readiness scorecard + blockers. | Ad hoc; strict mode (`production_status.py --strict`) runs inside `make release-gate`. | Advisory standalone; blocking (strict) inside `release-gate`. |
| `python scripts/staging_preflight.py --dry-run` | Staging preflight logic self-test. | `repo-health.yml` → `staging-preflight-dry-run` (nightly/dispatch); also the last step of `repo-consistency.yml`'s `release-gate` job. | Blocking within those specific jobs, not a PR gate. |
| `make integration-durable` | Production-shaped durable integration suite (requires Docker). | `repo-health.yml` → `main-integration`, push to `main` only. | Blocking for that job, post-merge only. |

## Notes

- Targets not listed here (demo seeding, dev-stack orchestration, delivery
  profile/environment resolution, etc.) are operational or local-development
  helpers, not CI/PR gates — run `make help`-style `grep '##' Makefile` for
  the full target list.
- A command appearing only under "nightly/dispatch" or "release-only" columns
  above is never sufficient, by itself, to satisfy the normal-PR authority.
  Per `CLAUDE.md`, `make verification-disposition BASE=<base> EXECUTE=1` is
  the only thing that does.
