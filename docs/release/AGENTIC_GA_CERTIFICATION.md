---
title: Agentic Intelligence GA Certification
slug: release/agentic-ga-certification
section: operations
visibility: I
audience: [dev-senior, architect, ai, ops]
status: experimental
since_version: "8.11.0"
source_files:
  - Backend Architecture/aether-backend/services/agentic_observability/release_readiness.py
  - Backend Architecture/aether-backend/services/agentic_observability/routes.py
---

# Agentic Intelligence GA Certification

Aether Agentic Intelligence remains an internal-preview capability until the
Kyber release-readiness endpoint reports `ga_ready: true`.

```text
GET /v1/admin/kyber/agentic-observability/release-readiness
```

The gate is intentionally conservative. It requires product, graph, MCP,
provider, Noesis, Kyber, frontend, onboarding, security, privacy, billing,
rollout, load/chaos, and release-level end-to-end evidence before GA can be
claimed.

## Current release gate

The current release gate is `internal_preview`.

## Required evidence areas

- Canonical ingestion and durable outbox coverage.
- MCP gateway, TypeScript/Python middleware, and local stdio proxy.
- Provider connector lifecycle and X reference connector productization.
- Delegated-authority graph semantics, temporal intelligence, identity, risk,
  and path intelligence.
- Profile 360, Journey v2, Cluster360, campaign attribution, outcomes, and
  tenant-safe exports.
- Noesis evidence labeling, contradiction handling, and unsupported-claim
  refusal.
- Kyber command center, tenant frontend, onboarding, health, and alerts.
- Security hardening, privacy/DSR, billing, rollout controls, performance,
  chaos, and release certification.
- Full release-level end-to-end scenario proving Aether observes and never
  executes provider actions.

## Rollback

The endpoint is read-only. Roll back by reverting the route and
`release_readiness.py` if the matrix needs to be removed from Kyber.
