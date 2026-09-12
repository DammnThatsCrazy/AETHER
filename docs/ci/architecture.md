---
title: CI Architecture
slug: ci/architecture
section: reference
visibility: I
audience: [dev-senior, ops]
status: stable
since_version: "0.1.0"
source_files: [.github/workflows/repo-consistency.yml, .github/workflows/repo-health.yml, scripts/verification_disposition.py, scripts/impact_graph.py, config/impact_graph.json]
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 3
---

# CI Architecture

This page describes how Aether's CI pipeline is structured: what blocks a pull
request, what is advisory, and what runs only for release candidates. It does
not replace `docs/source-of-truth/REPO_CONSISTENCY_OWNERSHIP.md`, which is the
canonical statement of verification authority — this page explains the
mechanics behind it.

## The single blocking PR authority

Every pull request and every push to `main` triggers
`.github/workflows/repo-consistency.yml` ("Repo Consistency"). Its terminal
job, `publish-evidence`, is named **`verification / disposition`** — this is
the one required status check for normal PRs. The workflow has four jobs that
run in sequence:

1. **`classify-change`** ("impact authority") — checks out full history,
   bootstraps the Python toolchain, and runs `scripts/check_router.py` to
   select the minimum verification lane for the change, then
   `scripts/impact_graph.py --fail-on-unresolved` to build the complete
   impact graph and telemetry evidence. The impact graph is keyed off
   `config/impact_graph.json` (components, contracts, deployables) and
   resolves which parts of the repo a changed file set actually affects.
   Both the lane selection and the impact graph are uploaded as artifacts
   for later jobs to consume — nothing downstream recomputes them.
2. **`build-artifact`** ("build authority") — downloads the impact graph,
   builds only the npm workspaces and (conditionally) the backend Docker
   image that the impact graph selected, and packages the result into an
   immutable release-candidate bundle via `scripts/artifact_builder.py`.
   This is a real build authority: nothing after this job rebuilds
   anything — the next job verifies the exact bytes it produced.
3. **`selected-verification`** ("affected verification execution") —
   re-downloads the built candidate, verifies it against the expected
   commit (`artifact_builder.py --verify`), runs the frontend data-truth and
   branding guardrails, and then runs
   `scripts/verification_disposition.py --base <base> --execute`. This
   script is the same one exposed as `make verification-disposition
   BASE=<base> EXECUTE=1` — CI and a local run execute the identical
   authority, so a green local run is a reliable predictor of CI.
4. **`publish-evidence`** ("verification / disposition") — the required
   check. It downloads every evidence artifact from the prior three jobs
   and fails closed if any of `classify-change`, `build-artifact`, or
   `selected-verification` did not succeed. This is the only job branch
   protection needs to require.

A fifth job, **`release-gate`**, exists in the same workflow file but only
runs on `workflow_dispatch` (`if: github.event_name == 'workflow_dispatch'`).
It is the pre-release ratchet — `make release-gate` plus a staging preflight
dry-run — and is never evaluated on a normal PR or push.

### Why impact-graph routing exists

Aether is a large multi-language monorepo (Python backend, ML models,
TypeScript frontend packages, smart contracts). Running every test suite on
every PR would make the blocking gate too slow to be a real gate. The impact
graph inverts this: `scripts/impact_graph.py` maps changed files to the
components, contracts, and deployables in `config/impact_graph.json`, and
`scripts/check_router.py` uses that mapping to pick the minimum verification
lane (`fast`, `pr`, `integration`, `regression`, or `release` — see
`make test-fast`, `make test-pr`, `make test-integration`,
`make test-regression`, `make test-release`) that actually covers the change.
`scripts/verification_disposition.py` is the single entry point that wraps
this routing decision and executes it, which is why it — not any individual
`make test-*` lane — is the canonical authority invoked both by CI and by
`make verification-disposition`.

The `--fail-on-unresolved` flag on `impact_graph.py` is deliberate: a changed
file the graph cannot map to a known component fails the job rather than
silently being routed to the loosest lane. This keeps the routing fail-closed
as the repo grows.

## Blocking vs. advisory vs. release-only

| Scope | Workflow / job | Authority |
|---|---|---|
| Every PR, every push to `main` | `repo-consistency.yml` → `publish-evidence` (`verification / disposition`) | **Blocking.** The only required status check for normal PRs. |
| Every PR, every push to `main` | `repo-health.yml` → `pr-size` | Advisory (`continue-on-error` on PRs). Warns above 600 meaningful changed lines; never blocks. |
| Every PR, every push to `main` | `repo-health.yml` → `lint-docs` | Advisory on PRs (`continue-on-error`), but the same `make docs-check` is enforced as part of `verification-disposition`'s routing where docs are affected. On non-PR trusted events it still just reports. |
| Push to `main` only | `repo-health.yml` → `main-integration` | Blocking for that job, but scoped to `push` on `main` — it is a post-merge integration authority, not a PR gate. It rebuilds the impact graph against the pre-merge SHA and runs `make integration-durable`. |
| Push to `main` only | `repo-health.yml` → `docs-sync` | Write-capable auto-commit of regenerated `docs/_generated/**` when `main` has drifted. Runs with `contents: write`, deliberately never on PR-head code. |
| Nightly (`schedule`) or manual `workflow_dispatch` | `repo-health.yml` → `python-tests`, `backend-tests`, `ml-tests`, `typescript`, `e2e-tenant`, `staging-preflight-dry-run`, aggregated by `validate` | Broad regression evidence (`make ci-check`-class checks plus full test trees). Not a PR blocker — this is what `make ci-check` documents as "broad local, trusted-main, nightly, or release evidence." |
| Manual `workflow_dispatch` only | `repo-consistency.yml` → `release-gate` | Release-only. Runs `make release-gate` (repo consistency in CI mode + strict production status + ops readiness + founding-tenant control spine) plus a staging preflight dry run. |

The practical rule, stated in both `AGENTS.md`/`CLAUDE.md` and
`docs/source-of-truth/REPO_CONSISTENCY_OWNERSHIP.md`: `make
verification-disposition BASE=<base> EXECUTE=1` is the only normal-PR
authority; `make ci-check` is broad evidence you may run and report
separately, never a second blocking gate; `make release-gate` applies only
when the PR itself claims release readiness.

## `repo-consistency.yml` vs. `repo-health.yml`

These two workflows have distinct, non-overlapping jobs:

- **`repo-consistency.yml`** owns the *build-and-verify* pipeline: it is the
  only workflow that builds a release-candidate artifact, verifies it
  byte-for-byte, and runs the impact-graph-routed verification disposition.
  It is what branch protection points at.
- **`repo-health.yml`** owns *signals and integration assurance* that sit
  around that pipeline: PR-size hygiene, docs drift linting, post-merge
  integration testing on `main`, the auto-commit of regenerated docs on
  `main`, and the nightly/dispatch-only full regression suite (Python, full
  backend tree, ML, TypeScript, E2E, staging preflight). None of its
  PR-scoped jobs are required checks; its `main`-scoped jobs run after merge,
  not before.

Both workflows independently invoke `scripts/impact_graph.py` when they need
change classification (`classify-change` in `repo-consistency.yml`,
`main-integration` in `repo-health.yml`), each against the base SHA
appropriate to its trigger (PR base vs. `github.event.before` on `main`).
They do not share job outputs across workflow boundaries — each recomputes
the impact graph for its own SHA range.

## Evidence artifacts

Every job in `repo-consistency.yml` uploads its evidence under
`release-evidence/` as a workflow artifact (`verification-selection-evidence`,
`impact-telemetry-evidence`, `pr-build-evidence`,
`selected-verification-evidence`, `repo-consistency-evidence`). This gives an
auditable trail from "which lane was selected" through "what was built"
through "what passed" for any given commit, independent of the GitHub Actions
UI. `scripts/artifact_builder.py --verify` is what proves the artifact tested
in `selected-verification` is byte-identical to the one built in
`build-artifact`, closing the gap between "we built something" and "we tested
that exact thing."

## Related documents

- `docs/source-of-truth/REPO_CONSISTENCY_OWNERSHIP.md` — canonical statement
  of verification authority and the owner map for derived surfaces.
- `docs/ci/gate-reference.md` — quick-reference table of every Makefile gate.
- `AGENTS.md` / `CLAUDE.md` — agent-facing rules for when each gate must be
  run.
