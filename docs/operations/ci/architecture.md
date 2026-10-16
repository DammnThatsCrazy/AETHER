---
title: CI Architecture
slug: ci/architecture
section: reference
visibility: I
audience: [dev-senior, ops]
status: stable
since_version: "0.1.0"
source_files: [.github/workflows/ci.yml, .github/workflows/release-gate.yml, .github/workflows/repo-health.yml, config/ci/ownership.yaml, scripts/ci_select.py, scripts/ci_control_gates.py, scripts/ci_build_selected.py, scripts/suite_worker.py, scripts/verification_disposition.py, scripts/lib/processes.py, scripts/staging_preflight.py, scripts/lib/preflight_dynamodb.py]
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 3
---


# CI Architecture

This page describes how Aether's CI pipeline is structured: what blocks a pull
request, what is advisory, and what runs only for release candidates. It does
not replace `docs/reference/source-of-truth/REPO_CONSISTENCY_OWNERSHIP.md`, which is the
canonical statement of verification authority — this page explains the
mechanics behind it. The design rationale and measurements are in
`docs/engineering/ci-v2/`.

## The single blocking PR authority

`.github/workflows/ci.yml` ("ci") ends in one job named **`ci / verdict`**, the
only required status check for normal pull requests. Draft PRs are the
accumulation phase and run nothing; the first run starts at `ready_for_review`
and then on every new head SHA. The workflow also runs for merge-queue SHAs, for
pushes to `development`, `staging` and `main`, and on demand. A manual
`workflow_dispatch` replay chooses its own diff base, so it publishes under the
name `ci / verdict (manual replay)` and can never satisfy the required context.

The jobs, in order:

1. **`classify`** — checks out full history and runs `scripts/ci_select.py`
   against the base SHA. The selector reads `config/ci/ownership.yaml` and the
   suite registry `config/test_suites.yaml`, selects the PR-lane suites a diff
   affects (a path it cannot classify falls back to every PR-lane suite),
   groups them into workers, and emits the non-suite `checks` to run. A
   selector error fails the job and therefore the verdict.
2. **`suites`** — a matrix of workers. Suites that share a dependency profile
   and runtime class are sharded by the registry's `expected_runtime_seconds`
   (about 450 s per worker) and run through `scripts/suite_worker.py`.
3. **`checks`** — a matrix of non-suite commands declared under `checks:` in
   `config/ci/ownership.yaml`. Each declares the paths that select it (or
   `always: true`) and whether it needs npm, pnpm, a Python profile, or full git
   history. The always-on `control-gates` check runs the router's `fast` lane
   validators (`scripts/ci_control_gates.py`); `build-selected` builds only the
   workspaces and backend image that Build Selection v2 derives from the diff
   (`scripts/ci_build_selected.py`).
4. **`verdict`** (`ci / verdict`) — runs `if: always()` and fails on a failed,
   cancelled or unexpectedly skipped required job. The only valid no-op is an
   empty selection. Only a passing run on a non-draft, non-manual event records
   the small `ci-verdict-evidence` artifact.

The `ci-evidence` and selection details for each run are written to the job
summary. Because cancelled runs fail closed, a superseded run's `verdict` shows
as failed; judge the run for the current head.

### Why selection exists

Aether is a large multi-language monorepo (Python backend, ML models,
TypeScript frontend packages, smart contracts). Running every suite on every
PR would make the blocking gate too slow to be a real gate. `ci_select.py`
maps changed files to suites through the registry's owned paths plus explicit
rules in `ownership.yaml`: critical invariants (tenant isolation, identity, auth
and security) always run, text-only changes run only the docs suite and the
control gates, and anything unclassified is treated as broad rather than
silently dropped. `make verification-disposition BASE=<base> EXECUTE=1` is the
local equivalent used before opening a PR.

Every bounded control-plane command runs in its own process group through
`scripts/lib/processes.py`. When a hard runtime budget expires, the runner
terminates the complete group before publishing a timeout result. This is
important for isolated pytest suites: killing only the wrapper can leave
descendant workers alive and contaminate the next verification run.

## Blocking vs. advisory vs. release-only

| Scope | Workflow / job | Authority |
|---|---|---|
| Non-draft PRs (from `ready_for_review`, then every push), merge-queue SHAs, and pushes to `development`, `staging` and `main` | `ci.yml` → `verdict` (`ci / verdict`) | **Blocking.** The only required status check for normal PRs. |
| Push to `main` or `staging` | `repo-health.yml` → `main-integration` | Blocking for that job, but scoped to `push` — a post-merge integration authority, not a PR gate. It rebuilds the impact graph against the pre-merge SHA and runs `make integration-durable`. |
| Push to `main` only | `repo-health.yml` → `docs-sync` | Write-capable auto-commit of regenerated `docs/_generated/**` when `main` has drifted. Runs with `contents: write`, deliberately never on PR-head code. |
| Nightly (`schedule`) or manual `workflow_dispatch` | `repo-health.yml` → `python-tests`, `backend-tests`, `ml-tests`, `typescript`, `e2e-tenant`, `staging-preflight-dry-run`, aggregated by `validate` | Broad regression evidence (`make ci-check`-class checks plus full test trees). Not a PR blocker — this is what `make ci-check` documents as "broad local, trusted-main, nightly, or release evidence." |
| Manual `workflow_dispatch` only | `release-gate.yml` → `release-gate` | Release-only. Runs `make release-gate` (repo consistency in CI mode + strict production status + ops readiness + founding-tenant control spine) plus a staging preflight dry run. The preflight selects the profile's durable cache check: DynamoDB for staging/production, Redis where Redis is selected. |

Finalization-only supplementary workflows (for example
`production-equivalent-ci.yml`, `infrastructure.yml`, `sdk-release-validation.yml`
and `smart-contract-analysis.yml`) may add evidence at `ready_for_review`, but only
`ci / verdict` determines normal-PR mergeability.

The practical rule, stated in both `AGENTS.md`/`CLAUDE.md` and
`docs/reference/source-of-truth/REPO_CONSISTENCY_OWNERSHIP.md`: `ci / verdict`
is the only hosted normal-PR authority and starts only after finalization; `make
verification-disposition BASE=<base> EXECUTE=1` is its local counterpart; `make
ci-check` is broad evidence you may run and report separately, never a second
blocking gate; `make release-gate` applies only when the PR itself claims
release readiness.

### Draft-to-finalization protocol

Keep architecture and engineering work in a draft PR while the blueprint is
being executed. Integrate all slices, perform clarification and architecture
review, remediate findings, update ownership-required surfaces and docs, and
run focused local checks. Then mark the PR ready for review once. A failed
verdict may be rerun after a material remediation; intermediate pushes while the
PR is a draft do not start another CI cycle.

## `ci.yml` vs. `repo-health.yml`

- **`ci.yml`** owns verification of changes: selection, suites, checks and the
  verdict. It is what branch protection points at.
- **`repo-health.yml`** owns *signals and integration assurance* around it:
  docs drift linting on trusted events, post-merge integration testing on
  `main`/`staging`, the auto-commit of regenerated docs on `main`, and the
  nightly/dispatch-only full regression suite (Python, full backend tree, ML,
  TypeScript, E2E, staging preflight). It has no pull-request trigger.

## Evidence

`ci / verdict` writes a short summary (selected mode, suites, checks and the
reasons) to the run's job summary. Deployment-candidate artifacts are built by
`deploy.yml`, not by pull-request runs; `ci.yml` builds the selected workspaces
and backend image only to prove they build and does not archive them.

## Related documents

- `docs/reference/source-of-truth/REPO_CONSISTENCY_OWNERSHIP.md` — canonical statement
  of verification authority and the owner map for derived surfaces.
- `docs/engineering/ci-v2/architecture.md` — design, sharding and check model.
- `docs/operations/ci/gate-reference.md` — quick-reference table of every Makefile gate.
- `AGENTS.md` / `CLAUDE.md` — agent-facing rules for when each gate must be
  run.
