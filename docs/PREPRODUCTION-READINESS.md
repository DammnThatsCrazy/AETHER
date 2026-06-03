---
title: Pre-production Readiness
slug: operations/preproduction-readiness
section: operations
visibility: I
audience: [exec, architect, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# Pre-production Readiness

Checklist for promoting Aether/Kyber from local to staging/pre-production. This
is a readiness gate, not a certification.

## Gates

- [ ] **Config**: staging `.env` from `.env.staging.example`; required secrets in
      the secret manager; `AETHER_ENV=staging`.
- [ ] **Health**: `GET /v1/health` green; `GET /v1/status` responds; container
      healthchecks pass.
- [ ] **Data**: migrations applied (`alembic upgrade head`); retention policies
      seeded; backup/restore path validated.
- [ ] **Isolation**: tenant-isolation verifier passes; Kyber routes operator-only;
      no cross-tenant leakage in aggregate views.
- [ ] **Security**: no secrets in logs/exports/UI; webhook signing on; rate limits
      active; secret scan + dependency audit run (see
      [Security Readiness](SECURITY-READINESS.md) when available).
- [ ] **Flags**: new systems default off; enable intentionally; partner ecosystem
      stays future-flagged off.
- [ ] **Frontends**: Aether/Kyber/Demo build with env-driven API URLs; local-mocked
      mode boots; empty/loading/error states present.
- [ ] **Observability**: metrics scrape (`/v1/metrics`); reliability dashboards
      populate; SLOs tracked.
- [ ] **CI**: repo-health, frontend tests, e2e all green; docs validation passes.

## Subsystem readiness (current)

Governance/control-plane, reliability/SRE, data-quality/drift, billing/revops +
external billing provider (flagged), onboarding, customer success, OODA, outcome
ledger, playbooks, audit exports — implemented and wired. Connectors and the
Demo App land in subsequent phases.

See [Production Deployment](PRODUCTION-DEPLOYMENT.md),
[Deployment Runbook](DEPLOYMENT-RUNBOOK.md), and
[Productization Checklist](PRODUCTIZATION-CHECKLIST.md).
