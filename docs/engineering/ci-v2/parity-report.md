---
title: CI V2 Parity Report
slug: engineering/ci-v2-parity-report
section: operations
visibility: I
audience: [ops]
status: beta
since_version: 0.1.0
---

# CI V2 parity report (selection phase and post-cutover measurement)

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

## Post-cutover measurement (2026-10-16)

Measured from the 78 `ci` runs recorded after the cutover and before it landed
(wall clock from `run_started_at` to `updated_at`; queueing included). The legacy
figures are the 30-run sample in `baseline.md`.

### Structure (exact, from `scripts/ci_baseline.py`)

| Measure | Baseline (`063ca632`) | After cutover |
|---|---|---|
| Workflow files | 30 | 28 (two added: `ci.yml`, `release-gate.yml`; four deleted; others kept) |
| Workflow lines | 16,517 | 15,538 |
| Workflows triggered on `pull_request` | 13 | 6 (`ci`, `frontend-preview`, `infrastructure`, `production-equivalent-ci`, `sdk-release-validation`, `smart-contract-analysis`) |
| Of those, path-filtered (cannot be required) | 7 | 3 |
| Workflows that run on `synchronize` | 0 | 1 (`ci`, and it skips drafts) |
| Required merge authority | `verification / disposition` | `ci / verdict` |
| `upload-artifact` / `download-artifact` steps | 48 / 25 | 36 / 18 |
| PR jobs that chain artifacts to reach the verdict | 9 uploads feed 7 downloads | none (one tiny diagnostic upload) |

The workflow and line counts moved only modestly: about 12,000 lines are staging,
Terraform and delivery operations that this program does not touch. The change
that matters is the number of PR-triggered workflows and the single authority.

### Time

| Sample | n | p50 | p95 | Max |
|---|---|---|---|---|
| Legacy `verification / disposition` (latest 30, baseline) | 30 | about 5.7 min | about 8.4 min | about 11.4 min |
| `ci` pull-request and push runs, completed (pass or fail) | 47 | 6.0 min | 12.6 min | 13.7 min |
| `ci`, successful only | 34 | 5.8 min | 12.0 min | |
| `ci` pushes to `development` since the cutover | 4 | 6.1 min | 10.8 min | 11.7 min |

Excluded: 26 runs cancelled by a newer push (the concurrency group does this by
design) and 4 draft runs that finish in under 10 s because drafts run nothing.

**Reading this honestly: wall clock did not improve.** The V2 median is level with
the legacy median and the tail is worse. What the data supports:

- **The long pole is one suite shard plus queueing.** In a full-selection run
  (`#803` merge, 343 s wall, 26 jobs) the slowest job was
  `suites (python-backend-medium-2)` at 277 s, and it started 60 s after the
  run began because 26 jobs compete for runners. Of 26 jobs, 12 took 98 s or more.
- **The sample is the hard case.** Most runs here are PRs for the CI V2 work
  itself, which touch `scripts/**` and workflows, so the selector falls back to
  every PR-lane suite plus all checks. Narrow PRs in the same sample finished in
  130 s, 142 s, 207 s and 209 s.
- **Contention inflated the tail.** During the shadow phase the legacy pipeline
  ran alongside V2 on every PR, which plausibly doubled runner demand (not measured). The three
  `development` pushes after the legacy workflows were deleted took 347, 362 and
  374 s, with 699 s for the one push before that. That is four points; treat the
  improvement as unproven until more post-cutover runs accumulate.
- **Failures are not comparable.** 13 of 47 completed runs failed (28%), against
  2 of 11 legacy pull-request runs. Several were real findings (wallet proof,
  access-kit, docs drift) and several were bugs in V2 itself that were fixed
  during the program (`shared` build order, shallow checkout, stale generated
  index). The rate should be re-measured on a steady state.

### What this does and does not show

Shown: one authority, fewer PR workflows, no artifact chain, narrow PRs in 2 to
3.5 minutes, and equal median time on the broad worst case while also running
the control gates, builds, Playwright, identity and Slither checks that the old
authority did not.

Not shown: lower p95 time, lower runner-minutes, or a lower failure rate.
Runner-minutes were not measured; the Actions API exposes per-job durations, so a
follow-up can sum them per run for both pipelines.

## Remaining parity work

- [ ] Hosted shadow runs on at least 30 PRs across change classes (16 distinct commits so far; 5 paired with the legacy gate)
- [ ] Controlled failing fixtures per category
- [x] p50/p95 against `verification / disposition` (above; no improvement shown, see the analysis)
- [ ] Runner-minute comparison (sum job durations per run for both pipelines)
