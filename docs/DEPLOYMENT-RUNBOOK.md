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

- Images: backend (`Backend Architecture/aether-backend/Dockerfile`), Aether
  (`frontend/aether/Dockerfile`), Kyber (`frontend/kyber/Dockerfile`), ML
  (`ML Models/aether-ml/docker/Dockerfile`).
- CI build/push: `.github/workflows/deploy.yml` (ECR + ECS, manual or on main).
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

1. Build + push images (CI `deploy.yml` or manual `docker build`).
2. Apply migrations: `alembic upgrade head` against the target `DATABASE_URL`.
3. Roll out backend, then frontends (env-driven `VITE_API_BASE_URL`).
4. Verify `GET /v1/health` is green and `GET /v1/status` responds.

## Rollback

1. Re-deploy the previous image tag.
2. If a migration must be reverted, apply the documented down-revision
   (alembic) and restore from backup if data changed — see
   [Backup & Restore](BACKUP-RESTORE.md) when available.
3. Disable any newly-enabled feature flag.

## Smoke

Run `scripts/smoke_test.py` (or the documented `test:e2e`/smoke profiles)
against the deployed URL. See [Healthchecks](HEALTHCHECKS.md),
[Pre-production Readiness](PREPRODUCTION-READINESS.md), and
[Production Deployment](PRODUCTION-DEPLOYMENT.md).
