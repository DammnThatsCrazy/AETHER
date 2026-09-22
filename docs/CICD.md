---
title: CI/CD Pipeline — Stages, Gates & SDK Release
slug: operations/cicd
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: stable
since_version: "0.1.0"
source_files:
  - cicd/aether-cicd/README.md
  - cicd/aether-cicd/main.py
  - cicd/aether-cicd/stages/
  - cicd/aether-cicd/quality_gates/
  - .github/workflows/
  - scripts/release/verify_effective_staging_apply_policy.py
  - scripts/release/check_staging_lane_contract.py
  - config/staging_apply_iam_policy.yaml
  - deploy/aws/terraform/modules/secrets/main.tf
  - deploy/aws/terraform/modules/ecr/main.tf
  - deploy/aws/terraform/modules/aurora/main.tf
  - deploy/aws/terraform/modules/kms_credentials/main.tf
canonical_owner: platform@aether
estimated_read_minutes: 15
toc_depth: 3
source_hashes:
  ".github/workflows/": "sha256:164d59496b052dc9c4b79e8745583b2000dbd82baca2620719e28b8c2d5399db"
  "cicd/aether-cicd/README.md": "sha256:ca102c45cda00d0bd46a2fa56456019362e1151e15dc39105345467720c80ca9"
  "cicd/aether-cicd/main.py": "sha256:aa0be4b12e05595a469df83ab97b8a36ab08206029422d2bd5af183e6fb60e48"
  "cicd/aether-cicd/quality_gates/": "sha256:795084ef52b4a288a64549b279677e0d5a66aa030ebb89f662014d78729320a6"
  "cicd/aether-cicd/stages/": "sha256:f26f7a608ed0d1cf1aff849650848b64958eba563c69ccb7f7d120726c767619"
  "config/staging_apply_iam_policy.yaml": "sha256:4a311f675ceb344018a5037f936da7b482d381f5a5628d0f03562ff4628ba802"
  "deploy/aws/terraform/modules/aurora/main.tf": "sha256:e609cdfaaf5d9d384e213edf6f936b0045eac823cc38d432e75db464c8eb14ad"
  "deploy/aws/terraform/modules/ecr/main.tf": "sha256:f8b30aba132a19ae65a39ac0ccafe0a08e35be1cc83d2abaa440414c8f0103e7"
  "deploy/aws/terraform/modules/kms_credentials/main.tf": "sha256:c1f29a39c56575b2a62de519767aa984cb80827644c4fd6ab79d021c53172bc6"
  "deploy/aws/terraform/modules/secrets/main.tf": "sha256:ba27b2bbe46c96631c9787541aa5b1e6c7c1190e88d724c2b1d4b47d35d10098"
  "scripts/release/check_staging_lane_contract.py": "sha256:7005ef21ff872335e729076c6c9e9e1e541e630e138b46589bf84f1985b968fb"
  "scripts/release/verify_effective_staging_apply_policy.py": "sha256:e06d55ce02df622bdf9dc4ae986361d1fcf2292eae9f7133be2219dd7853046a"
---

# CI/CD Pipeline — Stages, Gates & SDK Release

Internal reference for Aether's delivery pipeline.

## Current verification authority

For an ordinary pull request, `.github/workflows/repo-consistency.yml` owns one
blocking status: `verification / disposition`, started once when the PR is
finalized with the `ready_for_review` event. Draft pushes are an accumulation
phase and do not start hosted PR CI. The workflow classifies the
changed paths with the Impact Graph, runs the universal-fast checks, selects
the affected test suites and build workspaces, and publishes one machine-readable
disposition. The old full `make ci-check` PR job has been retired after the
representative selection observation window recorded zero unexplained misses;
it remains available for local, trusted-main, nightly, and release evidence but
does not determine mergeability. Hosted p50/p95 timing is measured separately
by `ci-runtime-report.yml`; its report remains `INSUFFICIENT_SAMPLES` until at
least 20 completed adaptive PR authority runs are available, so local timing
must not be presented as hosted timing evidence.

`repo-health.yml` keeps documentation and PR-size signals advisory on finalized pull requests
and runs a bounded contract/impact/durable-integration authority after merges to
`main`. Its broad Python/backend/TypeScript/E2E/preflight coverage runs nightly or
on explicit dispatch as regression assurance. The hardening
release workflow is invoked manually, from a release event, or by a release-candidate
caller; `make release-gate` is not an ordinary pull-request check. Release validation
therefore evaluates an immutable candidate in the release lifecycle rather than PR
source in the normal critical path.

The suite registry (`config/test_suites.yaml`) carries ownership, component/contract
relationships, lane, isolation, and runtime-budget metadata. Local runtime evidence
can be summarized with `scripts/validate_ci_runtime_budgets.py`; that validator reads
JSON/JSONL files only and makes no hosted telemetry claim.

The classifier now uses the minimal `ci-control` dependency boundary through
`make bootstrap-ci-control`; it does not install the application runtime merely
to resolve changed paths. It emits the typed
`contracts/delivery/verification-execution-plan.schema.json` plan consumed by
the workflow's `universal-fast`, dependency-aware suite matrix, build,
candidate-verification, and `publish-evidence` jobs. Every selected non-universal
check is represented by a registry-owned suite with one dependency profile and
runtime class; an unmapped check blocks plan creation rather than falling back
to an oversized control worker. Root and backend aggregate suites are retained
for regression/release lanes, while ordinary PR impact maps to component suites
and pooled/isolated workers. Node setup, Python extras, and backend image builds
are selected from that same plan; they are not repeated by individual jobs.
Each suite worker writes and uploads a worker-unique evidence filename so the
aggregator can account for every selected suite without artifact-path collisions;
missing selected evidence remains blocking rather than being treated as a partial
pass.
Each selected Node worker installs the lockfile and builds `packages/shared`
before its workspace suite so generated contract twins are available without
requiring a broad application build.

The canonical CI performance policy targets classifier p95 <= 30 seconds,
universal-fast p95 <= 60 seconds, ordinary PR p50 <= 300 seconds and p95 <=
600 seconds, isolated frontend p95 <= 360 seconds, isolated backend p95 <= 420
seconds, moderate cross-component p95 <= 600 seconds, and architecture/control
plane p95 <= 900 seconds. The workflow records classifier, dependency setup,
critical-path, build, candidate, and disposition timing. A breach is surfaced
as `CI_PERFORMANCE_DEGRADED` without initially blocking merge; p50/p95 claims
remain disallowed until at least 20 representative samples exist. Unresolved
paths, unknown profiles/suites, inconsistent build selection, and missing
blocking evidence remain fail-closed, and the existing verification disposition
is still the single ordinary-PR mergeability authority.

Repo Health scopes its concurrency group by event type as well as branch. A
push run therefore cannot cancel the pull request run that supplies the
required PR checks; each result remains attributable to its exact event and
head SHA.

The state-reconciliation workflow validates the checked-in state-access
contract, then uses the protected Terraform apply role because imports and
untaints write the shared state backend. It also runs IAM simulation against
that assumed role before touching state. It normalizes and deduplicates
comma-separated repository inputs,
pre-validates every requested ECR untaint target before any import or state
mutation, and checks both the canonical staging address and the other shared
profiles for duplicate ownership. It also verifies that each canonical staging
address contains the requested repository identity before clearing a taint, so
a stale, already-untainted, or manually moved state entry cannot be repaired
under the wrong name. Duplicate-owner matching is whitespace-tolerant because
`terraform state show` is a human-oriented format. State-reconciliation
membership checks capture the complete `terraform state list` output before
matching addresses; they do not pipe Terraform into `grep -q`, because
`pipefail` can otherwise send `EPIPE` to the Terraform output wrapper and
falsely report an existing address as absent.

When the operator supplies `staging_secret_names`, reconciliation first checks
the exact Secrets Manager names, staging CMK, and `AWSCURRENT` metadata, then
imports only the reviewed Terraform addresses. It never calls
`get-secret-value`; secret materialization remains a separate secure bootstrap.
The reviewed immutable frontend build also requires the Kyber Google client ID
and passes only the public client identifier into the Kyber bundle. The client
secret is backend-only and is mounted from Secrets Manager at task start. The
build and promotion gates fail closed when either required credential is absent,
so a successful build cannot produce a staging backend that immediately dies
from missing workforce identity configuration.
The staging promotion also probes the account plan and fails closed before any
mutation when a Free plan cannot support the reviewed Aurora topology. Its IAM
manifest therefore includes the ECR scan, account-plan read, S3 bucket-level
read, and ELB listener-attribute actions that those preflight checks and
Terraform plan actually call.

The remote plan requires `TF_AMPLIFY_GITHUB_ACCESS_TOKEN` for the five
GitHub-backed Amplify applications. AWS Amplify requires a repository access
token for public and private repositories alike. The workflow rejects an
absent value, the historical placeholder `-`, and values containing whitespace
before it assumes AWS credentials; a real token is consumed only as a sensitive
plan input. The apply job receives the reviewed binary plan and never
re-plans.
`TF_ALERT_EMAIL` is the actionable staging notification endpoint and is set to
`team@olympuslabsml.com`.

Reviewed Terraform promotion pins immutable digests and injects the staging
apply-role ARN only for staging. Inline-ML profiles leave the ML digest empty;
remote-ML profiles must provide one before apply or wake.
The raw secret payload check is deliberately a separate, short-lived
read-only preflight. It assumes `AetherStagingSecretPreflight`, which can read
only the `aether/*` secret prefix and decrypt only the staging Secrets Manager
CMK through its reviewed alias/tag conditions; the plan, deploy, and lifecycle
roles do not receive `secretsmanager:GetSecretValue`. After apply, a
metadata-only ECS task-definition gate proves that the running backend and
worker revisions carry the selected pilot/full lane contract before smoke
proceeds. The pilot smoke gate switches to the existing read-only
`AetherStagingPlan` role for that ECS metadata check rather than widening the
secret-value role. The immutable delivery path performs the same lane check
before cloning a live task definition, closing the gap between a correct
source plan and an old registered task definition still running in ECS.
Before an apply, the promotion workflow parses the reviewed plan for ECR
repositories in every shared-account profile (staging, demo, and preview) and
fails closed when a same-name repository exists outside the reviewed state; it
never deletes or silently imports shared repositories. The
confirmation-gated `Reconcile staging Terraform state` workflow provides the
only recovery path: it accepts the exact reviewed ECR repository names (and/or
the staging target-group ARN), validates that each exists, imports only those
addresses, and requires a fresh reviewed plan before any apply. It cannot
delete, replace, or adopt an unlisted resource. ECR reconciliation also requires
the exact reviewed staging KMS key and verifies that every repository is KMS
encrypted with that key before import. Before assigning ownership, it reads the
staging, demo, and preview state keys and refuses an import if any shared
repository or target group is already owned by another profile.
staging IAM contract is explicit about repository metadata, event targets,
parameter tags, staging Lambda tags, KMS grant/key-tag operations, S3
bucket-level read actions (`GetAccelerateConfiguration`,
`GetBucketRequestPayment`, `GetBucketNotification`,
`GetBucketOwnershipControls`, `ListBucket`), and ELB listener attributes
(`DescribeListenerAttributes`), while CMK policies constrain service use to
the staging account and regional service endpoints.
Role-name assertions are staging-only: every other profile is checked against
its encrypted role ARN without being forced to use a staging role name. The
staging effective-policy check also evaluates each reviewed action against its
resource patterns and conditions, rejects any overlapping explicit Deny, and
rejects attached Allow or NotAction statements that overlap a manifest's
declared forbidden action set. Exact reviewed operations remain allowable when
they are explicitly required by that manifest; a wildcard or broader attached
grant is not. An action name appearing in an unrelated statement is not
sufficient. If a
policy uses a condition operator the checker cannot model, that Deny is
treated as applicable and the preflight fails closed rather than allowing an
unverified apply to proceed, but only after the Deny overlaps a reviewed
resource. Attached Allows must also preserve every mandatory manifest
condition; a broader unconditional Allow is not accepted as equivalent.

The full staging rehearsal also treats its credentials and cleanup as release
gates: the tenant key is reserved for data-plane probes, while the encrypted
admin key is used only for diagnostics and run-scoped tenant administration.
Cleanup must revoke durable keys, verify auth-cache eviction, revoke contained
ingest identifiers, erase all tenant-scoped rehearsal projections, and return a
complete receipt before the workflow can report success. A failure at any of
those boundaries stops before tenant deletion and leaves enough evidence for a
safe retry; billing and immutable security-audit records remain retained by
policy.
The staging ECR collision check runs before any account-level service-linked
role bootstrap, so a rejected repository cannot leave an IAM mutation behind.
The checker also intersects identity policies with any permissions boundary,
normalizes IAM action names case-insensitively, and carries the paired alias
request context into both KMS `CreateAlias` resource checks.

Before a full staging rehearsal can wake compute, the lifecycle workflow runs a
staging-environment preflight. It requires one encrypted, pre-existing
`STAGING_ADMIN_API_KEY` bootstrap credential. The certificate-covered API
hostname and raw ALB name are captured from the reviewed Terraform apply output
after the load balancer exists. Since external DNS is not managed by Terraform,
promotion publishes both without making a completed apply fail on propagation;
the lifecycle performs the fail-closed hostname-to-ALB resolution check before
readiness, the awake lease, and the
primary rehearsal and isolation API keys are generated through the admin
tenant/key routes as run-scoped tenants after wake; they are masked, never
uploaded, and are deleted or deactivated by the always-run cleanup. This removes
the circular requirement for an ALB value
and long-lived test keys before the first apply while keeping the admin
bootstrap credential fail-closed. Plan-only and non-rehearsal actions remain
available without that runtime input, but a full rehearsal fails before
apply-wake rather than waking an environment that cannot be tested. Both the
lifecycle and TTL cleanup paths also fail closed: an absent SSM lease is treated
as already asleep, while an access, throttling, or other deletion error fails
the run so unknown cleanup state cannot be reported as success. The TTL guard
applies the same distinction when reading the lease. A missing lease is the
only benign empty state; read errors are fatal. On the first approved ECS
revision, rollback evidence is recorded as `not_applicable` because there is no
prior revision; subsequent rehearsals must execute and verify rollback and
roll-forward.

## Scope — two different things

`cicd/aether-cicd/` is a **Python demo runner**, not the pipeline. `main.py`
prints a CI → CD → SDK-release model from constants in
`config/pipeline_config.py`; it does not drive GitHub Actions, and
`.github/workflows/ci.yml` does not exist. The branch strategy, six-account
table and eight-stage CI/CD model below come from that reference model and are
labelled as such.

**The workflows in `.github/workflows/` are what actually runs.** Anything that
promotes, deploys or applies is described in
[Delivery workflows](#delivery-workflows--what-actually-runs), and that section
is authoritative wherever the two disagree.

## Reference model — branch strategy

Aether uses GitFlow with six permanent branch types:

| Branch | Purpose |
|--------|---------|
| `main` | Production-ready code; only receives merges from `release/*` and `hotfix/*` |
| `staging` | Pre-production integration; receives from `develop` for staging deploys |
| `develop` | Integration branch for feature work |
| `demo` | Stable demo environment; fed from `staging` on explicit promote |
| `feature/*` | Short-lived feature branches off `develop` |
| `hotfix/*` | Emergency patches off `main`; merged back to both `main` and `develop` |
| `release/*` | Release preparation off `develop`; merged to `main` and `develop` on ship |

## Reference model — AWS accounts

The reference model describes six isolated AWS accounts with placeholder IDs:

| Account | ID | Purpose |
|---------|-----|---------|
| dev | `111111111111` | Developer sandbox; auto-deployed from `develop` |
| staging | `222222222222` | Pre-prod integration; auto-deployed from `staging` |
| production | `333333333333` | Customer traffic; canary-gated deploys from `main` |
| data | `444444444444` | Data plane (ClickHouse, S3, MSK, SageMaker) |
| security | `555555555555` | Security tooling and audit log aggregation |
| demo | `666666666666` | Demo environment; deployed from `demo` branch |

**No such account structure is provisioned.** The live Terraform root targets a
single account and region per workspace, and the three production-class
deployment profiles collide on resource names and therefore *do* require
separate accounts — which have not been provisioned. See
[AWS Deployment](AWS-DEPLOYMENT.md).

## Reference model — CI stages

The eight sequential stages below are the reference model's. Stages 1–3 name
commands the real workflows do run; stages 4–8 and their thresholds are not
enforced by any workflow in `.github/workflows/`.

### 1. Lint / static checks

- `python -m ruff check .` for Python correctness-oriented linting.
- `npm run lint` for TypeScript workspace static checks. The workspace lint scripts intentionally run TypeScript compiler validation so CI does not depend on an unpinned ESLint parser/config package.
- Gate: **0 errors**.

### 2. Type check

- `npm run typecheck` across the TypeScript SDK/operator workspaces.
- Python runtime syntax is validated with `compileall` for the backend, agent layer, and security package.
- Gate: **0 type/syntax errors**.

### 3. Unit tests

- Vitest via `npm test` for TypeScript SDKs and frontends.
- Pytest via `python -m pytest tests/ -n auto --tb=short` for core Python tests; ML coverage uses the registered `services/ml` suite when `services/ml/**` changes.
- Gate: **all tests pass**.

### 4. Integration tests

- Spins up ephemeral Docker Compose stack (Postgres, Redis, Kafka, ClickHouse)
- Runs service-to-service integration suites
- Gate: **all tests green**

### 5. Security scan

- Trivy container vulnerability scan on every built image
- `npm audit --audit-level=critical` on Node packages
- `pip-audit` on Python packages
- Semgrep SAST on application code
- Gate: **0 critical vulnerabilities**

### 6. Build

- Docker images built and pushed to ECR (tagged with the commit SHA)
- The shared `@aether/shared` workspace is compiled before the Aether and Kyber
  frontend builds so their local contract imports resolve deterministically
- TypeScript packages compiled; `packages/web/dist/` populated
- SDK artefacts staged for release (see SDK Release below)
- Gate: **all builds succeed, images < 500 MB compressed**

### 7. E2E tests

- Playwright test suite against a freshly deployed ephemeral environment
- Covers critical user journeys: sign-up, wallet connect, event ingestion, dashboard
- Gate: **all E2E tests green**

### 8. Performance tests

- k6 load test against the ingestion endpoint (1 000 RPS for 60 s)
- Gate: **P99 latency < 200 ms, error rate < 0.1%**

## Reference model — CD stages

The canary and progressive-rollout model below is **not implemented by any
workflow in this repository**. No workflow shifts weighted traffic, and no
workflow applies Terraform as part of a deploy. The real promotion path is
[Delivery workflows](#delivery-workflows--what-actually-runs).

### 1. Staging deploy

ECS service update rolled out to the `staging` account using the commit-SHA image.

### 2. Staging smoke tests

Automated smoke suite hits staging endpoints. Gate: all checks green.

### 3. Canary deploy (5%)

5% of production traffic shifted to the new task revision in the `production`
account. Alarm monitoring begins.

### 4. Canary validation (15 min)

Automated hold: CloudWatch alarms for error rate, latency, and memory are
evaluated every 60 seconds for 15 minutes. Any alarm breach triggers automatic
rollback.

### 5. Progressive rollout

Traffic shifted in stages: 5% → 25% → 50% → 100%. Each step holds for 5 minutes
with the same alarm guard. Automatic rollback on breach at any step.

### 6. Post-deploy

- Cache warm-up tasks run against production
- PagerDuty alert suppression window closed
- Deployment record written to the audit log
- Slack notification sent to `#deploys`

## Delivery workflows — what actually runs

Staging runtime mutation is explicitly authorized: `apply-wake` and
`full-rehearsal` require `confirm_runtime_wake=true`, and the apply job must
carry the exact reviewed Lambda archives alongside the immutable plan. Inline
ML profiles may omit an ML digest; remote-ML profiles may not. A full
rehearsal also requires a live awake lease with sufficient remaining time;
lease validity is rechecked immediately before mutating migration work so an
expired lease cannot start another staging mutation.

Two things get promoted, on two separate paths that must never be conflated: the
**application** (an immutable release bound in `release.json`) and the
**infrastructure** (a reviewed Terraform plan).

The public web layer follows the infrastructure topology but has its own
Amplify build path. `olympus-marketing`, `aether-marketing`, `docs`,
`aether-app`, and `status` are connected to the checked-in monorepo build
configuration; staging reuses the verified `*.staging.olympuslabsml.com`
associations and production adds the reviewed `*.olympuslabsml.com` associations.
The protected tenant and
Kyber artifacts remain part of the immutable release and are published to
their private S3 origins by the staging rehearsal. This keeps Kyber internal
and prevents a public marketing build from being mistaken for an operator
deployment.

| Workflow | Trigger | What it does | Applies Terraform |
|---|---|---|---|
| `deploy.yml` | push to `main`; `workflow_dispatch` for staging or production | Builds the release once and deploys to staging on push or explicit staging dispatch; a staging dispatch may select `delivery_mode=build-only` to publish the verified immutable artifact without touching ECS, which breaks the asleep-staging/release circular dependency. The pilot full-rehearsal wrapper uses that build-only path when no approved release inputs were supplied; the lifecycle workflow accepts only a successful run with a successful immutable-build job. Staging dispatch reuses the successful merged-main integration authority for the exact SHA and safely reuses an already-published immutable backend tag, including a concurrent-publish race with bounded ECR visibility retries. Production promotion is manual and takes the staged run ID plus the approved `release.json` checksum; build-only is rejected for production. Before staging mutation, the deploy job verifies the currently registered task definitions already match the requested full/pilot lane, then registers one immutable task-definition revision per declared service; no rebuild occurs on promotion. The staging path validates `config/staging_application_delivery_iam_policy.yaml` before assuming the deploy role and uses the reviewed `TF_DOMAIN_NAME` fallback when no `ALB_DNS_NAME` repository variable exists. **Not armed without `AWS_DEPLOY_ROLE_ARN` in the selected target environment:** the armed guard and deployment job bind to the same target environment, and when the role is absent the build/deploy jobs skip while `delivery-not-armed` reports that nothing was built or deployed — that is NOT a claim that a release exists. The moment the role is wired, delivery runs exactly as before. | no |
| `amplify-status-production.yml` | push to `main`; `workflow_dispatch` | Waits for the exact main integration authority, binds the public `aether-status` Amplify app to the repository, and deploys the exact main SHA to its `PRODUCTION` `main` branch. The workflow performs a read-only state assessment before binding: a clean, unbound historical app (no branches and no domain mappings) gets a one-time repository bootstrap and stops before release, while any remaining legacy branch or live mapping fails closed for reviewed administrative cleanup. The administrator then restores the canonical `status -> main` domain mapping and dispatches the workflow again. Repository-backed runs never delete branches or call `UpdateDomainAssociation`; they verify the AVAILABLE association maps exactly once to `main`, deploy the exact commit, and verify the live CNAME target. Because repository auto-build can already have an active job for the pushed SHA, the workflow reuses that exact-commit job, waits out unrelated active branch jobs, and starts a release only when needed. Squarespace remains authoritative. | no |
| `infrastructure.yml` | PR finalization (`ready_for_review`) / push to `main` / dispatch on `deploy/aws/**` | Provider-mocked configuration plan for all six selectable profiles (four cloud + demo/preview ephemeral); OIDC remote plan per cloud profile when the shared credential set exists (the ML image digest is additionally required only by production-scale and enterprise-isolated); ephemeral-class is deliberately excluded from remote-plan; plan-policy and cost-model validation of the resulting plan JSON. | **no — never** |
| `terraform-promote.yml` | `workflow_dispatch` only | Produces a reviewed, checksum-bound binary plan, and applies exactly that plan. Backend digests are always required; ML digests are required only for production-scale and enterprise-isolated, and are optional for staging, production-lean, demo, and preview when remote ML is disabled. | **yes — the only path** |
| `staging-lifecycle.yml` | `workflow_dispatch` | Wake / validate / sleep / full rehearsal. Dispatches `terraform-promote.yml` for every mutation and independently re-verifies the reviewed plan first. Each handoff uses the exact run URL returned by GitHub and fails closed if no run ID is returned; it never guesses from a concurrent-run watermark. Dispatching jobs retain `actions: write` and check out the workspace before invoking `gh`; read-only jobs cannot perform the handoff. `plan-wake` is plan-only and requires only the Terraform plan credentials; lifecycle credentials are required for inspection, wake, or sleep actions. A full rehearsal accepts a successful immutable delivery or build-only run, verifies that the run contains a successful `Build immutable release once` job, binds its `release.json` to the intended merged-main SHA, arms the bounded lease before apply, re-assumes the lifecycle role after the protected promotion wait, preserves the original lease anchor and extension count when refreshing after readiness, revalidates the lease before every mutating phase, publishes and verifies the exact AETHER/Kyber SPA archives, and cleans only a secret-free, run-scoped registration tenant marker. | no (delegates) |
| `staging-state-reconcile.yml` | `workflow_dispatch` with explicit staging import confirmation | Reconciliation for an existing staging target group and/or the four reviewed Terraform ECR repositories. Requires an approved immutable backend digest, `IMPORT-STAGING`, exact target/repository validation, the reviewed staging ECR KMS key for KMS-encrypted repositories, all required root-module URL/certificate/alert inputs, and the Auth0 provider environment used by ordinary remote plans; those credentials remain runner environment variables and never enter Terraform state or plan variables. If a repository exists at one unambiguous legacy staging address, the workflow validates all import prerequisites and every candidate status before adopting it with a state-only move to the canonical module address; it records the complete adoption set before moving anything, rejects tainted or otherwise non-managed legacy instances, treats an already-canonical healthy entry as a verified retry no-op, and fails closed on ambiguous duplicate ownership or demo/preview ownership. It also has a separate, confirmation-gated `untaint_ecr_repository_names` path for repositories already at the canonical staging address whose reviewed before/after attributes are identical but were left tainted by an interrupted replacement; that path verifies the live repository against the Terraform-managed KMS key in staging state, uses Terraform's top-level `untaint` command, and always requires a fresh reviewed plan. An explicitly confirmed `migrate_legacy_secret_kms=true` with `MIGRATE-STAGING-SECRETS` re-encrypts an allowed legacy AWS-managed-key secret under the reviewed staging CMK by metadata-only API calls; it never reads or changes plaintext. Aurora and DynamoDB monitoring are enabled with static profile decisions, so an unrelated state import never derives Terraform resource cardinality from unresolved resource IDs. Temporary local state snapshots are removed in one exit cleanup path. A fresh reviewed plan is required after any state change. The pre-existing `aether-backend` repository is intentionally immutable AES-256 because ECR encryption cannot be changed after creation; the other staging repositories remain KMS-encrypted. It never deletes or applies infrastructure. | no (state reconciliation only) |
| `staging-ttl-guard.yml` | hourly schedule; dispatch | Enforces the staging awake lease. Runs no Terraform at all; it can scale ECS to zero and lower the ECS autoscaling floor, which can only reduce running compute. **Not armed without `AWS_STAGING_LIFECYCLE_ROLE_ARN`:** when the role is absent the guard has no credential to read the lease or enforce the TTL, reports it is a NO-OP and exits green — staging may still be running and will NOT be guarded; that is NOT a claim that staging is asleep. The moment the role is wired it enforces exactly as before, fail-closed in both directions. | no |
| `ephemeral-ttl-guard.yml` | hourly schedule; dispatch | Fail-closed TTL guard for the demo/preview ephemeral profiles. Reads the SSM lease at `/aether/{profile}/{env}/lifecycle/expires-at` (written by `ephemeral_env.py provision`) and ends the run red when the lease is missing or expired; enforcement is the operator-run `ephemeral_env.py teardown` (scale-to-zero + floor-zeroing + lease removal). Runs no Terraform. **Not armed without `AWS_EPHEMERAL_LIFECYCLE_ROLE_ARN`:** when the role is absent the guard has no credential to read the lease or trip the TTL, reports it is a NO-OP and exits green — demo/preview environments may still be running and will NOT be guarded; that is NOT a claim that demo/preview are asleep. The moment the role is wired it enforces exactly as before, fail-closed. | no |

| `repo-consistency.yml` | PR finalization (`ready_for_review`) / push to `main` | Classifies changed paths with the verification router, builds the Impact Graph-selected workspaces in dependency order, binds the selected workspace archive and any selected backend image into one immutable candidate, verifies and materializes that candidate in the consumer job, executes the universal and affected verification checks, and publishes the single blocking `verification / disposition` evidence. Draft pushes do not start this workflow. The broad `make ci-check` job is intentionally absent from the PR path after the completed selection observation window. | no |
| `production-status.yml` | 12-hourly schedule; dispatch | `scripts/production_status.py --strict` + readiness scorecard artifact. | no |
| `production-equivalent-ci.yml` | PR finalization (`ready_for_review`) / push / schedule / dispatch | Runs a cheap Impact Graph classifier for every triggered event. On finalized PRs it provisions the Postgres + Redis real stack only for persistence-impacting backend/infrastructure changes, production-equivalent tests, or unresolved paths. Pushes to `main`, nightly runs, and explicit dispatch retain full real-stack coverage. The lane remains non-blocking and is not a required merge check. | no |

Staging delivery and lifecycle workflows carry the same explicit
`deployment_lane` token (`full` or `pilot`) through the immutable release,
reviewed Terraform plan/apply, wake/sleep lifecycle and smoke gate. The
canonical profile remains `staging` for both lanes. `full` retains all existing
rehearsal and Kyber/workforce gates; `pilot` keeps the complete AWS-hosted
Aether customer path and fail-closed Stripe/runtime checks while deferring only
Kyber operator/workforce identity and GCP/Google hosting or credentials. A pilot
path cannot proceed until the required Stripe ECS/bootstrap wiring and real
test price secrets are present.

The reviewed-promotion credential boundary is intentional: a `plan` action
requires only the plan role and read-only planning inputs. The apply role is
required separately by the protected `apply` job immediately before mutation,
so a plan-only staging rehearsal can validate infrastructure without granting
or requiring mutation credentials.

### Infrastructure planning is not applying

`infrastructure.yml` **never applies Terraform.** The `apply-production-lean`
job that auto-applied on every push to `main` has been **deleted**. What is left
on the `main` branch path is `require-production-credentials`, which gates
**promotability**: a commit is only dispatchable for promotion if its
main-branch run proved the complete remote-plan credential set exists and all
four profiles produced a credentialed, policy- and cost-validated remote plan.
Without that job a commit could land on `main` with every remote plan silently
skipped and still be dispatched for promotion.

**Not armed without the remote-plan credential set.** Pushes and PR
finalization keep the credentialed remote-plan lane held; they do not claim that
a live plan exists. An explicit remote-plan dispatch must provide the exact
immutable backend digest and commit SHA and must have the complete credential
set. Missing or malformed inputs fail closed before any AWS or Terraform work,
while the provider-mocked configuration plan remains available for repository
evidence.

The two evidence layers it publishes are not interchangeable:

1. each finalized infrastructure-impact PR runs a provider-mocked configuration plan against the real root
   module, provider schemas and checked-in `profiles/*.tfvars`, publishing an
   immutable `terraform-configuration-plan-*` artifact — no remote state, no
   live provider API;
2. with the complete secret set, a separate OIDC job runs an
   environment-authoritative plan against an isolated remote-state key,
   publishing `terraform-remote-plan-*` plus the plan-policy report, the
   canonical resource inventory and the cost-model report.

Reviewers must distinguish the two and read the second before promotion.
Neither proves that an environment has been applied.

### Reviewed Terraform promotion

`terraform-promote.yml` is `workflow_dispatch`-only, so no push, tag, schedule
or path trigger can reach an apply. Apply consumes the exact binary plan the
plan job produced and **never re-plans**. It refuses unless all of the following
hold: the plan digest matches the dispatched checksum and its recorded
`sha256sum` manifest; the reviewed profile matches the dispatched profile; the
state key is `profiles/<profile>/terraform.tfstate`; the recorded state bucket
and lock table match the apply backend; the checked-out `HEAD` is
the plan's **own recorded commit** rather than the dispatch ref; the installed
Terraform version equals the recorded one; `sha256(.terraform.lock.hcl)` equals
the digest captured before `init`; and the plan is inside its **24-hour**
validity window. The policy and cost validators are re-run at the reviewed
commit, because the reports in the artifact are evidence, not proof.

Approval is intended to be per profile: the apply job binds to
`staging-terraform`, `production-lean-terraform`, `production-scale-terraform`
or `enterprise-terraform`, so staging cannot borrow production's reviewers.
The live repository currently defines only `staging` and `staging-terraform`,
with no protection rules; the non-staging environments and their credentials
must be provisioned before those profiles can be promoted. An empty environment
created by a workflow reference is not approval and is not a credentialed
promotion path.

`staging_state` (`awake` | `asleep`) is a **plan-time** input, recorded next to
the plan so a reviewer sees which shape was approved; an apply cannot reshape
the stored plan.

The pilot wrapper treats `plan-sleep` and `apply-sleep` as cleanup actions. It
keeps the contract job and canonical authority dispatch, but skips credential,
secret-payload and Amplify readiness checks that require application values or
current app artifacts. A direct apply never trusts its requested
`staging_state` input as a preflight bypass: only the explicit
`secret_preflight_required=false` sleep flag can bypass that gate, and the
reviewed plan artifact must independently record `staging_state=asleep`.

The staging apply handoff has explicit preflight contracts. The staging
workflow validates its reviewed IAM manifest and ensures the ECS service-linked
role is visible before capacity-provider changes. Other profiles remain
blocked from this bootstrap until they have their own reviewed IAM contract.
The maintenance target-group ARN is optional on the apply dispatch: when it is
omitted, `terraform-promote.yml` adopts the exact ARN recorded in the verified
plan artifact; a caller-supplied ARN must match that artifact or the apply is
rejected. This keeps lifecycle dispatches from losing a plan input while
the maintenance-target validation runs only when the reviewed plan actually
replaces the staging backend target group; ordinary existing backend ARNs are
not treated as maintenance targets, preserving the reviewed-plan boundary.
The staging collision guard is likewise action-aware: it checks for an
unmanaged `aether-staging-backend` only when the reviewed plan creates that
target group; update plans keep the existing managed target without a false
collision failure.
The apply path also checks Auth0 management credentials and
required scopes when Auth0 resources are in the plan, and rejects an
unmanaged deterministic staging target group instead of creating a same-name
replacement. If reconciliation is needed, use the import-only
`staging-state-reconcile.yml` workflow and produce a new reviewed plan. These
checks are intentionally fail-closed and run before Terraform mutation; they
do not grant broad IAM permissions or wake staging on their own. Service-linked
role creation is idempotent only for AWS's explicit already-present responses;
permission and throttling errors remain failures. Auth0 tokens with malformed
or non-string scope claims are likewise rejected rather than treated as a
successful preflight.

The Terraform workflows pass `TF_AUTH0_DOMAIN` both as the non-secret
`TF_VAR_auth0_domain` root input used by the Amplify runtime configuration and
as `AUTH0_DOMAIN` for the Auth0 provider. The management client ID and secret
remain runner environment variables; they are never placed in Terraform
variables, plan artifacts or state.

The immutable delivery workflow keeps repository variables as optional
overrides for the packaged Aether and Kyber SPAs. When those variables are not
configured, it derives the Auth0 domain and API/WebSocket origins from the
reviewed Terraform secret inputs (`TF_AUTH0_DOMAIN` and `TF_DOMAIN_NAME`) and
uses the canonical API audience. This prevents a release build from silently
embedding empty identity or endpoint configuration while preserving an
explicit override path for a later environment-specific release train.

For staging, the same delivery job simulates the live `AetherStagingDeploy`
permissions for ECR authorization and the exact immutable backend image
pull/publish operations before Docker authentication or image build begins.
This catches drift in the externally attached IAM policy at the role boundary,
including the `ecr:GetDownloadUrlForLayer` permission required by the
published-image runtime validation, before a release job consumes runner time.

### Deployment gates

```bash
make deployment-profile-gate      # every profile gate that needs no AWS credentials
make resolved-feature-flags        # explicit staging and production-lean flag manifests
make deployment-readiness-score   # three-column readiness scorecard
make collect-deployment-evidence  # materialise release-evidence/ + checksum
```

`deployment-profile-gate` chains `validate-profile-config`,
`validate-cost-policy`, `validate-cost-policy-terraform`,
`validate-delivery-topology`, `validate-terraform-profile-policy`,
`validate-cost-model`, `test-plan-policy`, `test-runtime-topology`,
`test-workflow-controls`, `test-cost-model`, `test-staging-lifecycle` and
`deployment-readiness-score`, in that order — the two plan targets write the
artifacts the scorecard later reads. `make test-terraform-profiles` runs
`terraform validate` plus the provider-mocked per-profile plan tests and needs a
local Terraform binary.

`make test-workflow-controls`
(`tests/unit/test_release_workflow_controls.py`) is the structural guard on all
of the above: no automatic apply, no false-green, reviewed-plan integrity.
The reviewed-plan sanitizer also removes sensitive root-variable values when a
provider embeds or URL-encodes them inside a larger resource string, and
redacts intrinsically credential-bearing provider fields such as
`access_token` even when a provider transforms the value without preserving
Terraform's sensitivity mask. It retains only the values consumed by the plan
policy gate.

### Frontend visual-system guardrail

`make frontend-branding` (also exposed as `npm run
validate:frontend-branding`) runs the lightweight static guard for the
deliberately migrated identity seams: the Aether shell mark and navigation,
Kyber navigation/top bar, and central provider-mark renderers. It rejects the
retired raw navigation glyph paths, feature-local provider SVG or asset maps,
and non-token motion/elevation additions in those surfaces. The guard is
intentionally narrow: it protects completed migrations without turning
unrelated legacy routes into a false CI block. Any temporary exception is an
exact path-and-rule entry with a human-readable reason and is reported by the
validator; the current migration has none. The canonical contracts and
component usage are documented in [`docs/brand-system/`](brand-system/README.md).

## Quality gates reference

| Gate | Threshold | Stage |
|------|-----------|-------|
| Line coverage | ≥ 90% | Unit tests |
| Lint errors | 0 | Lint |
| Type errors | 0 | Type check |
| Critical CVEs | 0 | Security scan |
| E2E pass rate | 100% | E2E tests |
| P99 latency | < 200 ms | Performance |
| Error rate | < 0.1% | Performance / Canary |
| Image size | < 500 MB | Build |

These thresholds live in `cicd/aether-cicd/quality_gates/`, which is part of the
reference model — they are not enforced by any workflow in
`.github/workflows/`. The normal pull-request gate that actually blocks a merge
is the `verification / disposition` status published by
`repo-consistency.yml`; the required-check catalog in
`config/required_release_checks.yaml` governs path-scoped SDK checks and
release-only evidence, and is validated by `make validate-required-release-checks`.

## SDK release

SDK publication is a manual `workflow_dispatch` run of
`.github/workflows/publish-sdk.yml`, which takes an explicit version string,
bumps every package manifest, and then fans out per registry:

The bump covers more than manifests: `scripts/bump-sdk-version.sh` rewrites the
SDK runtime constants (web, React Native, Android, iOS), the loader's own
`LOADER_VERSION` in `packages/web/src/loader/bootstrap.ts`, and the backend
mirror `CANONICAL_SDK_VERSION` in
`services/backend/services/sdk_distribution/versions.py`. The loader and backend
copies exist because each is bundled or deployed separately from the package
manifests, and the release then runs `scripts/validate_sdk_release_alignment.py`,
which pins all of them against the canonical version. That check runs under
`set -euo pipefail`, so a bump that missed any surface fails the release rather
than publishing a mislabelled install.

| Platform | Registry | Job | Version authority |
| --- | --- | --- | --- |
| Web (`packages/web`) | npm (`@aether/web`) | `publish-npm` | `packages/web/package.json` |
| React Native (`packages/react-native`) | npm (`@aether/react-native`) | `publish-npm` | `packages/react-native/package.json` |
| iOS (`packages/ios`) | CocoaPods (`AetherSDK`) | `publish-cocoapods` | `AetherSDK.podspec` |
| Android (`packages/android`) | GitHub Packages, Maven (`com.aether:sdk-android`) | `publish-android` | `gradle.properties` |
| Web CDN (`packages/web`) | `cdn.aether.network` | `publish-cdn` | `packages/web/package.json` |

`publish-cdn` runs after `publish-npm`, because npm is the registry of record and
the CDN is a delivery mirror of the same build. It derives the CDN layout and the
version manifests from `packages/web/package.json` — never a hand-written
version — via `scripts/release/generate-sdk-cdn-manifest.mjs`, then validates the
staged tree with `scripts/release/verify-cdn-layout.mjs` before uploading
anything. The upload is fail-closed on the `AWS_CDN_ROLE_ARN` and
`AETHER_SDK_CLOUDFRONT_DISTRIBUTION_ID` secrets.

Cache policy is split by mutability: `v1.js` (max-age 300) and
`sdk/manifests/web/latest.json` (max-age 60) are mutable and are the only two
paths invalidated on release; version-pinned bundles and loaders under
`sdk/<version>/` and `sdk/v<major>/` are immutable and long-cached, so pinned
installs keep resolving after a newer release.

Two hash formats are published deliberately and must not be unified:
`downloads.*Hash` is a bare hex SHA-256, which is what `aether-loader.ts`
computes and compares byte-for-byte before evaluating a fetched bundle, while
`integrity.sri` is `sha384-<base64>` Subresource Integrity for callers pinning
the immutable versioned bundle. The stable `/v1.js` snippet deliberately
advertises no `integrity` attribute: its bytes change on every loader release, so
a pinned hash would break every installed snippet.

`.github/workflows/sdk-release-validation.yml` runs the distribution wiring gates
(`scripts/validate_sdk_distribution_artifacts.py`, `npm run verify:artifacts
--workspace=packages/web`, and the loader artifact presence check) on SDK-scoped
pull requests.

## Hotfix procedure

1. Branch off `main`: `git checkout -b hotfix/description main`
2. Apply the fix and increment the patch version.
3. Open a PR targeting `main`. The adaptive `verification / disposition` gate
   runs universal-fast checks plus the affected suites/builds; the broad full
   gate remains a local/trusted-main/nightly/release command, not a PR job.
4. On merge, the bounded main-integration workflow runs; the CD pipeline
   executes the full canary rollout when its deployment conditions are met.
5. Immediately after merge to `main`, open a second PR to merge the hotfix into
   `develop` to keep branches in sync.

## Repo consistency gate

In addition to the eight deploy-oriented stages above, a dedicated
**Repo Consistency** workflow (`.github/workflows/repo-consistency.yml`)
publishes the blocking `verification / disposition` status when a PR is
finalized (`ready_for_review`) and on pushes to `main`. It enforces:

- version alignment (`pyproject.toml` is canonical)
- generated docs freshness (`docs/_generated/` diff check)
- docs sync freshness (`REPO-INDEX.md`, `AUTOMATION.md`)
- docs frontmatter validity
- source-linked docs drift (`--strict` mode)
- contract / event / consent alignment
- SDK release alignment
- Impact Graph selection, affected build artifacts, and Python/Node checks
  justified by the changed paths
- npm lockfile integrity + TypeScript build/test for selected workspaces
- Python tests for selected suites

The legacy full `make ci-check` PR job was retired after the representative
hosted observation window. It remains the canonical local and release-candidate
validation command, but it is not a second PR merge authority or a PR job. This gate is
separate from `repo-health.yml` and uses the single orchestrator script
(`scripts/repo_doctor.py`) so the same command works locally
(`make repo-doctor`) and in release validation (`make ci-check`).

## Production status routine

A scheduled **Production Status** workflow
(`.github/workflows/production-status.yml`) runs
`scripts/production_status.py --strict` every 12 hours and on manual
dispatch. It re-verifies the live consistency gates (version alignment,
docs drift, contract alignment, SDK alignment), checks that required
guardrail artifacts exist, and publishes the readiness scorecard +
blocker list as a JSON build artifact. It requires no secrets and no
external services. The same routine runs locally via
`make production-status` (advisory) and `make release-gate`
(repo consistency in CI mode + strict production status).

## Smart contract static analysis

`.github/workflows/smart-contract-analysis.yml` runs Slither static analysis on
pushes to `main`, manual dispatch, and PR finalization (`ready_for_review`)
when `contracts/smart-contracts/` is touched. Draft pushes do not start it.
Requires Slither to be installed (CI installs it via pip). Results are uploaded
as an artifact. The pre-audit checklist at
`scripts/smart_contract_audit_prep.py` runs 9 checks (oracle role, reward
enforcement, nonce protection, etc.) and must pass 9/9 before external audit.

## Adding a real gate

1. Add the check as a script under `scripts/` (or `scripts/release/` if it is
   release evidence) and give it a `make` target.
2. Wire the target into the appropriate aggregate: `make ci-check` for repo
   consistency, `make deployment-profile-gate` for deployment-profile
   enforcement, `make release-gate` / `make founding-tenant-release-gate` for
   release readiness.
3. Invoke it from the workflow that must block on it, and add it to
   `config/required_release_checks.yaml` if it is a required check.
4. Document it here and in the relevant operations page.

Adding a stage class under `cicd/aether-cicd/stages/` changes the reference
model's printed output and gates nothing.
