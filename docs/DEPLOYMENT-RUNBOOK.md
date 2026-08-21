---
title: Deployment Runbook
slug: operations/deployment-runbook
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 10
---

# Deployment Runbook

Operational steps to deploy and roll back Aether/Kyber.

Two things are being deployed and they travel on separate paths:

- **The application** — an immutable release (backend image by digest, static
  SPA archives, migration archive, runtime configuration) bound in
  `release.json` and promoted by `.github/workflows/deploy.yml`.
- **The infrastructure** — a Terraform plan promoted by
  `.github/workflows/terraform-promote.yml`, which is the **only** path that
  applies Terraform.

Never conflate them. A release promotion changes what runs; a Terraform
promotion changes what exists.

## Artifacts

- Immutable backend image by digest, static Aether and Kyber archives, migration
  archive, and runtime configuration are bound in `release.json`.
- CI build/push: `.github/workflows/deploy.yml`. A push to `main` builds once
  and targets staging only. Production promotion is manual and requires the
  staged workflow-run ID plus the approved release-manifest checksum.
- Local/staging stack: `docker-compose.yml` (+ profiles) and
  `deploy/legacy-staging/{bootstrap.sh,docker-compose.staging.yml,kafka_topics.sh}`.

## Pre-deploy checklist

1. Required secrets present in the secret manager (`JWT_SECRET`, `DATABASE_URL`,
   `BYOK_ENCRYPTION_KEY`, …) — see [Secrets Management](SECRETS-MANAGEMENT.md).
2. Migrations reviewed (`alembic upgrade head`) — see
   [Data Migrations](DATA-MIGRATIONS.md) when available.
3. Feature flags reviewed: new systems default off; enable intentionally.
4. CI green on the release commit.
5. `make ci-check` green, and for a deployment-shaped change also
   `make deployment-profile-gate` — the full no-credentials profile, topology,
   plan-policy, cost and lifecycle chain.
6. Know which profile you are deploying to. `deployment_profile` decides the
   real resource graph and the runtime topology; see
   [Deployment Profiles](DEPLOYMENT-PROFILES.md).

## Deploy the application

1. Allow `deploy.yml` to build the commit once and deploy it to staging.
2. Retain the workflow run ID and `release.json.sha256` from staging evidence.
3. After staging validation and approval, dispatch the same workflow for
   `production` with those two values. Do not rebuild artifacts.
4. The workflow verifies every checksum and registers one exact task-definition
   revision per **service** declared for the target profile in
   `config/runtime_deployment.yaml`. It fails if an expected ECS service is
   absent.
5. Aether and Kyber archives are uploaded to private S3 origins. Versioned
   assets receive immutable caching; `index.html` is always no-cache.
6. Verify readiness, smoke, and deployment evidence for the selected release.

### Which services exist

The deployable unit is a **service**, not a role. On `production-lean` and
`staging` (`execution_mode: consolidated`) there are two services: `api` and
`lean-worker`, the latter hosting all eight worker roles in one task. On
`production-scale` and `enterprise-isolated` (`dedicated`) there are nine, one
per role.

Each service key is passed straight through as the container's `AETHER_ROLE`
token, and maps to `AETHER-<env>-<key>` — with one exception: `api` is served by
the `AETHER-<env>-backend` service. Do not expect an `AETHER-<env>-api` service
to exist.

## Deploy infrastructure

`.github/workflows/infrastructure.yml` is **plan-and-validate only**. It never
applies. The `apply-production-lean` job that once auto-applied on every push to
`main` has been deleted.

1. Dispatch **Reviewed Terraform promotion** (`terraform-promote.yml`) with
   `action=plan`, the target `profile`, the approved `backend_image_digest` and
   `ml_image_digest` from the release manifest, and — for `staging` only —
   `staging_state` (`awake` | `asleep`).
2. Review the run summary: profile, commit, state key, Terraform version,
   lockfile sha256, plan sha256, created and expires timestamps. Read
   `reviewed.tfplan.txt`, `reviewed.policy.txt` and `reviewed.cost.txt`.
3. Dispatch the same workflow with `action=apply`, the plan's run ID and the
   plan checksum, and approve the per-profile environment
   (`staging-terraform`, `production-lean-terraform`,
   `production-scale-terraform`, `enterprise-terraform`).
4. Apply downloads that exact plan, re-verifies profile, state key, commit,
   Terraform version, lockfile digest and the 24-hour expiry, checks out the
   plan's **own recorded commit**, re-runs the policy and cost validators at
   that commit, and runs `terraform apply reviewed.tfplan`. **It never creates a
   replacement plan.**

A reviewed plan expires after 24 hours. An expired plan is refused; produce a
fresh one rather than extending anything.

### Before the first apply of the current profile shape

Three migration hazards apply. All are correct and intended, and each needs a
window rather than a routine promotion — the detail is in
[Deployment Profiles](DEPLOYMENT-PROFILES.md#migration-hazards) and
[AWS Lean Production](AWS-LEAN-PRODUCTION.md).

- Moving to the consolidated shape **destroys seven ECS services**. Queues,
  DLQs and consumer groups survive; expect a gap between the old services
  draining and the new task becoming healthy.
- On a NAT-carrying workspace the private default route migration is a
  **maintenance window** with a brief possible egress outage. Apply it alone.
- The three production-class profiles collide on resource names and **require
  separate AWS accounts**. Separate state keys are not sufficient.

If a profile change ever plans a destroy on a data store, **stop**. That is a
stop-the-line event, not a diff to skim; the sanctioned path is
`AWS Deployment/aether-aws/terraform/DECOMMISSION.md`.

## Staging rehearsal

Staging is a wake-for-validation environment, not a permanently running copy.
Use `.github/workflows/staging-lifecycle.yml`; it never runs `terraform apply`
itself, dispatching `terraform-promote.yml` for every mutation.

```
action: plan-wake | apply-wake | validate | plan-sleep | apply-sleep | full-rehearsal
```

Always return staging to zero, including after a failed wake. An awake lease
(1–8 h, default 4) is written to SSM at wake; `staging-ttl-guard.yml` runs
hourly, treats a missing or unparseable lease as expired, scales services to
zero, drops autoscaling floors, and fails the run so the lapse is visible. After
the guard has acted, run `action: apply-sleep` to reconcile Terraform state.

Full procedure, incident handling and residual-cost inspection:
[Staging Wake / Sleep](STAGING-WAKE-SLEEP.md).

## Rollback

### Application

1. Promote the previous verified release manifest. The workflow re-verifies
   the manifest and artifacts before registering its task revisions and static
   bundles; mutable tags are not rollback inputs.
2. If a migration must be reverted, apply the documented down-revision
   (alembic) and restore from backup if data changed — see
   [Backup & Restore](BACKUP-RESTORE.md) when available.
3. Disable any newly-enabled feature flag.

### Infrastructure

Roll back by promoting a **new reviewed plan** produced from the previous
commit, through the same `terraform-promote.yml` path. There is no "revert
apply" button, and re-running an old plan file is refused once it has expired.

A rollback has never been executed against real infrastructure. The procedure is
documented; `COND-ROLLBACK-VALIDATED` remains unmet and the corresponding
controls are recorded as externally blocked.

## Smoke

Run `scripts/smoke_test.py` (or the documented `test:e2e`/smoke profiles)
against the deployed URL. See [Healthchecks](HEALTHCHECKS.md),
[Pre-production Readiness](PREPRODUCTION-READINESS.md), and
[Production Deployment](PRODUCTION-DEPLOYMENT.md).

## Evidence

```bash
make deployment-readiness-score      # three-column readiness scorecard
make collect-deployment-evidence     # materialise release-evidence/ + checksum
```

Readiness is three numbers and is never merged into one — see
[Release Evidence](RELEASE-EVIDENCE.md) and
[Founding-Tenant Production](FOUNDING-TENANT-PRODUCTION.md).
