---
title: CI V2 Retirement Ledger
slug: engineering/ci-v2-retirement-ledger
section: operations
visibility: I
audience: [ops]
status: beta
since_version: 0.1.0
---

# CI V2 retirement ledger

Per-workflow disposition for everything that runs on pull requests today. A
workflow is deleted or loses its PR trigger only when its unique invariant is
covered by a V2 suite or check **and** hosted `ci / verdict` runs have shown the
replacement catches it. **Cutover executed:** `repo-consistency.yml`,
`aether-test.yml`, `kyber-e2e.yml` and `identity-continuity-gates.yml` are
deleted; the cutover was approved on less hosted evidence than the original
~30-PR bar (see the parity report for what was measured). `functionality-proof`,
`access-kit-container` and `repo-health` lost their PR triggers, `contract-tests`
was removed from `smart-contract-analysis.yml`, and `pr-size` was dropped. The
dispositions below record what was decided and why.

Disposition key: **retire** (after parity), **convert** (move its checks into
`ci.yml` as path-selected `checks`), **move tier** (nightly or release), **retain**.

| Workflow | PR-time jobs | Unique invariant | V2 replacement | Disposition |
|---|---|---|---|---|
| `aether-test.yml` | `test`: typecheck + `npm test` for `apps/aether-web` | Type safety of `aether-web` | suite `frontend-aether` + check `aether-web-typecheck` (shadow) | **Retire** after parity. Node 20 -> 22 |
| `kyber-e2e.yml` | `e2e`: component, integration, Playwright for `apps/kyber-web` | Browser-level operator flows; integration tests are not in the PR lane | suite `frontend-kyber-component` + check `kyber-web-e2e` (shadow) | **Retire** after parity. Node 18 -> 22 |
| `identity-continuity-gates.yml` | Gates 1-7 (contract, routing, merge safety, split, projection, UX, proof pack) | Identity merge safety and explainability proofs | **Mapped gate by gate** (below). Gates 2-5 and the pytest half of Gate 7 are already run by suites `backend-identity` and `backend-computation`; Gates 1 and 6 and the uncovered tests are ported to check `identity-continuity` (shadow) | **Retire** after parity. Gate 7's pnpm half is now check `identity-proof-packages` (shadow); no other workflow ran `@aether/proof-reporting`, so `functionality-proof.yml` could not stand in for it |
| `functionality-proof.yml` | 13 pnpm jobs: lint, typecheck, test, contracts, sdk, smoke, connectors, integration, graph, e2e, build | Unique TypeScript proof assertions (PR #741 work) | suite `functionality-proof-ts` covers the vitest portion only | **Convert**: gating jobs (lint, typecheck, test, contracts, sdk, fixtures, runner, build) are check `functionality-proof` (shadow, same commands and build env). `smoke-web`/`smoke-server` end in `\|\| echo` and cannot fail, so they gate nothing and are dropped. `graph` repeats the `integration` command. `e2e` (Playwright, `@aether/kyber`) moves to post-merge `push` runs; it is outside the PR lane today for forks and is covered for PRs by `kyber-web-e2e`. Retire the PR trigger after parity |
| `production-equivalent-ci.yml` | `classify-impact`, `real-stack-ingestion-smoke` (conditional) | Real Postgres/Redis ingestion behaviour | none (needs service containers) | **Retain**, unchanged: Postgres/Redis service containers do not fit the `checks` matrix. It keeps its own impact-graph gate (`classify-impact`), so it only runs for affected changes, plus the nightly schedule. Supplementary evidence, not a merge authority |
| `repo-health.yml` | `pr-size`, `lint-docs`; other jobs mostly main/schedule | Docs consistency on PRs | suite `docs` covers `lint-docs` | **Retire** `lint-docs` (suite `docs` runs `make docs-check`) and `pr-size` (soft warning at 600 lines, never fails; not ported). Main/schedule jobs stay and become `nightly.yml` |
| `sdk-release-validation.yml` | `sdk-js`, `android` (Gradle), `ios` (macOS) | Native SDK builds and wire compatibility | suites `sdk-*` cover JS tests only | **Retain** (becomes `sdk-release.yml`): Android Gradle and iOS `xcodebuild` need Android SDK/macOS runners and are slow and costly, so they stay path-filtered to `packages/sdk/{android,ios}/**` and release-relevant paths. `sdk-js` duplicates suites `sdk-*` and retires with the cutover |
| `smart-contract-analysis.yml` | `slither`, `contract-tests` | Static analysis of contracts | `contract-tests` runs `npm test`, which duplicates suite `smart-contracts` | `slither` -> check `contracts-slither` (shadow, `--fail-high`); SARIF upload to code scanning stays in the retained `push: main` run. **Retire** `contract-tests` once V2 is required (duplicate of suite `smart-contracts`) |
| `infrastructure.yml` | `plan` (`terraform validate`/plan), credential readiness | Infra validity; no automatic apply | none | **Retain** (becomes `infra.yml`): needs `setup-terraform`, plugin caching and the remote-plan dispatch flow; already path-filtered to `infra/aws/**`, no apply. Supplementary evidence, not a merge authority |
| `access-kit-container.yml` | `build-and-smoke` (`npm pack`, Docker build) | Access Kit packaging | none | check `access-kit-container` (shadow: `npm pack`, buildx, container smoke via `scripts/ci_access_kit_smoke.sh`). Retire the PR trigger after parity; push and dispatch runs stay |
| `frontend-preview.yml` | preview deploys | Preview environments | n/a | **Retain** (`preview.yml`) |
| `repo-consistency.yml` | 10-job DAG, `verification / disposition` | Current merge authority | `ci / verdict`; see the job map below | **Deleted** in the cutover. Its control validators and builds are checks `control-gates` and `build-selected`; `release-gate` moved to `release-gate.yml` (it was dispatch-only) |

Out of scope for this phase: staging, terraform-promote, deploy and publish
workflows. They are privileged operations, not PR verification.

## Identity continuity gates, mapped

Every command in `identity-continuity-gates.yml` was compared with what V2 runs.

| Gate | What it runs | V2 coverage |
|---|---|---|
| 1 Contract | identity contract JSON validity, inventory, `index.json` manifest, `generate_contracts.py --check` | check `identity-continuity` (`scripts/ci_check_identity_continuity.py` plus the twin check) |
| 2 Routing | 6 tests in `services/api/tests/identity/` and 2 in `services/api/tests/providers/` | the identity tests: suite `backend-identity`. The two `providers/` tests were in **no** PR-lane suite; now in check `identity-continuity` |
| 3 Merge safety | 11 tests in `services/api/tests/identity/`; calibration test, `tests/unit/test_identity_continuity_calibration_workflow.py`, and `identity_confidence_calibration_evaluation.py --help` | identity tests: `backend-identity`; the unit test and script smoke: check `identity-continuity` |
| 4 Split | `test_bad_merge_split.py`, `computation/test_identity_restatement.py` | `backend-identity`, `backend-computation` |
| 5 Projection | `test_projection_restatement*.py` | `backend-identity` |
| 6 UX explainability | frontend identity files exist; backend explainability and route markers present | check `identity-continuity` (same script) |
| 7 Proof pack | `make bootstrap`, `generate_contracts.py --check`, pnpm builds and tests of `@aether/proof-contracts`, `-fixtures`, `-runner`, `-reporting`, identity pytest | pytest half: `backend-identity`, `backend-computation`, and the twin check. pnpm half: check `identity-proof-packages` (`@aether/proof-contracts`, `-fixtures`, `-runner`, `-reporting` builds and the 24 `@aether/proof-reporting` tests) |

All seven gates now have a V2 home. A unit test
in the repo, `test_identity_continuity_calibration_workflow.py`, may reference
the workflow file; check it when retiring.

## Known duplicate execution

- `smart-contract-analysis.yml` `contract-tests` and suite `smart-contracts`
  both run the Hardhat tests on contract changes.
- `aether-test.yml` and suite `frontend-aether` both run the `aether-web` tests.
- `kyber-e2e.yml` component tests and suite `frontend-kyber-component`.

## Why checks came before deletion

The first V2 version only ran registry suites. The hosted check above shows
workflows also protect invariants outside the registry, so deleting them first
would remove unique coverage. `config/ci/ownership.yaml` now has a `checks`
section for non-suite commands; each retirement moves one workflow's unique
commands there, then waits for hosted parity.

## `repo-consistency.yml`, job by job

Mapping the legacy DAG showed V2 ran **none** of its control validators, builds
or release gate. Closed by this change unless noted:

| Legacy job | What it did | V2 home |
|---|---|---|
| `classify-change` | `check_router`, execution plan, impact graph `--fail-on-unresolved` | `ci_select.py` for selection; `impact_graph` and the plan run inside the `control-gates` and `build-selected` checks |
| `universal-fast` | the router `fast` lane: 17 validators (toolchain, metadata, delivery, verification policy, impact graph, telemetry, workflow authority, CI execution contracts, branding, debt ledger, profile config, capability overlays, service classification, reachability, settings flags) | check `control-gates` (`scripts/ci_control_gates.py`), always on, adds `contracts` from the `pr` lane |
| `plan-verification`, `suite-matrix` | suite workers | `classify` + `suites` matrix |
| `plan-build`, `build-node` | Build Selection v2, dependency-first workspace builds | check `build-selected` (`scripts/ci_build_selected.py`); the archive tarball is not produced |
| `build-backend-image` | `docker build services/api` | check `build-selected` (same script); the image is not saved |
| `candidate-verification` | verified the immutable archive of the two builds above | **Retired with the archives.** `deploy.yml` builds the release candidate; no workflow downloads the PR run's archives |
| `publish-evidence` | `verification / disposition` | `ci / verdict` |
| `release-gate` | `make release-gate` and staging preflight dry-run on push to `development`, `staging`, `main` | **Ported unchanged** to `release-gate.yml`; it was `workflow_dispatch`-only, not push-time |

## Accepted overlap after the cutover

- Slither runs twice on smart-contract PRs: as check `contracts-slither` under
  `ci / verdict`, and in `smart-contract-analysis.yml`, which stays for the SARIF
  upload to code scanning. Remove the workflow's `pull_request` trigger if the
  duplicate cost outweighs the PR annotations.
- `sdk-release-validation.yml` keeps its `sdk-js` job because the release-check
  catalog names it, even though the `sdk-*` suites cover the same tests.
