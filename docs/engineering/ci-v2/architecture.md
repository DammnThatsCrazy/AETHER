---
title: CI V2 Architecture
slug: engineering/ci-v2-architecture
section: operations
visibility: I
audience: [ops]
status: beta
since_version: 0.1.0
---

# CI V2 Architecture

CI V2 replaces the multi-job evidence DAG behind `verification / disposition`
with one workflow, `.github/workflows/ci.yml`, and one stable check,
`ci / verdict`. It is in **shadow phase**: it runs on every new PR head SHA and
merge-queue SHA, but `verification / disposition` remains the merge authority
until the parity report clears the cutover.

## How a PR is classified

1. `classify` runs `scripts/ci_select.py` on the merge-base diff
   (`base...head`, renames contribute old and new paths).
2. Rules live in `config/ci/ownership.yaml`; suite ids, paths and runner
   commands come from `config/test_suites.yaml`, so there is no second command
   list.
3. The result is `docs-only`, `targeted`, `broad-safe` or `empty`:
   - text-only paths select the `docs` suite only;
   - registry `paths` and `extra` rules select the owning suites;
   - `critical` suites (identity, compliance, security) are added to every
     non-text change and cannot be opted out of;
   - `fanout` paths (lockfiles, root config, `scripts/`, workflows, shared
     packages) and any **unclassified** path select every PR-lane suite;
   - a selector error fails the `classify` job, which fails the verdict.
4. `suites` runs workers grouped by (dependency profile, runtime class) and
   sharded by the registry's `expected_runtime_seconds` (about 300 s per worker)
   through `scripts/suite_worker.py`. No artifacts are uploaded or downloaded.
   `checks` runs path-selected non-suite commands declared under `checks:` in
   `config/ci/ownership.yaml` (type checks, browser e2e, the identity-continuity
   static gates, the pnpm proof packages, functionality-proof, Slither, the Access
   Kit container, the always-on control gates, and the selected builds); a check may
   need npm, pnpm, Python extras, or a combination.
   A broad-safe selection runs all of them.
5. `verdict` runs with `if: always()` and fails on a failed, cancelled or
   unexpectedly skipped required job (suites or checks). The only valid no-op
   is an empty diff.

## Running it locally

```bash
python scripts/ci_select.py --base origin/Development      # what would run
python -m pytest tests/unit/test_ci_select.py              # selector table tests
```

## Parity replay

Dispatch `ci` with `base` set to a historical base ref to replay a change set,
then compare the selected suites with `verification / disposition` for the same
SHA. Record results in `parity-report.md`. Old gates are deleted only after the
replay shows no unexplained selection gap.

## Known gaps in this phase

- The `docs` suite maps to the full Python profile, so docs-only PRs install
  more than they need; a lighter docs check is required to meet the 45 s goal.
- Suite-level registry paths such as `tests/unit` fan out to several
  `root-unit-*` suites; narrowing that needs per-file ownership.
- `ci / verdict` is not a required status yet.
