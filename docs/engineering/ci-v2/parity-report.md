---
title: CI V2 Parity Report
slug: engineering/ci-v2-parity-report
section: operations
visibility: I
audience: [ops]
status: beta
since_version: 0.1.0
---

# CI V2 parity report (selection phase)

Local replay with `python scripts/ci_parity.py --rev <rev> --count 60`. For each
of the last 60 non-merge commits on `Development` (before the CI V2 commits), it
compares the PR-lane suites chosen by the legacy `check_router.py` with the
suites chosen by `scripts/ci_select.py`.

## Result

| Measure | Value |
|---|---|
| Commits replayed | 60 (0 legacy-router errors) |
| Selection gaps (legacy suite not selected by V2) | **0** after the rule fix below |
| Mode mix | 37 targeted, 13 broad-safe, 10 docs-only |
| Mean PR-lane suites per commit | legacy 15.8, V2 21.4 |

## What the replay found

1. First draft rules missed suites on two commits that touched
   `services/api/shared` and `services/api/value/derivatives`
   (`agent-layer`, `contracts`, `journey-service`, and others). `services/api`
   is one coupled runtime, so any change under it now selects the whole backend
   group.
2. A second replay then showed `root-unit-frontend-sdk` missing for backend
   changes; it is now part of that group.

## What this does and does not show

- V2 is **more conservative, not smaller**, on this history: most recent
  commits touch `scripts/**` or workflows, which fan out to every PR-lane
  suite. The speed case rests on lower orchestration overhead (no artifact
  chain, one job graph), not on selecting fewer suites for CI-tooling changes.
  `scripts/**` fan-out can be narrowed once hosted data shows which scripts are
  safe.
- This is **selection parity only**. It does not prove V2 catches the same
  failures. Still required before cutover: hosted `ci / verdict` runs on real
  PRs, controlled failing fixtures per change class (auth, contract,
  tenant filter, migration), and p50/p95 time-to-verdict measurements.
- Docs-only PRs still run the `docs` suite on the full Python profile.

## Hosted evidence (first runs)

Measured from GitHub Actions runs on 2026-10-15 (wall clock, `run_started_at`
to `updated_at`).

| Run | PR | Wall clock | Notes |
|---|---|---|---|
| `ci` run 3 | #788 | 11.0 min | 34 legacy jobs queued at the same moment; contended runners |
| `ci` run 4 | #790 | 5.8 min | |
| `ci` run 5 | #790 | 7.7 min | critical path: `python-backend-medium` selected suites took 6m24s |
| `repo-consistency` (7 successful PR runs, same day) | various | median 7.2 min, range 5.7-11.4 | legacy `verification / disposition` |

- **V2 was not faster in this sample.** One worker ran all 17 backend suites
  serially and set the critical path; every other worker finished in 0.5-4 min.
  Registry runtime estimates are about 4x pessimistic (17 suites estimated at
  1,680 s took 384 s) but rank suites well, so workers are now sharded by
  expected runtime (target 300 s). Expected effect is a critical path of
  roughly 3-4 min; this must be confirmed on hosted runs.
- **Sample size is far below the bar.** Three completed V2 runs against the
  30 PRs the cutover requires.
- V2 runs on draft pushes, legacy does not. That gave early feedback on #788:
  the `docs` worker caught a stale `doc-manifest.json` on a draft push, before
  the legacy gate would have run.
- Coverage gap found: several PR-time workflows protect invariants that are
  not registry suites (identity gates, Playwright e2e, typecheck, Slither,
  native SDK builds). See `test-retirement-ledger.md`.

## Remaining parity work

- [ ] Hosted shadow runs on at least 30 PRs across change classes (3 completed so far)
- [ ] Controlled failing fixtures per category
- [ ] p50/p95 and runner-minute comparison against `verification / disposition`
