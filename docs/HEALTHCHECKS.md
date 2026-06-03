---
title: Healthchecks
slug: operations/healthchecks
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: stable
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Healthchecks

## Endpoints

| Endpoint | Audience | Purpose |
| --- | --- | --- |
| `GET /v1/health` | infra/load balancer | Deep liveness/readiness probe (status, timestamp, dependency/service summary). Public (bypasses auth). |
| `GET /v1/metrics` | internal | Prometheus metrics scrape. |
| `GET /v1/status` | tenant-safe | Single-tenant system status (no infra internals, no other tenants). |
| `GET /v1/admin/kyber/reliability/*` | operator | Service/pipeline/queue health, SLOs (operator-gated). |

## Container healthchecks (`docker-compose.yml`)

- Backend: `curl -sf http://localhost:8000/v1/health` (30s interval, 5s timeout,
  3 retries, 15s start period).
- Postgres: `pg_isready -U aether`; Redis: `redis-cli ping`; LocalStack:
  `/_localstack/health`; Kyber frontend: `wget .../health`.

## Deployment probes

Use `/v1/health` for liveness/readiness in your orchestrator. The backend
**fails fast** at startup in non-local environments if `JWT_SECRET` or
`DATABASE_URL` is missing, so a failing health probe on boot usually indicates
missing required config. Optional integrations (Stripe, connectors, email) do
**not** block startup when disabled.

See [Production Deployment](PRODUCTION-DEPLOYMENT.md) and
[Deployment Runbook](DEPLOYMENT-RUNBOOK.md).
