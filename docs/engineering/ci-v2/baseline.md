# CI V2 baseline

Point-in-time baseline for the CI V2 program (`AETHER_LEAN_CI_V2_BUILD_SPEC`),
measured on `origin/Development` at `063ca632` on 2026-10-15. Regenerate the
inventory with `python scripts/ci_baseline.py`.

## Validated against the spec

| Spec claim | Measured |
|---|---|
| 30 workflows | 30 files, 16,517 lines (about 12k of those are staging/terraform operations, not PR CI) |
| `test_suites.yaml` about 1,700 lines, 46 suites, 39 PR-lane | 1,698 lines, 46 suites, 39 `pr`, 3 `regression`, 2 `integration`, 1 `fast`, 1 `release` |
| About 1,434 Python and 443 TypeScript tests | 1,490 `.py`, 278 `.ts` and 169 `.tsx` test files |
| `production-olympus` exists | Not present on origin |
| `Development` 43 ahead of `main`, `staging` 33 ahead | `Development` is 131 ahead / 4 behind `main`, 100 ahead / 2 behind `staging`; `staging` is 33 ahead / 4 behind `main` |

## PR gating facts

- All 13 PR-triggered workflows use `types: [ready_for_review]`; none run on `synchronize`.
- Seven workflows are path-filtered on `pull_request` (`access-kit-container`, `aether-test`, `infrastructure`, `kyber-e2e`, `sdk-release-validation`, `smart-contract-analysis`), so none can be a required check.
- 48 `upload-artifact` and 25 `download-artifact` steps. `repo-consistency.yml` alone chains 9 uploads into 7 downloads.

## Authority run time (`repo-consistency.yml`, latest 30 runs)

p50 about 5.7 min, p95 about 8.4 min, max about 11.4 min (wall clock from
`run_started_at` to `updated_at`). 2 of 11 pull-request runs and 5 of 18 push
runs failed. Of 1,833 total runs, only the latest 30 were sampled; the
artifact-quota failure rate over a longer window is still to be measured.

## Artifact handling change in this step

Diagnostic uploads in workflows that never download artifacts
(`aether-test`, `kyber-e2e`, `identity-continuity-gates`,
`production-equivalent-ci`, `repo-health`, `sdk-release-validation`,
`smart-contract-analysis`, `infrastructure`) now set `continue-on-error: true`
and `retention-days: 7` where none was set, so a quota failure cannot turn a
passing test run red. `repo-consistency.yml` is untouched because its verdict
consumes artifacts; that dependency goes away when `ci / verdict` replaces it.

## Workflow inventory

See `workflow-inventory.csv` (one row per workflow: lines, jobs, events, PR
types, path filter, upload and download counts).
