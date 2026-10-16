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
| `ci` run 12 (sharded, with checks) | #792 | **3.7 min** | broad-safe selection: all 17 PR-lane worker shards plus both checks, all green; slowest jobs 203 s |
| `repo-consistency` (7 successful PR runs, same day) | various | median 7.2 min, range 5.7-11.4 | legacy `verification / disposition` |

- **After sharding, V2 is faster on its worst case.** Run 12 selected every suite
  (fan-out from a `scripts/` change) and finished in 3.7 min against a legacy
  median of 7.2 min. This is one run; the 30-PR sample is still required.
- **Before sharding, V2 was not faster.** One worker ran all 17 backend suites
  serially and set the critical path; every other worker finished in 0.5-4 min.
  Registry runtime estimates are about 4x pessimistic (17 suites estimated at
  1,680 s took 384 s) but rank suites well, so workers are now sharded by
  expected runtime (target 300 s). Expected effect is a critical path of
  roughly 3-4 min; run 12 confirmed 3.7 min.
- **Sample size is far below the bar.** Three completed V2 runs against the
  30 PRs the cutover requires.
- V2 runs on draft pushes, legacy does not. That gave early feedback on #788:
  the `docs` worker caught a stale `doc-manifest.json` on a draft push, before
  the legacy gate would have run.
- Coverage gap found: several PR-time workflows protect invariants that are
  not registry suites (identity gates, Playwright e2e, typecheck, Slither,
  native SDK builds). See `test-retirement-ledger.md`.

## Hosted comparison with the legacy authority

Counted on 2026-10-15/16 from the `ci` workflow history (29 runs).

| Measure | Value |
|---|---|
| `ci` runs | 29 (8 cancelled by newer pushes, 21 completed) |
| Distinct commits with a completed run | 16, across 8 PRs |
| Completed runs that failed | 5 (3 distinct commits, on #781 and #791) |
| Commits where both V2 and the legacy gate completed | 5 (`ad80b3de`, `57813fe4`, `410d9deb`, `e9143a96`, `ea7b1082`) |
| Disagreements between the two on those 5 | **0** (3 passed on both, 2 failed on both) |

The two commits both authorities failed show V2 catching real failures: on
`e9143a96` (#791) the `docs` worker reported source-linked docs drift, and on
`410d9deb` (#781) a `python-backend-medium` suite failed. V2 also produced
verdicts on draft pushes the legacy gate never sees (it only runs at
`ready_for_review`): `ec866c7e` failed and `b1659ebc` passed with no legacy run.

**Not enough for cutover.** Five paired commits against a target of 30 PRs, and
no controlled failing fixtures yet. Pairs also under-test the coverage gap: the
legacy workflows that V2 does not run (identity gates 1 and 6, Playwright,
Slither, native SDK builds) passed on every compared commit, so their absence
from V2 could not have produced a disagreement. See the retirement ledger.

## Remaining parity work

- [ ] Hosted shadow runs on at least 30 PRs across change classes (16 distinct commits so far; 5 paired with the legacy gate)
- [ ] Controlled failing fixtures per category
- [ ] p50/p95 and runner-minute comparison against `verification / disposition`
