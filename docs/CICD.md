---
title: CI/CD Pipeline — Stages, Gates & SDK Release
slug: operations/cicd
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: stable
since_version: "8.8.0"
source_files:
  - cicd/aether-cicd/README.md
  - cicd/aether-cicd/main.py
  - cicd/aether-cicd/stages/
  - cicd/aether-cicd/quality_gates/
  - .github/workflows/
canonical_owner: platform@aether
estimated_read_minutes: 15
toc_depth: 3
last_synced_commit: "b9a5cd71"
---

# CI/CD Pipeline — Stages, Gates & SDK Release

Internal reference for Aether's delivery pipeline.

Reviewed Terraform promotion pins immutable digests and injects the staging
apply-role ARN only for staging. Inline-ML profiles leave the ML digest empty;
remote-ML profiles must provide one before apply or wake.

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
- Pytest via `python -m pytest tests/ -n auto --tb=short` for core Python tests; ML tests run when `ML Models/**` changes.
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

| Workflow | Trigger | What it does | Applies Terraform |
|---|---|---|---|
| `deploy.yml` | push to `main`; `workflow_dispatch` for production | Builds the release once, deploys to staging on push; production promotion is manual and takes the staged run ID plus the approved `release.json` checksum. Registers one task-definition revision per declared service; no rebuild on promotion. **Not armed without `AWS_DEPLOY_ROLE_ARN`:** when the role is absent the build/deploy jobs skip and a `delivery-not-armed` job reports that nothing was built or deployed — that is NOT a claim that a release exists. The moment the role is wired, delivery runs exactly as before. | no |
| `infrastructure.yml` | PR / push to `main` / dispatch on `AWS Deployment/**` | Provider-mocked configuration plan for all six selectable profiles (four cloud + demo/preview ephemeral); OIDC remote plan per cloud profile when the full credential set exists (ephemeral-class is deliberately excluded from remote-plan); plan-policy and cost-model validation of the resulting plan JSON. | **no — never** |
| `terraform-promote.yml` | `workflow_dispatch` only | Produces a reviewed, checksum-bound binary plan, and applies exactly that plan. Backend digests are always required; ML digests are required only for production-scale and enterprise-isolated, and are optional for staging, production-lean, demo, and preview when remote ML is disabled. | **yes — the only path** |
| `staging-lifecycle.yml` | `workflow_dispatch` | Wake / validate / sleep / full rehearsal. Dispatches `terraform-promote.yml` for every mutation and independently re-verifies the reviewed plan first. Dispatching jobs retain `actions: write` and check out the workspace before invoking `gh`; read-only jobs cannot perform the handoff. `plan-wake` is plan-only and requires only the Terraform plan credentials; lifecycle credentials are required for inspection, wake, or sleep actions. | no (delegates) |
| `staging-state-reconcile.yml` | `workflow_dispatch` with explicit staging import confirmation | Import-only reconciliation for an existing staging target group. Requires an approved immutable backend digest, `IMPORT-STAGING`, exact `aether-staging-backend` ARN validation, all required root-module URL/certificate/alert inputs, and a fresh reviewed plan after state changes. It refuses duplicate ownership and never deletes or applies infrastructure. | no (state import only) |
| `staging-ttl-guard.yml` | hourly schedule; dispatch | Enforces the staging awake lease. Runs no Terraform at all; its only action is an ECS scale-to-zero, which can only reduce running compute. **Not armed without `AWS_STAGING_LIFECYCLE_ROLE_ARN`:** when the role is absent the guard has no credential to read the lease or enforce the TTL, reports it is a NO-OP and exits green — staging may still be running and will NOT be guarded; that is NOT a claim that staging is asleep. The moment the role is wired it enforces exactly as before, fail-closed in both directions. | no |
| `ephemeral-ttl-guard.yml` | hourly schedule; dispatch | Fail-closed TTL guard for the demo/preview ephemeral profiles. Reads the SSM lease at `/aether/{profile}/{env}/lifecycle/expires-at` (written by `ephemeral_env.py provision`) and ends the run red when the lease is missing or expired; enforcement is the operator-run `ephemeral_env.py teardown` (scale-to-zero + floor-zeroing + lease removal). Runs no Terraform. **Not armed without `AWS_EPHEMERAL_LIFECYCLE_ROLE_ARN`:** when the role is absent the guard has no credential to read the lease or trip the TTL, reports it is a NO-OP and exits green — demo/preview environments may still be running and will NOT be guarded; that is NOT a claim that demo/preview are asleep. The moment the role is wired it enforces exactly as before, fail-closed. | no |

| `repo-consistency.yml` | PR / push to `main` | `make ci-check`, including documentation consistency, contract checks, and the targeted frontend-brand guardrail. | no |
| `production-status.yml` | 12-hourly schedule; dispatch | `scripts/production_status.py --strict` + readiness scorecard artifact. | no |
| `production-equivalent-ci.yml` | PR / push / dispatch | Boots Postgres + Redis service containers, applies the full Alembic graph to a **fresh** database (`alembic upgrade head` → single head), and runs real-pool ingestion tests against the real stack: a round-trip smoke test (M1) plus idempotency/concurrency tests (M2) that prove concurrent `ingest_many` of the same key is exactly-once via the real UNIQUE index + `ON CONFLICT`, plus measurement/attribution repo tests (M4) exercising `conversion_repo`/`spend_repo`/`attribution_run_repo` real ON CONFLICT, tenant-scope, FX-provenance round-trip, and the single-active-run invariant — properties the in-memory (`AETHER_ENV=local`) dict fallback gets "right" for free without proving (that path never runs Alembic). **Non-blocking** (not a required check); real-stack tests skip without `DATABASE_URL`. | no |

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

**Not armed without the remote-plan credential set.** When the credential set
is absent (a credential-less repository), `require-production-credentials`
reports that it is a NO-OP — the commit is explicitly **NOT** promotable — and
passes green, so a credential-less `main` is not permanently red. The job
re-arms and fails closed on plan/remote-plan results the moment the full
credential set is wired. The notice is the opposite of a promotability claim;
it states that promotion is impossible until credentials exist.

The two evidence layers it publishes are not interchangeable:

1. every PR runs a provider-mocked configuration plan against the real root
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
state key is `profiles/<profile>/terraform.tfstate`; the checked-out `HEAD` is
the plan's **own recorded commit** rather than the dispatch ref; the installed
Terraform version equals the recorded one; `sha256(.terraform.lock.hcl)` equals
the digest captured before `init`; and the plan is inside its **24-hour**
validity window. The policy and cost validators are re-run at the reviewed
commit, because the reports in the artifact are evidence, not proof.

Approval is per profile: the apply job binds to `staging-terraform`,
`production-lean-terraform`, `production-scale-terraform` or
`enterprise-terraform`, so staging cannot borrow production's reviewers.

`staging_state` (`awake` | `asleep`) is a **plan-time** input, recorded next to
the plan so a reviewer sees which shape was approved; an apply cannot reshape
the stored plan.

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

### Deployment gates

```bash
make deployment-profile-gate      # every profile gate that needs no AWS credentials
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
`.github/workflows/`. The gates that actually block a merge are
`repo-consistency.yml` (`make ci-check`) and the required-check catalog in
`config/required_release_checks.yaml`, validated by
`make validate-required-release-checks`.

## SDK release

When a `release/*` branch is merged to `main`, the SDK release sub-pipeline fires
alongside the service deploy:

| Platform | Registry | Trigger |
|----------|----------|---------|
| Web (`packages/web`) | npm (`@aether/web`) | Version bump in `package.json` |
| iOS (`packages/ios`) | CocoaPods (`AetherSDK`) | Version bump in `AetherSDK.podspec` |
| Android (`packages/android`) | Maven Central (`network.aether:sdk`) | Version bump in `build.gradle` |
| React Native (`packages/react-native`) | npm (`@aether/react-native`) | Version bump in `package.json` |

The release script (`cicd/aether-cicd/scripts/release_sdk.py`) validates that the
version in the manifest matches the git tag before publishing.

## Hotfix procedure

1. Branch off `main`: `git checkout -b hotfix/description main`
2. Apply the fix and increment the patch version.
3. Open a PR targeting `main`. CI runs the full 8-stage suite.
4. On merge, the CD pipeline executes the full canary rollout.
5. Immediately after merge to `main`, open a second PR to merge the hotfix into
   `develop` to keep branches in sync.

## Repo consistency gate

In addition to the eight deploy-oriented stages above, a dedicated
**Repo Consistency** workflow (`.github/workflows/repo-consistency.yml`)
runs `make ci-check` on every PR and push to `main`. It enforces:

- version alignment (`pyproject.toml` is canonical)
- generated docs freshness (`docs/_generated/` diff check)
- docs sync freshness (`REPO-INDEX.md`, `AUTOMATION.md`)
- docs frontmatter validity
- source-linked docs drift (`--strict` mode)
- contract / event / consent alignment
- SDK release alignment
- npm lockfile integrity + TypeScript build/test
- Python tests

This gate is separate from `repo-health.yml` and uses the single
orchestrator script (`scripts/repo_doctor.py`) so the same command
works locally (`make repo-doctor`) and in CI (`make ci-check`).

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

`.github/workflows/smart-contract-analysis.yml` runs Slither static analysis on every push and PR that touches `Smart Contracts/`. Requires Slither to be installed (CI installs it via pip). Results are uploaded as an artifact. The pre-audit checklist at `scripts/smart_contract_audit_prep.py` runs 9 checks (oracle role, reward enforcement, nonce protection, etc.) and must pass 9/9 before external audit.

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
