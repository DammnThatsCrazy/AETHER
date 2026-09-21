---
title: Staging Wake / Sleep
slug: operations/staging-wake-sleep
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: stable
since_version: "0.1.0"
source_files:
  - .github/workflows/staging-lifecycle.yml
  - .github/workflows/staging-ttl-guard.yml
  - .github/workflows/terraform-promote.yml
  - .github/workflows/pilot-staging.yml
  - .github/workflows/staging-smoke.yml
  - .github/workflows/amplify-status-production.yml
  - config/runtime_deployment.yaml
  - config/deployment_profiles.yaml
  - deploy/aws/terraform/profiles.tf
  - deploy/aws/terraform/variables.tf
  - deploy/aws/terraform/profiles/staging.tfvars
  - scripts/release/check_staging_lane_contract.py
  - scripts/release/check_staging_credential_contract.py
  - scripts/release/check_amplify_app_contract.py
  - scripts/release/check_staging_secret_payload_contract.py
  - scripts/release/check_staging_secret_preflight_policy.py
  - scripts/release/check_staging_task_definition_contract.py
  - config/staging_secret_preflight_iam_policy.yaml
  - config/staging_secret_preflight_trust_policy.json
canonical_owner: platform@aether
estimated_read_minutes: 18
toc_depth: 3
source_hashes:
  ".github/workflows/amplify-status-production.yml": "sha256:7f5ba24a66904f7675c6f8260a3f65a99125db37134baae806b723a5d721f846"
  ".github/workflows/pilot-staging.yml": "sha256:6f01ef3271178d33d925e108f7a0d71f2ad16240f345accbc866bc7f9533a47b"
  ".github/workflows/staging-lifecycle.yml": "sha256:30db90946b2611fb62cf4ec64600b353b046312869b97f927fb5e4632205e4ff"
  ".github/workflows/staging-smoke.yml": "sha256:bf9c21599a780f84fac02ae320669dc8522b9a9b9e2f35a75aa7ff7bbcb57e68"
  ".github/workflows/staging-ttl-guard.yml": "sha256:c441dd81c2354b8608cb362024f5d3431a380f26e1244eb433ba1e6882d386da"
  ".github/workflows/terraform-promote.yml": "sha256:2a41dc438ae0fdea7b1e78537affd2344697c32d0d8b78cbf9c64c5d2d1fbd0f"
  "config/deployment_profiles.yaml": "sha256:83715252d5052cd9ef78a33db51ea7f7f73c5b850821bdb37e35f47a9e8ced6b"
  "config/runtime_deployment.yaml": "sha256:7c6ebe1fafec7f7a2fae8e054cd09ffe0b0f78bd8c6694bdd4da1d517740d7d8"
  "config/staging_secret_preflight_iam_policy.yaml": "sha256:06ad4ef9c7777eff1190d01b02536542b902692051532f640635e128d5c1403d"
  "config/staging_secret_preflight_trust_policy.json": "sha256:35974a1b8ddb89cd605c79ea10bbf06510886b7a04f0e619fb301220c08b55c8"
  "deploy/aws/terraform/profiles.tf": "sha256:e8db2b2d668be5f42c72f0cc9e45aedde9eb441e33ef8fba5fe2b55946e32560"
  "deploy/aws/terraform/profiles/staging.tfvars": "sha256:30b3fa7a866dbf24e67096fbe9ddff0bbe5afcd3fb414e01b04991914d0d0836"
  "deploy/aws/terraform/variables.tf": "sha256:6153654e6668f4673cd15ceb44ea3caf14ba44ca274750d4ad7c7361127c361a"
  "scripts/release/check_amplify_app_contract.py": "sha256:28fe586a024e18c9375af589b4d9c2527cce03071ad55ec88a2f6a1237a596db"
  "scripts/release/check_staging_credential_contract.py": "sha256:b5960e8b08f2714ca2fa42f835cc2bb3f79bf3350745215ba58acd25e06a648c"
  "scripts/release/check_staging_lane_contract.py": "sha256:7005ef21ff872335e729076c6c9e9e1e541e630e138b46589bf84f1985b968fb"
  "scripts/release/check_staging_secret_payload_contract.py": "sha256:74dca12d6b7606421bbd04d94c4698cc06b0d9f3774d03ba8402f5e27c2c9f52"
  "scripts/release/check_staging_secret_preflight_policy.py": "sha256:c1d8e7f3e28de4e0dd2fcf259cdbd3da95f2186ecee32c0dffcfca1443cd5f04"
  "scripts/release/check_staging_task_definition_contract.py": "sha256:c741b3fe45139c8493818dd2184c5ea530a44225eaa38a8ad435576d5273508e"
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
  -f release_run_id=<successful "Immutable delivery" build-only or deployed run id> \
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
| `release_run_id` | — | required for `full-rehearsal`; must be a successful `.github/workflows/deploy.yml` build-only or deployed run with a successful immutable-build job |
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
| Secret payload preflight role | `secrets.AWS_STAGING_SECRET_PREFLIGHT_ROLE_ARN` |
| ECS metadata read role | `secrets.AWS_TERRAFORM_PLAN_ROLE_ARN` (`AetherStagingPlan`) |
| Promotion workflow | `.github/workflows/terraform-promote.yml` |

The canonical profile and state key do not change between staging lanes. Every
staging lifecycle, delivery, promotion and smoke dispatch carries the explicit
`deployment_lane` token (`full` or `pilot`). `full` keeps the existing rehearsal
including Kyber/workforce checks. `pilot` is the complete lean AWS customer
staging path: it still provisions and verifies the Aether backend and public
surfaces, durable state, Stripe billing/webhooks/entitlements, tenant isolation,
observability, migrations, lifecycle controls and smoke coverage; only Kyber
operator/workforce identity and GCP/Google hosting/credentials are deferred.

Pilot admission is fail-closed. The repository contract validator checks the
bootstrap/ECS Stripe wiring before planning, and the promotion preflight also
requires populated current versions for the four self-service Stripe price
secrets (`aether/stripe-price-alpha`, `-beta`, `-gamma`, and `-delta`).
Epsilon, Omicron, and Omega remain contract-tier operator mappings and are not
part of the self-service pilot critical path. The secure bootstrap rejects
malformed or placeholder values before writing them; the workflow preflight
reads metadata only and never prints or invents a price ID.
If one of the four self-service price secrets predates the staging CMK, the pilot
reconcile path can re-encrypt it with an explicit
`migrate_legacy_secret_kms=true` and `MIGRATE-STAGING-SECRETS` confirmation;
the migration uses metadata-only Secrets Manager calls and does not read the
secret value.

The pilot wrapper treats `plan-sleep` and `apply-sleep` as cleanup actions:
after the contract job, it skips credential, secret-payload and Amplify
readiness checks that require application values or current app artifacts, then
still dispatches the canonical lifecycle authority. A direct apply cannot use
the requested `staging_state` input to bypass a preflight; only the explicit
sleep-only `secret_preflight_required=false` flag is accepted, and the apply
must prove that the reviewed plan artifact itself records `staging_state=asleep`.

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
   `deployment_lane=full|pilot`, `staging_state=awake` and both digests. Run
   the workflow-dispatch command and capture the exact run URL returned by
   GitHub. If GitHub does not return a run ID, the handoff fails closed rather
   than guessing from concurrent-run history. Completion is awaited up to
   `promote_timeout_minutes`.
3. **Verify the plan artifact.** All 16 `reviewed.*` files must be present and
   non-empty; `reviewed.profile == staging`;
   `reviewed.state-key == profiles/staging/terraform.tfstate`;
   `reviewed.state-bucket` and `reviewed.state-lock-table` must be present and
   syntactically valid;
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
8. **Arm the awake lease before apply, then refresh it after readiness.**

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
(`%Y-%m-%dT%H:%M:%SZ`). `wake-apply` writes `now + max_awake_hours` before it
dispatches the reviewed apply, so a failed or abandoned apply is still bounded.
After the services become ready, the workflow refreshes the deadline from the
same original `awake_since`; the refresh never resets the total-awake clock.

| Actor | Effect on the lease |
|---|---|
| `staging-lifecycle.yml` → `wake-apply` | arms `now + max_awake_hours` before apply, then refreshes it after readiness (1–8 h, default 4) |
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

When armed, the guard first validates and assumes
`AWS_TERRAFORM_PLAN_ROLE_ARN` (`AetherStagingPlan`) to inspect the effective
`AetherStagingLifecycle` IAM policy. Only after that inspection succeeds does it
assume `AWS_STAGING_LIFECYCLE_ROLE_ARN` for SSM/ECS lease enforcement. The
lifecycle role therefore never needs IAM policy-read permissions merely to run
the TTL guard.

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

The public production status app is established separately from the staging
runtime wake. On a merged `main` push, `amplify-status-production.yml` waits
for the exact main integration authority, then binds `aether-status` to the
repository, recreates its production `main` branch when migrating the legacy
manual deployment, deploys the exact merge SHA, and verifies the public
`status.olympuslabsml.com` association and its live CNAME target. Before changing a domain mapping, the
workflow disables Amplify auto-subdomain creation and intentionally omits the
optional delegated IAM role, so the pilot/status path does not require
`iam:PassRole`. Squarespace remains authoritative; the dedicated empty
`AETHER-staging-amplify-domain-role` remains reserved for a separately reviewed
auto-subdomain operation. A repository-backed status app is updated in place on
later runs; it is never treated as a staging ECS or Terraform mutation.

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
   remaining, then the approved protected tenant `aether_spa` and internal
   `kyber_spa` archives are unpacked and synchronized into their staging S3
   origins with `aws s3 sync --delete`. `index.html` is uploaded with no-cache
   headers, every object is read back, and the bucket contents are compared
   byte-for-byte with the release artifact. This is a real staging mutation:
   it requires the scoped S3 write permission and fails closed if the lease
   expires or publication differs from the approved digest. The five public
   Amplify applications (Olympus, Aether, docs, app, and status) are a
   separate application-delivery surface; their branch builds and
   verified `*.staging.olympuslabsml.com` domain checks belong to the Amplify
   delivery/smoke workflows, not this private S3 publication phase.
3. **Migrations.** A one-off Fargate task is launched from the
   `AETHER-staging-backend` task definition with `RUN_MIGRATIONS=1`. The
   release entrypoint runs `alembic upgrade head` and receives an explicit
   `/bin/sh -c 'exit 0'` command override so it exits after migrations instead
   of starting a second long-running API process. It is awaited with
   `aws ecs wait tasks-stopped`, its stopped task and exit code are retained as
   evidence, and it is required to exit 0. The resulting revision is then
   verified over HTTP: a 200 from `/v1/ready` whose body mentions `alembic` or
   `migration`.
   On a `public_ip` profile the run-task network configuration needs
   `assignPublicIp=ENABLED` — there is no NAT to egress through.
4. **Readiness and frontend availability.** `/v1/health` and `/v1/ready` must
   both return 200. For each of the protected `aether` and `kyber` artifacts,
   the static bucket name is read from SSM
   (`/aether/staging/AETHER_STATIC_BUCKET`,
   `/aether/staging/KYBER_STATIC_BUCKET`) and `index.html` must exist. The
   five public Amplify apps are checked by their own delivery/smoke gate; this
   lifecycle phase does not claim to publish or verify those separate Amplify
   domains. Staging intentionally does not attach the production custom domain
   or a production status API URL.
   Before apply, the promotion workflow verifies that every ECS-mounted
   application Secrets Manager name has an `AWSCURRENT` version and, when the
   canonical Aurora already exists, that its AWS-managed `MasterUserSecret`
   reports `active`. Terraform creates the
   encrypted secret stubs but never invents their values; bootstrap or import
   those values through the secure operator procedure before a wake. The check
   reads metadata only and never uploads or prints secret material. In the
   pilot lane, the Kyber workforce pair (`aether/kyber-google-client-id` and
   `aether/kyber-google-client-secret`) is intentionally deferred; the twelve
   core application secrets and four real self-service Stripe test-price
   secrets remain required, and the value-safe payload contract checks the
   `sk_test_`, `whsec_`, and `price_` forms. In the full lane, the twelve base
   application secrets and Kyber pair remain required, while the pilot-only
   Stripe price secrets are not required. The
   payload check assumes the dedicated `AetherStagingSecretPreflight` OIDC
   role, whose reviewed reads are `secretsmanager:GetSecretValue` for the
   `aether/*` prefix plus `kms:Decrypt` only for the staging Secrets Manager
   CMK under its alias and environment-tag conditions. The lifecycle role
   remains forbidden from reading secret values. The pilot smoke gate then
   switches to the read-only `AetherStagingPlan` role for ECS
   `DescribeServices`/`DescribeTaskDefinition` metadata; it never broadens the
   secret preflight role. After a reviewed apply,
   `check_staging_task_definition_contract.py`
   reads only ECS metadata and proves both the API and `lean-worker` revisions
   match the selected lane, including the pilot Stripe mounts and the absence
   of deferred Kyber mounts. A stale registered revision is a hard failure,
   not a successful source-only check. The
   Google client must use the API callback
   `https://<api-domain>/v1/kyber/auth/callback`; the Kyber SPA origin is the
   separate WebAuthn origin. This prevents a green infrastructure plan from
   producing the earlier task-start failure caused by missing workforce
   identity anchors.
5. **Tenant isolation.** The run uses the encrypted staging admin bootstrap
   key to create two fresh, free, run-scoped tenants and one API key for each.
   The raw keys are masked and held only in the runner environment; they are
   never committed or uploaded. Their `tenant_id` values must differ. A
   cross-tenant read of the peer's consent records must return 401/403/404 — a
   200 is a breach and fails the run. An unauthenticated `/v1/me` must fail
   closed.
6. **Capability checks.** `scripts/staging_capability_matrix.py --json`,
   `scripts/smoke_test.py` (the tenant key covers data-plane checks and the
   encrypted `STAGING_ADMIN_API_KEY` is supplied only to the two admin
   diagnostics probes), then explicit probes for auth, consent/privacy
   (records, retention manifest, DSR), ingestion, **queue-worker drain**
   (polls analytics for the ingested event for up to 300 s; failure to drain is
   reported as the `lean-worker` execution group not draining — this is the
   check that proves consolidation actually works), graph, analytics, and
   inline ML (`/v1/ml/models` plus the unique in-process `/models` probe,
   since staging runs `remote_ml: false`).
7. **Synthetic-seed exclusion and empty state.**
   `scripts/validate_frontend_data_truth.py`, plus a probe that an unknown
   subject returns no records, plus a scan of the response for the markers
   `demo`, `synthetic`, `sample-tenant`, `lorem`.
8. **Baseline load.** `scripts/load_smoke.py --users 10 --duration 60
   --api-key "$REHEARSAL_TENANT_API_KEY"`, so the load path exercises the same
   authenticated tenant contract as the capability probes.
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
    `release.json`, and a cost-model run are collected with required AWS
    permissions. Missing or unreadable evidence is a rehearsal failure; no
    command is allowed to turn an evidence error into a false green.
12. **Tenant cleanup.** Every run-scoped tenant recorded by the bootstrap or
    registration marker is removed with `DELETE /v1/admin/tenants/{id}`, falling
    back to `POST .../deactivate`. Both admin paths revoke durable API keys,
    invalidate and verify the Redis auth-cache entries, and revoke contained
    public ingest identifiers before deleting or deactivating the tenant. A
    successful DELETE must return a `cleanup_complete` receipt after erasing
    every rehearsal surface (consent/DSR and propagation indexes, feed and SDK
    Bronze/Silver/Gold records, analytics, profiles, and graph projection);
    billing and security-audit evidence retained by policy is detached rather
    than silently claimed erased. Marker IDs are validated and cleanup refuses
    to guess when a marker is malformed or absent. Cleanup attempts every
    recorded tenant even if one delete and its deactivation fallback fail, then
    fails the step with the complete list of failures; neither operation may
    silently succeed with an unknown state.

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
4. **Verify the plan and assert the asleep shape.** Same 16-artifact,
   checksum, profile, state-key, state-backend and 24-hour-expiry verification
   as wake. Then:
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
succeed, the last-resort cost stop runs. It scales services down, lowers the
matching autoscaling floors through the reviewed lifecycle permissions, and
stops every remaining running or pending ECS task in the staging cluster:

```bash
test "$STAGING_CLUSTER" = "AETHER-staging" || exit 1   # refuses outside staging
for service in "${services[@]}"; do
  aws ecs update-service --cluster AETHER-staging --service "$service" --desired-count 0
  echo "::warning::scaled ${service} to 0 outside Terraform; state must be reconciled"
done
for task_arn in "${task_arns[@]}"; do
  aws ecs stop-task --cluster AETHER-staging --task "$task_arn" \
    --reason 'staging reviewed sleep apply failed'
done
```

It reduces only and never provisions. Any force-stop or floor change is called
out as outside-Terraform state that requires a later reviewed reconciliation;
the residual check below still fails if a floor, service, or task remains.

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

**Known scope limit.** Residue detection covers ECS services, running/pending
ECS tasks, and ECS autoscaling floors. EC2 instances, RDS, NAT Gateways and
Elastic IPs are not inspected by the sleep job; staging's `nat_mode` is `none`
and Aurora auto-pauses at 0 ACU. A task that cannot be enumerated or described
is an unknown-state failure, not an asleep result.

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
artifacts into that layout is a manual release-evidence step. A credentialed
rehearsal has run, but the latest run failed during migration because the
immutable backend image did not contain `psycopg2`; no successful full
rehearsal has yet been recorded.

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

## Promotion input: `staging_state`

`terraform-promote.yml` declares `staging_state` as an explicit `awake` /
`asleep` choice and passes it to Terraform as `-var staging_state=...`.
The lifecycle workflow records the same value in the reviewed plan and the
apply job verifies that recorded value before consuming the binary plan.
This keeps the wake/sleep shape reviewable and prevents a plan for one shape
from being applied as the other.

This wiring is a source-level control, not runtime evidence. A complete
rehearsal still requires a hosted plan, reviewed apply, and successful
post-apply shape checks tied to the exact commit and plan checksum.

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
