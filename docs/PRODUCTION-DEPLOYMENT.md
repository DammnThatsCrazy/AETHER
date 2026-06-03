---
title: Production Deployment
slug: self-hosting/production-deployment
section: self-hosting
visibility: I
audience: [ops, architect, dev-senior]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 6
---

# Production Deployment

Provider-agnostic production deployment guidance. The repo ships Docker images,
an AWS reference (`AWS Deployment/`, `.github/workflows/deploy.yml`,
`infrastructure.yml`), and `docker-compose` for non-AWS hosts. Choose the target
that fits your infra; the contract below is what production needs regardless.

## Required production config

- `AETHER_ENV=production`, `DEBUG=false`.
- `JWT_SECRET`, `DATABASE_URL` (PostgreSQL), `BYOK_ENCRYPTION_KEY`,
  `ORACLE_SIGNER_PRIVATE_KEY`, `GRAFANA_ADMIN_PASSWORD` — from a secret manager.
- `CORS_ORIGINS` set to the real app/API origins.
- Frontends built with env-driven `VITE_API_BASE_URL` and `VITE_*_ENV=production`.

## Topology

- Backend (`uvicorn main:app`) behind a load balancer using `/v1/health` probes.
- PostgreSQL (durable), Redis (rate-limit/quota + cache), event bus
  (Kafka or SNS/SQS via `EVENT_BROKER`), optional ClickHouse/analytics, graph
  endpoint (`NEPTUNE_ENDPOINT`) where graph features are enabled.
- Aether, Kyber (and Demo) served as static builds via CDN/static host.

## Sequence

1. Provision infra + secrets. 2. `alembic upgrade head`. 3. Deploy backend; verify
`/v1/health`. 4. Deploy frontends with env-driven URLs. 5. Smoke test. 6. Enable
feature flags intentionally (default off).

## Safety

- Optional integrations (Stripe, connectors, email, providers) do not block
  startup when disabled.
- Partner ecosystem/marketplace/developer-platform remain future-flagged off.
- No compliance certification is implied — see
  [Security Readiness](SECURITY-READINESS.md) when available.

See [Deployment Runbook](DEPLOYMENT-RUNBOOK.md),
[Healthchecks](HEALTHCHECKS.md),
[App Routing & Domains](APP-ROUTING-DOMAINS.md), and
[Deployment & Hosting Readiness](DEPLOYMENT-HOSTING-READINESS.md).
