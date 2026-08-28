---
title: Staging Wake / Sleep
slug: operations/staging-wake-sleep
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: stable
since_version: "8.12.0"
source_files:
  - .github/workflows/staging-lifecycle.yml
  - .github/workflows/staging-ttl-guard.yml
  - .github/workflows/terraform-promote.yml
  - config/runtime_deployment.yaml
  - config/deployment_profiles.yaml
  - AWS Deployment/aether-aws/terraform/profiles.tf
  - AWS Deployment/aether-aws/terraform/variables.tf
  - AWS Deployment/aether-aws/terraform/profiles/staging.tfvars
canonical_owner: platform@aether
estimated_read_minutes: 18
toc_depth: 3
---

# Staging Wake / Sleep

Aether's staging environment is a **release rehearsal**, not a permanently
running pre-production copy. It wakes on demand, proves a release, and returns
to zero. This page is the operating procedure for that cycle and for what to do
when it goes wrong.

The cost model that makes this worth doing: staging's budget is USD 25 target /
USD 50 hard ceiling, computed against
`maximum_scheduled_awake_hours_per_month: 40` rather than 730. Hourly-accruing
resources are prorated by awake hours; per-month charges (KMS keys, Secrets
Manager secrets, alarms) accrue in full regardless of sleep, because AWS does
not prorate them either.

## The mechanism

`staging_state` is a **root Terraform variable**, not a tfvars constant, with
a validated domain of `awake | asleep` and a default of `awake`. It resolves
against `config/runtime_deployment.yaml` →
`profiles.staging.staging_state.states.<state>.desired_count_multiplier`
(`awake: 1`, `asleep: 0`).

`profiles.tf` applies that multiplier to **four** things per service:

- `desired_count`
- the autoscaling **floor** (`min_capacity`)
- the autoscaling **ceiling** (`max_capacity`)
- the capacity provider's guaranteed `base_count`

The ceiling and `base_count` are not decoration. The `api` service's
`desired_count` is `ignore_changes`d in `modules/ecs` so an apply cannot fight
Application Auto Scaling mid-scale-out; on an already-applied workspace the
scaling target is the only lever that still reaches a running service. So
`asleep` has to close the envelope to `0..0` — a ceiling above zero would let a
stray backlog metric wake the environment behind the operator's back. And a
guaranteed on-demand floor of 1 contradicts a desired count of 0;
`scripts/release/check_delivery_topology.py` rejects `base_count > desired_count`.

The consequence that matters operationally: **an asleep environment owns exactly
the same services, the same roles and the same queues as an awake one.** Waking
is flipping one input, not planning a differently-shaped topology. Staging runs
the same consolidated 2-service shape as `production-lean` — `api` plus
`lean-worker` hosting all eight worker roles — so the packing itself is
rehearsed before production sees it, sized one step down at 1 vCPU / 4 GiB for
the worker.

## Commands

Everything runs through `.github/workflows/staging-lifecycle.yml`
(`workflow_dispatch` only — there is no schedule on it). The `action` input
takes exactly six values.

| `action` | Jobs run | Use |
|---|---|---|
| `plan-wake` | `wake-plan` | Produce a reviewed awake plan and stop. |
| `validate` | `wake-validate` | Re-verify an existing reviewed plan (needs `plan_run_id`). |
| `apply-wake` | `wake-validate`, `wake-apply` | Wake using an already-reviewed plan (needs `plan_run_id` + `plan_checksum`). |
| `plan-sleep` | `sleep` (plan + verify only) | Produce and verify an asleep plan without applying. |
| `apply-sleep` | `sleep` (plan + verify + apply) | Return staging to zero. |
| `full-rehearsal` | all of the above plus `rehearse` | The complete cycle. |

The ML digest is profile-dependent. Staging, demo, preview, and
`production-lean` run inline ML (`remote_ml: false`) and must leave this input
empty. Only profiles with a dedicated remote ML service require the immutable
serving-image digest.

```bash
# Wake for a manual investigation (remote-ML profiles only; omit the ML input
# for staging and other inline-ML profiles)
gh workflow run staging-lifecycle.yml \
  -f action=plan-wake \
  -f ml_image_digest=sha256:<64hex> \
  -f backend_image_digest=sha256:<64hex> \
  -f max_awake_hours=4

gh workflow run staging-lifecycle.yml \
  -f action=apply-wake \
  -f plan_run_id=<run id from plan-wake> \
  -f plan_checksum=<reviewed.tfplan sha256>

# Return to zero — ALWAYS run this, even after a failed wake
gh workflow run staging-lifecycle.yml \
  -f action=apply-sleep \
  -f ml_image_digest=sha256:<64hex>

# The whole rehearsal in one dispatch
gh workflow run staging-lifecycle.yml \
  -f action=full-rehearsal \
  -f ml_image_digest=sha256:<64hex> \
  -f release_run_id=<successful "Immutable delivery" run id> \
  -f release_manifest_checksum=<approved release.json sha256> \
  -f max_awake_hours=4 \
  -f promote_timeout_minutes=180
```

### Inputs

| Input | Default | Constraint |
|---|---|---|
| `action` | `validate` | one of the six above |
| `ml_image_digest` | — | required for wake or sleep **plans** only when the selected profile has `remote_ml: true`; optional for inline-ML profiles such as staging |
| `backend_image_digest` | — | ignored when `release_run_id` is supplied |
| `release_run_id` | — | required for `full-rehearsal`; must be a successful `.github/workflows/deploy.yml` run |
| `release_manifest_checksum` | — | required for `full-rehearsal` |
| `plan_run_id` | — | required for a standalone `validate` / `apply-wake` |
| `plan_checksum` | — | required for a standalone `apply-wake` |
| `max_awake_hours` | `4` | integer 1–8 (`MAX_AWAKE_HOURS_CAP`) |
| `promote_timeout_minutes` | `180` | digits; bounds the wait for a dispatched promotion **including its environment approval** |

`select-profile` validates every one of these before any job that costs money
runs, and additionally re-derives the profile from canonical configuration:
`profiles/staging.tfvars` must exist, `config/deployment_profiles.yaml` →
`profiles.staging` must declare `class: staging`, `wake_sleep: true` and a
`budget.hard_monthly_spend`, and `config/runtime_deployment.yaml` must declare
both `awake` and `asleep` states.

### Environment and identity

| Constant | Value |
|---|---|
| ECS cluster | `AETHER-staging` |
| Region | `us-east-1` |
| Awake-lease SSM parameter | `/aether/staging/lifecycle/awake-until` |
| Terraform state key | `profiles/staging/terraform.tfstate` |
| AWS role | `secrets.AWS_STAGING_LIFECYCLE_ROLE_ARN` |
| Promotion workflow | `.github/workflows/terraform-promote.yml` |

## Wake

`staging-lifecycle.yml` never runs Terraform itself. It dispatches
`terraform-promote.yml` and waits, so waking staging goes through the **same**
reviewed-plan machinery as a production apply.

1. **Resolve the backend digest.** If `release_run_id` is supplied, the run is
   verified to be a successful `deploy.yml` run, `release.json` is validated by
   `scripts/release/release_manifest.py` against its commit SHA and the
   approved checksum, and the digest is read from
   `artifacts.backend_image.digest`. A separately supplied
   `backend_image_digest` must match it exactly.
2. **Dispatch the reviewed plan** with `action=plan`, `profile=staging`,
   `staging_state=awake` and both digests. Run discovery polls for 300 s;
   **more than one candidate run is a hard failure** rather than a guess.
   Completion is awaited up to `promote_timeout_minutes`.
3. **Verify the plan artifact.** All 14 `reviewed.*` files must be present and
   non-empty; `reviewed.profile == staging`;
   `reviewed.state-key == profiles/staging/terraform.tfstate`;
   `sha256sum --check` on `reviewed.tfplan.sha256`; `reviewed.commit` a
   40-character SHA.
4. **`wake-validate` re-verifies independently**, at the reviewed commit, from a
   fresh download — the checksum must match the approved one, the Terraform
   version must be concrete, and the 24-hour expiry window must be intact and
   unexpired. It then runs
   `check_terraform_plan_policy.py --profile staging` and
   `check_cost_model.py --profile staging` against the resulting inventory.
5. **Assert the awake shape.** The planned ECS desired counts are compared by
   exact dictionary equality against the counts computed from
   `runtime_deployment.yaml × awake multiplier`, using deploy.yml's naming rule
   (`api` → `AETHER-staging-backend`, every other key →
   `AETHER-staging-<key>`). An extra planned service, a missing one or a wrong
   count all fail. Awake is 1 API task and 1 `lean-worker` task.
6. **`wake-apply` dispatches `action=apply`** with the plan run ID and checksum
   taken from `wake-validate`'s outputs — never straight from the dispatch
   inputs.
7. **Wait for readiness**: `aws ecs describe-clusters`, then
   `aws ecs wait services-stable` across every service in the cluster. Zero
   services after a wake is an error.
8. **Open the awake lease.**

### Aurora resume

`profiles/staging.tfvars` sets `aurora_min_acu = 0` / `aurora_max_acu = 2`.
Aurora Serverless v2 with a zero floor **auto-pauses when idle**, so a woken
staging environment starts with a paused database.

This is intentional and is the single largest reason staging's budget is USD 25
rather than production-lean's USD 150: an idle staging cluster costs nothing per
hour. The operational consequence is a **cold start on the first database
connection after a wake**. Nothing in the workflow explicitly resumes the
cluster; the first query does it. Expect the first `/v1/ready` probe and the
migration task to absorb that latency, and do not treat a slow first response
as a regression. `production-lean` deliberately does not share this behaviour —
see the rejected lever in [Cost Optimization](COST-OPTIMIZATION.md#rejected-lever-1--drop-the-aurora-floor-to-0-acu).

### The awake lease

The lease is one SSM Parameter Store `String` at
`/aether/staging/lifecycle/awake-until` holding an **absolute UTC deadline**
(`%Y-%m-%dT%H:%M:%SZ`), written as `now + max_awake_hours` after a successful
wake apply and stable services.

| Actor | Effect on the lease |
|---|---|
| `staging-lifecycle.yml` → `wake-apply` | writes `now + max_awake_hours` (1–8 h, default 4) |
| `staging-ttl-guard.yml` mode `extend` | **overwrites** with `now + extend_hours` (1–4 h); does not add to the existing deadline |
| `staging-lifecycle.yml` → `sleep` | deletes it (`always()`) |
| `staging-ttl-guard.yml` enforcement | deletes it after scaling to zero |

## The TTL guard

`.github/workflows/staging-ttl-guard.yml` runs **hourly at minute 17 UTC** and
is the backstop for a rehearsal that never returned to sleep.

**Not armed without the lifecycle role.** When `AWS_STAGING_LIFECYCLE_ROLE_ARN`
is not configured, the guard has no credential to read the lease or enforce the
TTL, reports it is a NO-OP and exits green — staging may still be running and
will **not** be guarded; that is **not** a claim that staging is asleep. The
moment the role is wired it enforces exactly as below, fail-closed in both
directions.

Its design constraints are deliberate and worth understanding before relying on
it:

- It **never runs Terraform** and **never dispatches a reviewed apply**.
  `terraform-promote.yml` is `workflow_dispatch`-only precisely so no timer can
  reach an apply.
- Its only enforcement is an ECS scale-to-zero plus zeroing Application Auto
  Scaling floors — operations that can only *reduce* compute.
- **A missing, empty, unparseable or `None` lease is treated as expired.** So is
  a lease more than `MAX_TOTAL_AWAKE_HOURS` (12 h) in the future.
- On a scheduled run the mode is forced to `enforce`; it cannot degrade to
  `report-only`.

Modes:

```bash
# Look, don't touch
gh workflow run staging-ttl-guard.yml -f mode=report-only

# Buy more time — refused if staging is already asleep, reason mandatory
gh workflow run staging-ttl-guard.yml \
  -f mode=extend -f extend_hours=2 \
  -f extend_reason="investigating intermittent graph-writer lag in rehearsal 412"

# What the hourly schedule does
gh workflow run staging-ttl-guard.yml -f mode=enforce
```

When enforcement fires it, in order: refuses to act unless the cluster is
literally `AETHER-staging`; sets every service's `--desired-count 0`; registers
every matching scalable target at `--min-capacity 0`; deletes the lease; then
re-reads the cluster to compute residual tasks.

**A successful enforcement makes the run red on purpose.** The guard emits an
error telling the operator to run `staging-lifecycle.yml` with
`action: apply-sleep` to reconcile Terraform state, because the guard changed
live desired counts and autoscaling floors *outside* Terraform. A green TTL
guard run means nothing needed doing; a red one is either "I cleaned up after
you, now reconcile" or "I could not clean up, intervene manually".

## Full rehearsal

`action=full-rehearsal` runs wake → rehearse → sleep. The `rehearse` job is the
only job in the workflow behind a GitHub environment (`staging`); the apply
approvals live in `terraform-promote.yml`.

Steps, in order, with what each proves:

1. **Exact-artifact verification.** `release.json` is validated against its
   commit SHA and approved checksum; every artifact
   (`aether_spa`, `kyber_spa`, `migration_package`, `configuration`) is
   re-hashed and compared to its recorded digest; the manifest's backend digest
   must equal the digest the applied wake plan pinned; and **every** running
   ECS service's task definition image must equal the manifest's
   `backend_image.uri`. Staging is proven to be running the exact artifact
   under review, not a rebuild of it.
2. **Static publication.** The lease is revalidated with at least five minutes
   remaining, then the approved `aether_spa` and `kyber_spa` archives are
   unpacked and synchronized into their staging S3 origins with `aws s3 sync
   --delete`. `index.html` is uploaded with no-cache headers, every object is
   read back, and the bucket contents are compared byte-for-byte with the
   release artifact. This is a real staging mutation: it requires the scoped
   S3 write permission and fails closed if the lease expires or publication
   differs from the approved digest.
3. **Migrations.** A one-off Fargate task is launched from the
   `AETHER-staging-backend` task definition with `RUN_MIGRATIONS=1`
   (`alembic upgrade head`), awaited with `aws ecs wait tasks-stopped`, and
   required to exit 0. The resulting revision is then verified over HTTP: a 200
   from `/v1/ready` whose body mentions `alembic` or `migration`.
   On a `public_ip` profile the run-task network configuration needs
   `assignPublicIp=ENABLED` — there is no NAT to egress through.
4. **Readiness and frontend availability.** `/v1/health` and `/v1/ready` must
   both return 200. For each of `aether` and `kyber`, the static bucket name is
   read from SSM (`/aether/staging/AETHER_STATIC_BUCKET`,
   `/aether/staging/KYBER_STATIC_BUCKET`) and `index.html` must exist.
5. **Tenant isolation.** The run uses the encrypted staging admin bootstrap
   key to create two fresh, free, run-scoped tenants and one API key for each.
   The raw keys are masked and held only in the runner environment; they are
   never committed or uploaded. Their `tenant_id` values must differ. A
   cross-tenant read of the peer's consent records must return 401/403/404 — a
   200 is a breach and fails the run. An unauthenticated `/v1/me` must fail
   closed.
6. **Capability checks.** `scripts/staging_capability_matrix.py --json`,
   `scripts/smoke_test.py`, then explicit probes for auth, consent/privacy
   (records, retention manifest, DSR), ingestion, **queue-worker drain**
   (polls analytics for the ingested event for up to 300 s; failure to drain is
   reported as the `lean-worker` execution group not draining — this is the
   check that proves consolidation actually works), graph, analytics, and
   inline ML (`/v1/ml/models`, since staging runs `remote_ml: false`).
7. **Synthetic-seed exclusion and empty state.**
   `scripts/validate_frontend_data_truth.py`, plus a probe that an unknown
   subject returns no records, plus a scan of the response for the markers
   `demo`, `synthetic`, `sample-tenant`, `lorem`.
8. **Baseline load.** `scripts/load_smoke.py --users 10 --duration 60`.
9. **Failure and retry.** A malformed ingest payload must be a 4xx — a 5xx is a
   server error and a 2xx means it was accepted. A duplicate event must not
   produce a 5xx.
10. **Rollback rehearsal.** Refuses to run outside the `AETHER-staging` cluster.
   Rolls `AETHER-staging-backend` back to the previous task-definition revision,
   waits for stability, asserts the rollback took effect and `/v1/health` is
   200, then restores the current revision and waits again. On the first
   approved revision there is no earlier task definition, so the step records
   `not_applicable` instead of fabricating a rollback; every later revision must
   execute and verify both rollback and roll-forward.
11. **Evidence collection.** ECS service state, log groups, CloudWatch metrics,
    `release.json`, and a cost-model run. Every command is `|| true`, so this
    step never fails the rehearsal.
12. **Tenant cleanup.** Every run-scoped tenant recorded by the bootstrap or
    registration marker is removed with `DELETE /v1/admin/tenants/{id}`, falling
    back to `POST .../deactivate`. Both admin paths revoke contained public
    ingest identifiers before deleting or deactivating the tenant. Marker IDs
    are validated and cleanup refuses to guess when a marker is malformed or
    absent. Cleanup attempts every recorded tenant even if one delete and its
    deactivation fallback fail, then fails the step with the complete list of
    failures; neither operation may silently succeed with an unknown state.

## Sleep

The `sleep` job runs `if: always()`. That is the point of it: staging returns to
zero even when the wake failed, the migration failed, smoke failed, load failed,
the rollback rehearsal failed, or evidence collection failed. It reports the
upstream failure but never repairs or masks it — the `outcome` job re-raises it
at the end.

1. **Record what is being cleaned up after.** Any of `wake-plan`,
   `wake-validate`, `wake-apply` or `rehearse` in `failure`/`cancelled`/
   `timed_out` sets `validation_result=failure` for the summary.
2. **Skip only when provably at zero.** The reviewed sleep plan is skipped only
   if the cluster exposes no ECS services at all, or
   `length(services[?desiredCount>`0`])` is zero. Note this consults
   `desiredCount` only.
3. **Generate the reviewed sleep plan** — dispatch `terraform-promote.yml` with
   `action=plan`, `staging_state=asleep`, same 300 s discovery window with the
   same hard failure on ambiguity.
4. **Verify the plan and assert the asleep shape.** Same 14-artifact,
   checksum, profile, state-key and 24-hour-expiry verification as wake. Then:
   the expected map must be **all zero** (a non-zero expected count means the
   `asleep` multiplier itself has drifted); the planned counts must equal it
   exactly; and **every** Application Auto Scaling target in the plan must have
   a floor of 0 or null — `asleep plan leaves an autoscaling floor of N` is a
   failure. Enabled EventBridge/Scheduler rules are collected and printed but
   do not fail.
5. **Apply the reviewed sleep plan** when `action=apply-sleep` or
   `full-rehearsal`. A non-success conclusion here is a **warning**, not a
   failure, precisely so the last-resort stop below still runs.

### Fail-safe cleanup

If staging was not already at zero and the reviewed sleep apply did not
succeed, the last-resort cost stop runs:

```bash
test "$STAGING_CLUSTER" = "AETHER-staging" || exit 1   # refuses outside staging
for service in "${services[@]}"; do
  aws ecs update-service --cluster AETHER-staging --service "$service" --desired-count 0
  echo "::warning::scaled ${service} to 0 outside Terraform; state must be reconciled"
done
```

It reduces only. Unlike the TTL guard it does **not** touch autoscaling floors,
so a service with a non-zero floor can be scaled back up by Application Auto
Scaling after this stop runs. That gap is why the residual check below inspects
floors separately and why the job fails when it finds one.

The stop also fires on a plain `plan-sleep` run whenever staging was not
already at zero, because there is no apply conclusion to succeed.

### Residual inspection

Run `if: always()`, after the stop. It inspects exactly two resource classes in
the `AETHER-staging` cluster:

- **ECS services** — `desiredCount`, `runningCount`, `pendingCount` for every
  service, written to `artifacts/sleep/desired-counts.json`. Any service with
  any of the three non-zero fails the job.
- **Application Auto Scaling scalable targets** in the `ecs` namespace whose
  `ResourceId` contains `AETHER-staging`, written to
  `artifacts/sleep/autoscaling.json`. Any non-zero `MinCapacity` fails the job.

It then prices the residue: task sizes come from
`config/runtime_deployment.yaml`, rates from `config/aws_price_book.yaml`
(`vcpu_hour` 0.04048, `gb_hour` 0.004445), tasks per service are
`max(desired, running + pending)`, and the result is reported as
`residual_cost_usd_per_hour`.

**Known scope limit.** Residue detection covers ECS services and ECS
autoscaling floors only. Standalone `run-task` tasks (including an orphaned
migration task), EC2 instances, RDS, NAT Gateways and Elastic IPs are **not**
inspected. On staging that is a small gap — `nat_mode` is `none` so there is
nothing NAT-shaped to leak, and Aurora auto-pauses at 0 ACU — but a stray
`run-task` will not be caught and must be checked by hand if a rehearsal died
mid-migration.

## Evidence

Each job uploads from its own runner, so the artifacts do not merge into one
bundle.

| Artifact | Contents | Retention |
|---|---|---|
| `staging-wake-plan-validation-<run_id>` | `artifacts/wake-plan-policy.txt`, `artifacts/wake-plan-cost.txt`, `artifacts/profile-resource-inventory.json` | 14 days |
| `staging-rehearsal-<run_id>` | everything under `artifacts/rehearsal/` — `bootstrap-marker.json`, `registration-marker.json`, `static-publication.txt`, `migrations.txt`, `ready.json`, `tenant.json`, `capability-matrix.json`, `capabilities.json`, `smoke.txt`, `data-truth.txt`, `load.json`, `load.txt`, `rollback.txt`, `ecs-services.json`, `log-groups.json`, `metrics.json`, `release.json`, `cost.txt` | 30 days |
| `staging-lifecycle-evidence-<run_id>` | `artifacts/sleep-plan-policy.txt`, `artifacts/sleep/desired-counts.json`, `artifacts/sleep/autoscaling.json`, `artifacts/evidence.sha256`, `artifacts/evidence.sha256.sha256` | 30 days |
| `staging-ttl-guard-<run_id>` | `services.json`, `services-after.json`, `actions.log` | 30 days |

`artifacts/evidence.sha256` is a deterministic `sha256sum` manifest of every
file under `artifacts/` on the sleep runner, sorted, with a checksum of the
manifest itself alongside it. **It covers the sleep job's own files only, not
the rehearsal artifacts.**

These are GitHub Actions artifacts. They are **not** the release-evidence
bundle. `config/deployment_readiness.yaml` expects credentialed lifecycle
evidence at `release-evidence/lifecycle/staging-wake.json`,
`release-evidence/lifecycle/rehearsal-history.json` and
`release-evidence/lifecycle/sleep-residual.json`; promoting a rehearsal's
artifacts into that layout is a manual step that has never been performed,
because no credentialed rehearsal has ever run.

## Incident handling

### The lifecycle run is red

Read `outcome` first. It lists which phases failed and never masks one; a
skipped job is not counted as a failure. Then read the `sleep` job's step
summary table — validation result, cleanup result, reviewed sleep apply,
services force-scaled to zero, residual tasks, estimated residual cost, manual
intervention required.

`cleanup_result` has three values:

| Value | Meaning | Action |
|---|---|---|
| `success` | Reviewed sleep applied and nothing residual | None |
| `degraded` | Staging is at zero but got there outside Terraform | Run `apply-sleep` to reconcile state |
| `failure` | A service or an autoscaling floor is still non-zero | Manual intervention — staging is still billing |

### Staging is still awake and money is running

1. Dispatch `staging-lifecycle.yml -f action=apply-sleep` (add
   `-f ml_image_digest=...` only when the selected profile has `remote_ml: true`).
   This is the correct path: it goes through a reviewed plan and leaves
   Terraform state consistent.
2. If that cannot run (promotion credentials broken, approval unavailable),
   dispatch `staging-ttl-guard.yml -f mode=enforce`. It will scale services to
   zero and zero the autoscaling floors immediately, and it will go red telling
   you to reconcile.
3. After any out-of-band scale-to-zero, **run `apply-sleep`**. Terraform still
   believes the desired counts are 1. The next apply for any reason will
   restore them.

### The TTL guard is red every hour

Either staging is genuinely stuck awake (see above), or the lease is confusing
it. The guard treats a missing lease as expired, so a manual `aws ecs
update-service` that woke staging without writing a lease will be enforced
against on the next hour. Wake through the workflow, not by hand.

### The rehearsal drained nothing

`the lean-worker execution group did not drain the ingested event` after 300 s
means the consolidated worker task is not processing. Check that
`AETHER-staging-lean-worker` has a running task, then check its log group for
the eight roles' startup lines. This is the consolidation-specific failure mode
and is exactly what staging exists to find before production does.

### A reviewed plan expired mid-run

Reviewed plans are valid for 24 hours and apply refuses an expired one. If
`promote_timeout_minutes` was spent waiting on an environment approval, the plan
may age out. Re-run `plan-wake` and approve promptly; do not extend the expiry.

### Ambiguous dispatched run

`ambiguous reviewed-plan runs (...); refusing to guess` means two candidate
`terraform-promote.yml` runs appeared in the 300 s discovery window. Do not
re-run blindly — find out who else dispatched a promotion, let it finish, then
retry. The `staging-lifecycle` concurrency group is `staging-lifecycle`, which
does not serialise manual dispatches of `terraform-promote.yml`.

## Known gap: `staging_state` is not a promotion input

`staging-lifecycle.yml` dispatches the promotion workflow with
`-f staging_state=awake` and `-f staging_state=asleep`, but
`.github/workflows/terraform-promote.yml` declares **no `staging_state` input**
and its `terraform plan` invocation passes no `-var staging_state=`.

Two consequences, both real:

1. `gh workflow run` rejects an undeclared input, so the wake and sleep
   dispatches will fail rather than silently plan the wrong shape.
2. Even if the dispatch were accepted, the plan would fall back to the root
   variable's default of `awake`, and the sleep job's own "assert the asleep
   shape" check would then catch it — the asleep assertion compares planned
   counts against an all-zero expectation by exact equality.

So the failure mode is loud in both directions, which is the right side to fail
on, but the wake/sleep path **cannot currently complete end to end**. This is
recorded in `config/implementation_ledger.yaml` under `FT-9-STAGING-LIFECYCLE`.
No claim on this page should be read as saying a rehearsal has been executed.

## What has not been proven

Nothing on this page has been executed against real infrastructure. Every
staging readiness control in `config/deployment_readiness.yaml` is unproven:
the staging scorecard reads **75/100 code-complete, 0/100 externally-verified**
against a gate of 95, and `deployment_ready: false`.

Specifically externally blocked:

- A credentialed wake apply (`COND-STAGING-WAKE-APPLIED`).
- Two **consecutive** complete rehearsals with no failed or partial run between
  them (`COND-STAGING-TWO-REHEARSALS`). One green run is an anecdote.
- Migration forward-and-rollback against a real database
  (`COND-MIGRATION-REHEARSED`).
- Smoke against a deployed environment (`COND-SMOKE-PASSED`) — also not
  code-complete: `STG-SMOKE` has no `smoke-result` artifact path.
- Security, privacy and tenant-isolation probes against a deployed environment
  (`COND-SECURITY-VALIDATED`).
- Load validation (`COND-LOAD-VALIDATED`) — also not code-complete
  (`STG-LOAD`).
- An executed rollback with a recovery timestamp (`COND-ROLLBACK-VALIDATED`).
- A measured sleep residual under the declared ceiling
  (`COND-SLEEP-RESIDUAL`).

## See also

- [Cost Optimization](COST-OPTIMIZATION.md) — the awake-hours budget model
- [AWS Lean Production](AWS-LEAN-PRODUCTION.md) — the topology staging rehearses
- [Deployment Profiles](DEPLOYMENT-PROFILES.md) — the eight-profile matrix
- [Deployment Runbook](DEPLOYMENT-RUNBOOK.md) — application promotion
