---
title: Deployment & Hosting Readiness
slug: operations/deployment-hosting-readiness
section: operations
visibility: I
audience: [architect, ops, dev-senior]
status: beta
since_version: "0.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 6
---

# Deployment & Hosting Readiness

The platform deploys as containerized services with environment-driven
configuration. This page complements [Deployment Readiness](DEPLOYMENT-READINESS.md)
with the hosting/config contract.

## Build artifacts

- Backend: `services/backend/Dockerfile`
- Aether tenant frontend: `apps/aether-web/Dockerfile`
- Kyber operator frontend: `apps/kyber-web/Dockerfile` (private artifact path)
- Olympus Labs marketing: `apps/marketing-olympus`
- Aether marketing: `apps/marketing-aether`
- Public status: `apps/status`
- ML serving: `services/ml/docker/Dockerfile`

`.github/workflows/deploy.yml` builds and pushes images to ECR; infrastructure is
Terraform-managed under `infra/aws/terraform/`. `infra/local/docker-compose.yml`
with profiles (`streaming`, `analytics`, `notebooks`, `full`) runs the stack
locally.

## Configuration contract

- **Backend** reads all config from environment (`config/settings.py`). In
  non-local environments `JWT_SECRET` and `DATABASE_URL` are required; the app
  fails fast if they are missing.
- **Frontends** build with env-driven API URLs (`VITE_API_BASE_URL`); do not
  hardcode `localhost` for deployment. `VITE_AETHER_ENV` / `VITE_KYBER_ENV`
  are explicitly `local`, `staging`, or `production` (`test` is reserved for
  automation). Invalid configuration prevents normal application startup.
  Staging and production require complete authentication configuration;
  production API URLs must be HTTPS.

## Frontend data-truth contract

- Aether and Kyber are API-backed in every normal runtime environment.
- A clean deployment is live and empty. Empty collections render empty states;
  API/dependency failures render unavailable/error states.
- Production bundles contain no browser MSW worker, runtime fixture imports,
  mock authentication tokens, or synthetic operational datasets.
- A scoped startup migration removes only legacy `mockServiceWorker.js`
  registrations and their caches.
- Normal backend startup and database migrations never seed demonstration data.
  Demo seed/reset are explicit backend operations, refused in production, and
  allowed in staging only by an explicit policy and tenant allowlist.

## Feature flags default safe

Every new system is flagged off by default — data quality, intelligence quality,
external/Stripe billing, and provider sync.
Optional integrations (Stripe, providers, email) do not break startup when their
env vars are absent; they are simply inactive.

## Health checks

The backend exposes liveness and structured component health under `/health` and
`/v1/health`; readiness is `/ready` and `/v1/ready`. The public status app reads
the verified `/health` payload and renders unknown/degraded/down component
states without substituting tenant-specific feature readiness. Reliability
service/pipeline/queue health remains operator-only under
`/v1/admin/kyber/reliability/*`.

## Readiness summary

- Backend starts with only `AETHER_ENV=local` locally; with `JWT_SECRET` +
  `DATABASE_URL` in staging/production.
- Frontends build per environment with `VITE_*` config.
- Local and production config are separated via `.env` files and `VITE_*` envs.
- Feature flags default safe. There is no partner ecosystem, marketplace or developer platform in the product and no flag for one.
- Frontend data-truth source and production-bundle scans are required CI gates.

See [Local Development](LOCAL-DEVELOPMENT.md) and
[External Billing Integration](../reference/EXTERNAL-BILLING-INTEGRATION.md).
