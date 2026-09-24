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
  - .github/workflows/deploy.yml
  - .github/workflows/staging-ttl-guard.yml
  - .github/workflows/terraform-promote.yml
  - .github/workflows/pilot-staging.yml
  - .github/workflows/reconcile-staging-plan-role.yml
  - .github/workflows/staging-smoke.yml
  - .github/workflows/amplify-status-production.yml
  - services/backend/alembic/versions/20260702_delivery_infrastructure.py
  - config/runtime_deployment.yaml
  - config/deployment_profiles.yaml
  - config/staging_lifecycle_iam_policy.yaml
  - deploy/aws/terraform/profiles.tf
  - deploy/aws/terraform/variables.tf
  - deploy/aws/terraform/profiles/staging.tfvars
  - deploy/aws/terraform/modules/ecs/main.tf
  - scripts/release/check_staging_lane_contract.py
  - scripts/release/check_staging_credential_contract.py
  - scripts/release/check_staging_runtime_iam.py
  - scripts/release/check_staging_lifecycle_policy.py
  - scripts/release/bootstrap_staging_admin_key.py
  - scripts/release/ensure_staging_autoscaling_target_tags.py
  - scripts/release/check_amplify_app_contract.py
  - scripts/release/check_staging_secret_payload_contract.py
  - scripts/release/check_staging_secret_preflight_policy.py
  - scripts/release/check_staging_task_definition_contract.py
  - scripts/release/check_staging_awake_lease.py
  - scripts/release/reconcile_staging_plan_role.py
  - config/staging_secret_preflight_iam_policy.yaml
  - config/staging_secret_preflight_trust_policy.json
  - config/staging_plan_iam_policy.yaml
  - config/staging_plan_reconcile_iam_policy.json
  - config/staging_plan_reconcile_trust_policy.json
  - config/terraform_plan_state_access_policy.yaml
canonical_owner: platform@aether
estimated_read_minutes: 18
toc_depth: 3
source_hashes:
  ".github/workflows/amplify-status-production.yml": "sha256:71773ae36b767f0b914026697240573183d8e5f971280c72cb7e477a84612bd1"
  ".github/workflows/deploy.yml": "sha256:bf66c442b7239daccaee5e82e25b764835b8d679c2831fc2658f281b45204310"
  ".github/workflows/pilot-staging.yml": "sha256:d58b403e87f22b728f224b9951e51c83032a26d71c23c69809cb729ae573190e"
  ".github/workflows/reconcile-staging-plan-role.yml": "sha256:0b3192802e7b8ad76dfb121339946c08a5f4b5efee5e8c36019145cb08df70e0"
  ".github/workflows/staging-lifecycle.yml": "sha256:af994b96bd6c7a1997c1e516356be23e1782f7d8dbca01d9fcfd1b984a0575ec"
  ".github/workflows/staging-smoke.yml": "sha256:bf9c21599a780f84fac02ae320669dc8522b9a9b9e2f35a75aa7ff7bbcb57e68"
  ".github/workflows/staging-ttl-guard.yml": "sha256:506e98c36a7d2b280a1e00397c9b8afe3c170c4d77b57e79ab36ddc88a664a8f"
  ".github/workflows/terraform-promote.yml": "sha256:e26e2608beb6cac5287a3b521cc0e3b0eb441da41daa59627292b74f543d17a5"
  "config/deployment_profiles.yaml": "sha256:83715252d5052cd9ef78a33db51ea7f7f73c5b850821bdb37e35f47a9e8ced6b"
  "config/runtime_deployment.yaml": "sha256:7c6ebe1fafec7f7a2fae8e054cd09ffe0b0f78bd8c6694bdd4da1d517740d7d8"
  "config/staging_lifecycle_iam_policy.yaml": "sha256:b6c9ae760b6e408c63a2b4fcf277499fa4764650f32854cee9b52943a9b3e4b1"
  "config/staging_plan_iam_policy.yaml": "sha256:e4c818162c2ede98217a53c123c2581bcf771cc9e2d1ccf58e048fff591598c3"
  "config/staging_plan_reconcile_iam_policy.json": "sha256:8cd18e4c0f1f2f1f0583c3705f6352e990a399cab3f08315f393ed9106cea12d"
  "config/staging_plan_reconcile_trust_policy.json": "sha256:4d413822419f32fb1cd82b99f8cabbda1b66a72c02f819d65b0213d15b14001a"
  "config/staging_secret_preflight_iam_policy.yaml": "sha256:06ad4ef9c7777eff1190d01b02536542b902692051532f640635e128d5c1403d"
  "config/staging_secret_preflight_trust_policy.json": "sha256:35974a1b8ddb89cd605c79ea10bbf06510886b7a04f0e619fb301220c08b55c8"
  "config/terraform_plan_state_access_policy.yaml": "sha256:3ef6bc24c567f84eb9a44c8a180d0f6f14e6c4a9fabb76138cb3543e4cf150e0"
  "deploy/aws/terraform/modules/ecs/main.tf": "sha256:ca2a52de871d72661439c932674799164c893d893be54a3fffaf40e377a855a1"
  "deploy/aws/terraform/profiles.tf": "sha256:be5cedd8602afe2450d53747e0d17f34817435939880a57b20e2b7fd4c50e3a0"
  "deploy/aws/terraform/profiles/staging.tfvars": "sha256:f08b229d63e97a9f7e37e07a6517c766a3de42d92578d19c7c713d9f111f346c"
  "deploy/aws/terraform/variables.tf": "sha256:6153654e6668f4673cd15ceb44ea3caf14ba44ca274750d4ad7c7361127c361a"
  "scripts/release/bootstrap_staging_admin_key.py": "sha256:096541627176be35c7699c30495602740fa0e44df25233c2d369258d1491f2e6"
  "scripts/release/check_amplify_app_contract.py": "sha256:73a2b2aea0910f3267a58f0c3e27084bcbebfd210abdf13a702e717ef30717c8"
  "scripts/release/check_staging_awake_lease.py": "sha256:7e13acfed4fef002cbf39b26e9e0c4e10ef4e9a4b1cf6445e44dbf0f90b6b704"
  "scripts/release/check_staging_credential_contract.py": "sha256:01c7eed02e4873e19be2477fe2a131c0bc0641aa7bcf9ab647187bb9575b6f23"
  "scripts/release/check_staging_lane_contract.py": "sha256:7005ef21ff872335e729076c6c9e9e1e541e630e138b46589bf84f1985b968fb"
  "scripts/release/check_staging_lifecycle_policy.py": "sha256:001a5330f78fb4c334c3ddf56448c464355bee4b16c1640a1cbd5041be499fb5"
  "scripts/release/check_staging_runtime_iam.py": "sha256:85aa09eb552d0d57d87a169c250d97bb2d9790b865530bcf3ab5b61760e97d60"
  "scripts/release/check_staging_secret_payload_contract.py": "sha256:4108624b378be9fe306c7a24608fd6f747a7598cd175b120a524a31cd67f6e4c"
  "scripts/release/check_staging_secret_preflight_policy.py": "sha256:c1d8e7f3e28de4e0dd2fcf259cdbd3da95f2186ecee32c0dffcfca1443cd5f04"
  "scripts/release/check_staging_task_definition_contract.py": "sha256:edfa749aba1fc6e49eb1a2c6a58d3ef36b78f2c084cd3644441eac090a740435"
  "scripts/release/ensure_staging_autoscaling_target_tags.py": "sha256:2f0733c66a6df555537336d88edf30dab740b1d8c30bbaf8140bab9463cb6b00"
  "scripts/release/reconcile_staging_plan_role.py": "sha256:0e886d472c9a6e4d317c4b0ae627461a5ce2af8caf548290a37a8f28708a9c5c"
  "services/backend/alembic/versions/20260702_delivery_infrastructure.py": "sha256:df8a6bf971bd9db9a907414a8b7e8f0695b6a7c01aa55719e40f869509510916"
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

`profiles.tf` applies that multiplier to task count and autoscaling floor for
both lanes:

- `desired_count`
- the autoscaling **floor** (`min_capacity`)

The autoscaling ceiling (`max_capacity`) is deliberately unchanged; it is the
static safety bound, not current capacity. In the full lane, Terraform also
scales the capacity provider's guaranteed `base_count`. The **pilot** lane
instead pins `base_count = 0` for both awake and asleep states: staging uses a
single FARGATE provider at weight 100, so `desired_count` alone controls task
capacity. This stable strategy is important because the AWS Terraform provider
marks changes to `aws_ecs_service.capacity_provider_strategy` as
replacement-only. Pilot plan policy fails before apply if an ECS service or
scaling target would be replaced, scaling-target tags would be removed, an
Aether Auth0 resource would be deleted, or a deferred Auth0 surface would be
mutated.

The floor and pilot's stable strategy are not decoration. The `api` service's
`desired_count` is `ignore_changes`d in `modules/ecs` so an apply cannot fight
Application Auto Scaling mid-scale-out; on an already-applied workspace the
scaling target is the only lever that still reaches a running service. So
`asleep` has to set desired count and autoscaling floor to zero. Pilot's
capacity-provider base stays zero in both states; `max_capacity` stays at the
reviewed ceiling. For the full lane, a guaranteed on-demand floor of 1
contradicts a desired count of 0; `scripts/release/check_delivery_topology.py`
rejects `base_count > desired_count`.

The consequence that matters operationally: **an asleep environment owns exactly
the same services, the same roles and the same queues as an awake one.** Waking
is flipping one input, not planning a differently-shaped topology. Staging runs
the same consolidated 2-service shape as `production-lean` — `api` plus
`lean-worker` hosting all eight worker roles — so the packing itself is
rehearsed before production sees it, sized one step down at 1 vCPU / 4 GiB for
the worker.

The shared Auth0 database connection has one `auth0_connection_clients`
Terraform owner because that resource controls the entire enabled-client set.
The pilot state migration moves the Aether resource address and forgets the
old Kyber duplicate with `destroy = false`; it preserves the existing remote
Kyber association without running or provisioning Kyber's deferred operator
workflows.

Before a rehearsal can create a wake plan, it binds the immutable release to
the exact current `main` SHA and verifies the build run, manifest checksum,
staging profile/lane, every packaged SPA/migration/configuration digest, and
the explicit lane identity evidence. It then validates delivery and rehearsal
credentials, assumes the exact `AetherStagingDeploy` role through the staging
GitHub environment, checks live ECR image-pull grants, and verifies the current
ECS task-definition/secret-mount contract. Before wake planning it also verifies
that both live services select the staging DynamoDB cache table, that the table
is active, and that every live task role is allowed all required cache
operations on that table. Pilot also proves that the configured GitHub
credential can safely write and then remove a disposable repository secret—the
same persistence path used only if the post-readiness admin bootstrap is needed.
The preflight's `iam:SimulatePrincipalPolicy` call runs with the deploy-role
session and is covered by the delivery/apply contract, not the separate
`AetherStagingLifecycle` policy manifest.
Any failure blocks wake planning. After Terraform apply, the promotion workflow
repeats the cache-role check against Terraform outputs. After the reviewed wake,
the lifecycle dispatches canonical delivery with that same release run and
checksum; delivery independently verifies the artifact before running its
single migration task, rolling ECS, or publishing static origins. The delivery
job revalidates the awake lease immediately before each static-origin write,
not only before ECS mutations.

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
`deployment_lane` token (`full` or `pilot`). The staging lifecycle defaults to
`pilot` and passes that value into each promotion; the multi-profile
`terraform-promote.yml` dispatch defaults to `full` so non-staging profiles
remain valid, and a direct staging promotion must explicitly select `pilot`.
`full` keeps the existing rehearsal including Kyber/workforce checks. `pilot`
is the complete lean AWS customer
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

The staging Amplify preflight is also race-safe for a merged `main` push. The
five customer-facing apps can auto-start their reviewed-commit builds before
the pilot wrapper reaches its provenance gate, so the gate waits for an active
job only when its commit is exactly the reviewed SHA. It polls for up to 15
minutes, then requires a terminal `SUCCEED` status and the exact commit; an
active job for another commit, a failed build, or a timeout remains a hard
failure. This keeps the process bounded without accepting stale or unverified
artifacts.

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

Staging also retains a separate pre-existing Aurora cluster named
`aether-staging`; it is not the Terraform-created `aether-staging-aurora`
cluster. The one-time `staging-state-reconcile.yml` path accepts only that
exact identifier plus the explicit `IMPORT-LEGACY-STAGING-AURORA` confirmation.
It validates the live cluster and writer identity, imports metadata only, and
does not alter data, credentials, encryption, networking, backups, tags, or AWS
settings. The next ordinary reviewed staging plan must set this legacy
cluster's capacity to min 0 / max 2 with a 300-second idle pause. Its plan gate
rejects creation, deletion, replacement, duplicate ownership, or any unrelated
attribute drift. The reviewed Terraform promotion—not the state import—is what
applies that scale change, then verifies the exact auto-pause configuration on
both the legacy cluster and the canonical Terraform-managed staging cluster.
The scale checks are metadata-only and do not connect to the databases.
Auto-pause removes idle compute charges, but storage
and other non-compute charges continue; open database connections also prevent
automatic pausing.

This is intentional and is the single largest reason staging's budget is USD 25
rather than production-lean's USD 150: paused Aurora instances incur no compute
capacity charge while idle. Storage and other non-compute charges still accrue.
The operational consequence is a **cold start on the first database
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
literally `AETHER-staging`; checks the exact scalable-target set and ownership
tags; sets every service's `--desired-count 0`; registers every matching
scalable target at `--min-capacity 0`; deletes the lease; then re-reads the
cluster to compute residual tasks. Task counts come from the projected
`taskArns[]` list, never the length of the raw `list-tasks` response object,
which is always 1 and once made every run report a phantom residual task.
Conflicting or missing target tags never
produce a false green: the guard still attempts ECS scale-to-zero and task
stopping, while failed autoscaling-floor enforcement remains visible. Missing
tags are repaired only by the reviewed Terraform apply path, which verifies
them after applying.

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
for the exact main integration authority and performs a read-only state
assessment. A clean, unbound legacy app (no manual branches and no live
domain mappings) is bound to the repository and its production `main` branch
in a one-time bootstrap that stops before release. A reviewed administrative
step then restores `status -> main`; the next dispatch deploys the exact merge
SHA and verifies the public `status.olympuslabsml.com` association and its live
CNAME target. If legacy branches or mappings remain, CI fails closed instead
of attempting a domain mutation. Repository-backed runs never delete branches
or call `UpdateDomainAssociation`; they verify the AVAILABLE association and
canonical `main` mapping before release. Squarespace remains authoritative.
A repository-backed status app is updated in place on later runs; it is never
treated as a staging ECS or Terraform mutation. Since Amplify can auto-start
the branch build for the pushed SHA, the workflow reuses an active exact-SHA
job, waits for unrelated active jobs to clear, and starts a release only when
no matching job exists.

Steps, in order, with what each proves:

1. **Exact-artifact delivery.** Before any wake plan is dispatched, the
   lifecycle has verified that the immutable source run is a successful build
   for the exact current `main` SHA, and that its manifest profile/lane,
   checksum, packaged artifacts, and lane evidence match the selected run.
   After the reviewed wake applies and services are ready, it dispatches
   canonical `deploy.yml` with the same immutable source run ID and approved
   manifest checksum. Delivery independently repeats the source and artifact
   verification, acquires the release without rebuilding, and requires its
   backend digest to equal the digest pinned by the reviewed wake plan.
2. **Canonical migrations, ECS rollout, and static publication.** `deploy.yml`
   applies the packaged migration using the exact release image, registers and
   rolls every lane-selected ECS service, waits for readiness and its golden
   path check, and publishes the selected SPA archives to their private S3
   origins. Its deployment evidence is tied to the exact delivery run. Pilot
   publishes Aether only; full also publishes Kyber. The rehearsal does not
   repeat these mutations: it verifies the recorded migration/service rollout,
   checks **every** live ECS service uses the approved image, and compares the
   S3 origin bytes with the approved archives. The public Amplify apps
   (Olympus, Aether, docs, app, and status) are a separate delivery surface;
   their exact-head builds and staging-domain checks belong to the Amplify
   delivery/smoke workflows, not this private S3-origin verification.
3. **Migration evidence.** The canonical delivery must record exactly one
   successful migration task using the approved image. Migration success alone
   does not prove runtime readiness. A prior task used an older image and
   failed when `delivery_jobs` already existed; the current migration adopts
   a pre-existing table only after validating its required columns and creates
   missing indexes idempotently. Canonical delivery now rolls the exact
   manifest-bound main image before this migration runs, so the rehearsal
   cannot migrate with the stale task-definition image that caused that
   failure.
4. **Backend readiness.** The rehearsal checks `/v1/ready` to prove the
   database revision matches the packaged head; `/v1/health` and `/v1/ready`
   must both return 200. A prior rehearsal completed migrations but `/v1/ready`
   returned 503 because the ECS task role lacked table-scoped
   `dynamodb:DescribeTable` for the configured staging cache. That permission
   is now present in the Terraform task-role policy and has been verified in
   the live policy; the all-action, exact-table simulation also runs before
   wake and after Terraform apply. This history is not evidence of a successful
   rehearsal.
5. **First-admin handoff (pilot only).** Only after migration and readiness
   succeed does the lifecycle validate/reuse a working `STAGING_ADMIN_API_KEY`
   or, when absent/stale and the durable database marker is unclaimed, create
   one through the staging-only first-admin route. The helper stores a new key
   as a GitHub repository secret before making the one-time request, then
   verifies `/v1/me` reports admin scope. If an earlier attempt left a claimed
   marker, the status endpoint compares the saved candidate against the marker
   hash without returning either value: only the exact same candidate can
   resume the idempotent request. A different/unverifiable candidate, uncertain
   status, non-authentication error, or authenticated non-admin key fails
   closed; never replace it with a different key. The full lane does not enable
   this route and still requires a pre-existing durable `ak_...` admin key.
6. **Lane-specific identity and static-origin checks.** Pilot checks Aether only
   and explicitly defers Kyber workforce identity and its Google/GCP
   prerequisites. The full lane additionally runs the Kyber workforce
   identity contract and live identity probe, including the API callback
   `https://<api-domain>/v1/kyber/auth/callback`; the Kyber SPA origin remains
   the separate WebAuthn origin. Each selected lane's S3 static origin must
   contain `index.html`. The five public Amplify apps have their own
   delivery/smoke gate; this lifecycle step does not claim to publish or verify
   those Amplify domains. Staging does not attach the production custom domain
   or a production status API URL.

   Before apply, promotion separately verifies that every ECS-mounted
   application secret has an `AWSCURRENT` version and, when canonical Aurora
   exists, its AWS-managed `MasterUserSecret` reports `active`. Terraform
   creates encrypted secret stubs but never invents values. The metadata check
   does not print secret material. Pilot requires the core application secrets,
   first-admin bootstrap token, and four real recurring Stripe test-price
   secrets; Kyber Google credentials are deferred. Full requires the base
   application secrets and Kyber pair, not the pilot-only Stripe price
   secrets. Value-safe checks validate `sk_test_`, `whsec_`, and `price_`
   formats, verify the Stripe test catalog, and use the dedicated
   `AetherStagingSecretPreflight` role. The lifecycle role's only application
   secret exception is `aether/first-admin-bootstrap-token-*`, with KMS decrypt
   constrained to the staging CMK and Secrets Manager encryption context. The
   pilot metadata smoke check uses the read-only `AetherStagingPlan` role; it
   does not broaden the secret-preflight role. After apply,
   `check_staging_task_definition_contract.py` verifies the registered API and
   `lean-worker` task definitions match the selected lane, including pilot
   Stripe mounts and absence of deferred Kyber mounts; a stale revision fails.
7. **Tenant isolation.** The run uses the verified durable staging admin
   key to create two fresh run-scoped tenants and one API key for each: an
   `enterprise` primary tenant (graph Connectivity and ML Prediction are
   gamma-gated) and a `free`, read-only isolation peer.
   The raw keys are masked and held only in the runner environment; they are
   never committed or uploaded. Their `tenant_id` values must differ. The
   primary tenant writes a consent record for a unique subject and reads it
   back; the peer's read of that subject must be refused or return no record,
   and any visible record is a breach that fails the run. (The route is keyed
   by data subject and answers `200 {"consent": null}` for unknown subjects, so
   a bare 200 is not itself a breach.) An unauthenticated `/v1/me` must fail
   closed.
8. **Capability checks.** `scripts/staging_capability_matrix.py --json`,
   `scripts/smoke_test.py` (the tenant key covers data-plane checks; the
   encrypted durable `STAGING_ADMIN_API_KEY` (`ak_` plus 24 alphanumeric
   characters) is supplied only after the post-wake `/v1/me` admin validation,
   then to the two admin diagnostics probes), then explicit probes for
   auth, consent/privacy
   (records, retention manifest, DSR), ingestion (a canonical `page` event for
   a consented subject, which must be reported `accepted`, not merely HTTP
   200), **queue-worker drain**
   (polls analytics for the ingested event for up to 300 s; failure to drain is
   reported as the `lean-worker` execution group not draining — this is the
   check that proves consolidation actually works), graph, analytics, and
   inline ML (`/v1/ml/models` plus the unique in-process `/models` probe,
   since staging runs `remote_ml: false`).
9. **Synthetic-seed exclusion and empty state.**
   `scripts/validate_frontend_data_truth.py`, plus a probe that an unknown
   subject returns no records, plus a scan of the response for the markers
   `demo`, `synthetic`, `sample-tenant`, `lorem`.
10. **Baseline load.** `scripts/load_smoke.py --users 10 --duration 60
   --api-key "$REHEARSAL_TENANT_API_KEY"`, so the load path exercises the same
   authenticated tenant contract as the capability probes.
11. **Failure and retry.** A malformed ingest payload must be a 4xx — a 5xx is a
   server error and a 2xx means it was accepted. The retry probe records a
   consent receipt for its subject, its first write must be accepted, and the
   identical retry must be reported as a duplicate, never a 5xx.
12. **Rollback rehearsal.** Refuses to run outside the `AETHER-staging` cluster.
   Rolls `AETHER-staging-backend` back to the previous task-definition revision,
   waits for stability, asserts the rollback took effect and `/v1/health` is
   200, then restores the current revision and waits again. On the first
   approved revision there is no earlier task definition, so the step records
   `not_applicable` instead of fabricating a rollback; every later revision must
   execute and verify both rollback and roll-forward.
13. **Evidence collection.** ECS service state, log groups, CloudWatch metrics,
    `release.json`, and a cost-model run are collected with required AWS
    permissions. Missing or unreadable evidence is a rehearsal failure; no
    command is allowed to turn an evidence error into a false green.
14. **Tenant cleanup.** Every run-scoped tenant recorded by the bootstrap or
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
for target in "${targets[@]}"; do   # exact service/AETHER-staging/ targets only
  aws application-autoscaling register-scalable-target --service-namespace ecs \
    --scalable-dimension ecs:service:DesiredCount --resource-id "$target" \
    --min-capacity 0
done
```

Only the floor is lowered. `max_capacity` stays at the reviewed ceiling: the
pilot wake policy rejects any ceiling change as autoscaling shape drift, so a
cost stop that clamped it would make the next wake plan unapplyable. An
unreadable autoscaling namespace fails the step rather than leaving a floor
that could revive staging.

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
| `staging-rehearsal-<run_id>` | everything under `artifacts/rehearsal/` — `bootstrap-marker.json`, `registration-marker.json`, `static-origin-verification.txt`, `migrations.txt`, `ready.json`, `tenant.json`, `capability-matrix.json`, `capabilities.json`, `smoke.txt`, `data-truth.txt`, `load.json`, `load.txt`, `rollback.txt`, `ecs-services.json`, `log-groups.json`, `metrics.json`, `release.json`, `cost.txt` | 30 days |
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
artifacts into that layout is a manual release-evidence step. The latest
credentialed full rehearsal completed the migration task, but `/v1/ready`
returned 503 because the ECS task role lacked the staging cache table's
`dynamodb:DescribeTable` permission. That permission is now in the reviewed
Terraform policy and live role policy. Later pilot plan attempts failed before
apply because the old main-branch credential gate required a pre-existing
admin key that the pilot flow only creates after readiness. Lane-aware
credential gating and the post-readiness first-admin handoff are implemented
in the pending change; no successful full rehearsal is recorded yet.

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
