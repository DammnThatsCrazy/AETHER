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
| `identity-continuity-gates.yml` | Gates 1-7 (contract, routing, merge safety, split, projection, UX, proof pack) | Identity merge safety and explainability proofs; not registry suites | none yet (`backend-identity`, `root-unit-security` cover only part) | **Convert** to path-selected checks; do not delete until each gate is mapped |
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
