---
title: Deployment Runbook
slug: operations/deployment-runbook
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 6
---

# Deployment Runbook

Operational steps to deploy and roll back Aether/Kyber. Provider-agnostic; align
with your infra (the repo ships Docker images, `docker-compose`, and AWS
workflows as references).

## Artifacts

- Immutable backend image by digest, static Aether and Kyber archives, migration
  archive, and runtime configuration are bound in `release.json`.
- CI build/push: `.github/workflows/deploy.yml`. A push to `main` builds once
  and targets staging only. Production promotion is manual and requires the
  staged workflow-run ID plus the approved release-manifest checksum.
- Local/staging stack: `docker-compose.yml` (+ profiles) and
  `deploy/staging/{bootstrap.sh,docker-compose.staging.yml,kafka_topics.sh}`.

## Pre-deploy checklist

1. Required secrets present in the secret manager (`JWT_SECRET`, `DATABASE_URL`,
   `BYOK_ENCRYPTION_KEY`, …) — see [Secrets Management](SECRETS-MANAGEMENT.md).
2. Migrations reviewed (`alembic upgrade head`) — see
   [Data Migrations](DATA-MIGRATIONS.md) when available.
3. Feature flags reviewed: new systems default off; enable intentionally.
4. CI green on the release commit.

## Deploy

1. Allow `deploy.yml` to build the commit once and deploy it to staging.
2. Retain the workflow run ID and `release.json.sha256` from staging evidence.
3. After staging validation and approval, dispatch the same workflow for
   `production` with those two values. Do not rebuild artifacts.
4. The workflow verifies every checksum, registers one exact task-definition
   revision per required role, and fails if any expected ECS service is absent.
5. Aether and Kyber archives are uploaded to private S3 origins. Versioned
   assets receive immutable caching; `index.html` is always no-cache.
6. Verify readiness, smoke, and deployment evidence for the selected release.

For infrastructure changes, dispatch `Reviewed Terraform promotion` with
`action=plan`. After review and environment approval, dispatch `action=apply`
with the plan run ID and checksum. Apply downloads and verifies that plan and
runs `terraform apply reviewed.tfplan`; it never creates a replacement plan.

## Rollback

1. Promote the previous verified release manifest. The workflow re-verifies
   the manifest and artifacts before registering its task revisions and static
   bundles; mutable tags are not rollback inputs.
2. If a migration must be reverted, apply the documented down-revision
   (alembic) and restore from backup if data changed — see
   [Backup & Restore](BACKUP-RESTORE.md) when available.
3. Disable any newly-enabled feature flag.

## Smoke

Run `scripts/smoke_test.py` (or the documented `test:e2e`/smoke profiles)
against the deployed URL. See [Healthchecks](HEALTHCHECKS.md),
[Pre-production Readiness](PREPRODUCTION-READINESS.md), and
[Production Deployment](PRODUCTION-DEPLOYMENT.md).
