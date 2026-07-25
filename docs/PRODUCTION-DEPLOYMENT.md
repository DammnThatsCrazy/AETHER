---
title: Production Deployment
slug: self-hosting/production-deployment
section: self-hosting
visibility: I
audience: [ops, architect, dev-senior]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 9
---

# Production Deployment

Provider-agnostic production deployment guidance. The repo ships Docker images,
an AWS reference (`AWS Deployment/aether-aws/terraform/`,
`.github/workflows/deploy.yml`, `.github/workflows/terraform-promote.yml`), and
`docker-compose` for non-AWS hosts. Choose the target that fits your infra; the
contract below is what production needs regardless.

On AWS, the shape of production is decided by one variable. `deployment_profile`
selects `production-lean`, `production-scale` or `enterprise-isolated`, and it
drives the real Terraform resource graph and the runtime topology — see
[Deployment Profiles](DEPLOYMENT-PROFILES.md) and, for the founding-tenant
profile in depth, [AWS Lean Production](AWS-LEAN-PRODUCTION.md).

## Required production config

- `AETHER_ENV=production`, `DEBUG=false`.
- `JWT_SECRET`, `DATABASE_URL` (PostgreSQL), `BYOK_ENCRYPTION_KEY`,
  `ORACLE_SIGNER_PRIVATE_KEY` — from a secret manager, never from the
  environment file or the task definition.
- `CORS_ORIGINS` set to the real app/API origins.
- Frontends built with env-driven `VITE_API_BASE_URL` and `VITE_*_ENV=production`.
- `AETHER_ROLE` set per process. On AWS it is the ECS service key, injected by
  `deploy.yml`; on any other host it must be set explicitly, because it decides
  which roles that process hosts.
- `GRAFANA_ADMIN_PASSWORD` is required **only** when you run the optional
  self-hosted observability stack (`deploy/observability/`, the `docker-compose`
  Grafana service). The AWS profiles are CloudWatch-native and provision no
  Grafana or Prometheus server at any tier — `prometheus_grafana_servers` is a
  forbidden resource for every profile.

## Topology

- Backend (`uvicorn main:app`) behind a load balancer using `/v1/health` probes.
  `/v1/ready` additionally asserts the database alembic revision equals the
  packaged head, so it is the authoritative post-migration check.
- Durable PostgreSQL. Memory cache and memory event bus are development-only and
  are rejected in a deployed profile.
- The remaining backends are **profile selectors**, not a fixed list:

| Dimension | `production-lean` | `production-scale` / `enterprise-isolated` |
|---|---|---|
| database | Aurora Serverless v2 Postgres | Aurora Serverless v2 Postgres |
| cache | DynamoDB | ElastiCache Redis |
| event bus | SNS → SQS | MSK Kafka |
| graph | Aurora Postgres | Neptune |
| analytics | Postgres | ClickHouse (selector only — no module provisions it) |
| ML serving | inline, in-process | dedicated ECS service |

  Which backend a running task uses is passed explicitly (`EVENT_BROKER`,
  cache/graph/analytics selectors) rather than inferred from whether a host
  string happens to be set.
- Aether, Kyber (and Demo) served as static builds from immutable object-store
  origins behind a CDN. They are never ECS services — `frontend_ecs_services` is
  forbidden at every profile.

### Runtime processes

The deployable unit is a service, not a role. `production-lean` runs **two**
always-on tasks — `api`, and one `lean-worker` task hosting all eight worker
roles — rather than one task per role. Consolidation moves the process boundary
only: each role keeps its own queue, consumer group, DLQ, retry policy,
backpressure budget and metrics label. `production-scale` and
`enterprise-isolated` run one service per role instead. The canonical matrix is
`config/runtime_deployment.yaml`.

## Sequence

1. Provision infra + secrets. 2. `alembic upgrade head`. 3. Deploy backend; verify
`/v1/health` and `/v1/ready`. 4. Deploy frontends with env-driven URLs. 5. Smoke
test. 6. Enable feature flags intentionally (default off).

On AWS, steps 1 and 3 are two different promotion paths: infrastructure through
`terraform-promote.yml` (reviewed, checksum-bound, apply never re-plans) and the
application through `deploy.yml` (immutable digests, no rebuild on promotion).
[Deployment Runbook](DEPLOYMENT-RUNBOOK.md) is the operator procedure for both.

## Safety

- Optional integrations (Stripe, connectors, email, providers) do not block
  startup when disabled.
- Partner ecosystem/marketplace/developer-platform remain future-flagged off.
- No compliance certification is implied — see
  [Security Readiness](SECURITY-READINESS.md) when available.
- On AWS, no environment has been applied, billed, load-tested or rolled back.
  Readiness is reported as a code-complete column and an externally-verified
  column and is never merged into one number; `deployment_ready` is currently
  `false`. See [Release Evidence](RELEASE-EVIDENCE.md).

See [Deployment Runbook](DEPLOYMENT-RUNBOOK.md),
[Deployment Profiles](DEPLOYMENT-PROFILES.md),
[Cost Optimization](COST-OPTIMIZATION.md),
[Healthchecks](HEALTHCHECKS.md),
[App Routing & Domains](APP-ROUTING-DOMAINS.md), and
[Deployment & Hosting Readiness](DEPLOYMENT-HOSTING-READINESS.md).
