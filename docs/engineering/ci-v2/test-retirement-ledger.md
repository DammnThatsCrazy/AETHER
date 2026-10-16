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
replacement catches it. Nothing here is retired yet.

Disposition key: **retire** (after parity), **convert** (move its checks into
`ci.yml` as path-selected `checks`), **move tier** (nightly or release), **retain**.

| Workflow | PR-time jobs | Unique invariant | V2 replacement | Disposition |
|---|---|---|---|---|
| `aether-test.yml` | `test`: typecheck + `npm test` for `apps/aether-web` | Type safety of `aether-web` | suite `frontend-aether` + check `aether-web-typecheck` (shadow) | **Retire** after parity. Node 20 -> 22 |
| `kyber-e2e.yml` | `e2e`: component, integration, Playwright for `apps/kyber-web` | Browser-level operator flows; integration tests are not in the PR lane | suite `frontend-kyber-component` + check `kyber-web-e2e` (shadow) | **Retire** after parity. Node 18 -> 22 |
| `identity-continuity-gates.yml` | Gates 1-7 (contract, routing, merge safety, split, projection, UX, proof pack) | Identity merge safety and explainability proofs | **Mapped gate by gate** (below). Gates 2-5 and the pytest half of Gate 7 are already run by suites `backend-identity` and `backend-computation`; Gates 1 and 6 and the uncovered tests are ported to check `identity-continuity` (shadow) | **Retire** after parity, once the pnpm half of Gate 7 is ported or accepted as covered |
| `functionality-proof.yml` | 13 pnpm jobs: lint, typecheck, test, contracts, sdk, smoke, connectors, integration, graph, e2e, build | Unique TypeScript proof assertions (PR #741 work) | suite `functionality-proof-ts` covers the vitest portion only | **Retain**; map each job (lint/typecheck/build/smoke/e2e) before any retirement |
| `production-equivalent-ci.yml` | `classify-impact`, `real-stack-ingestion-smoke` (conditional) | Real Postgres/Redis ingestion behaviour | none (needs service containers) | **Retain** as the targeted-integration tier; schedule stays |
| `repo-health.yml` | `pr-size`, `lint-docs`; other jobs mostly main/schedule | Docs consistency on PRs | suite `docs` covers `lint-docs` | **Move tier**: PR jobs retire, main/schedule jobs become `nightly.yml` |
| `sdk-release-validation.yml` | `sdk-js`, `android` (Gradle), `ios` (macOS) | Native SDK builds and wire compatibility | suites `sdk-*` cover JS tests only | **Retain** (becomes `sdk-release.yml`); native jobs stay path-filtered |
| `smart-contract-analysis.yml` | `slither`, `contract-tests` | Static analysis of contracts | `contract-tests` runs `npm test`, which duplicates suite `smart-contracts` | **Retain** `slither`; **retire** `contract-tests` once V2 is required (known duplicate execution) |
| `infrastructure.yml` | `plan` (`terraform validate`/plan), credential readiness | Infra validity; no automatic apply | none | **Retain** (becomes `infra.yml`) |
| `access-kit-container.yml` | `build-and-smoke` (`npm pack`, Docker build) | Access Kit packaging | none | **Retain** (folds into `package-release.yml`) |
| `frontend-preview.yml` | preview deploys | Preview environments | n/a | **Retain** (`preview.yml`) |
| `repo-consistency.yml` | 10-job DAG, `verification / disposition` | Current merge authority | `ci / verdict` | **Retire last**, after the ruleset requires `ci / verdict` |

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
| 7 Proof pack | `make bootstrap`, `generate_contracts.py --check`, pnpm builds and tests of `@aether/proof-contracts`, `-fixtures`, `-runner`, `-reporting`, identity pytest | pytest half: `backend-identity`, `backend-computation`, and the twin check. **The pnpm proof-package builds and the `@aether/proof-reporting` test are not ported.** |

Before this workflow can be deleted, the pnpm half of Gate 7 needs a V2 home
(or an explicit decision that `functionality-proof.yml` covers it). A unit test
in the repo, `test_identity_continuity_calibration_workflow.py`, may reference
the workflow file; check it when retiring.

## Known duplicate execution

- `smart-contract-analysis.yml` `contract-tests` and suite `smart-contracts`
  both run the Hardhat tests on contract changes.
- `aether-test.yml` and suite `frontend-aether` both run the `aether-web` tests.
- `kyber-e2e.yml` component tests and suite `frontend-kyber-component`.

## Why nothing is deleted yet

The first V2 version only ran registry suites. The hosted check above shows
workflows also protect invariants outside the registry, so deleting them first
would remove unique coverage. `config/ci/ownership.yaml` now has a `checks`
section for non-suite commands; each retirement moves one workflow's unique
commands there, then waits for hosted parity.
