---
title: Agentic Governance Productization
slug: architecture/agentic-governance-productization
section: architecture
visibility: I
audience: [dev-senior, architect, ai, ops]
status: experimental
since_version: "8.11.0"
source_files:
  - Backend Architecture/aether-backend/services/agentic_observability/governance.py
  - Backend Architecture/aether-backend/services/agentic_observability/routes.py
---

# Agentic Governance Productization

Aether's Agentic Governance layer productizes the remaining observation-first
operational controls around Agentic Intelligence without adding provider-side
execution. The service assembles tenant-scoped evidence from Bronze, Silver,
canonical activity, outbox, and compatibility observation stores.

## Kyber surfaces

- `GET /v1/admin/kyber/agentic-observability/commercialization` returns usage
  dimensions, entitlement keys, and operator limits.
- `POST /v1/admin/kyber/agentic-observability/privacy/dsr-preview` returns DSR
  export/tombstone impact counts and can include redacted rows for portability.
- `GET /v1/admin/kyber/agentic-observability/security-privacy` summarizes
  no-execution, secret handling, privacy, and cross-tenant controls.
- `GET /v1/admin/kyber/agentic-observability/rollout-controls` reports feature
  flags, emergency-disable instructions, and rollback notes.
- `GET /v1/admin/kyber/agentic-observability/operator-audit-package` bundles
  pipeline health, usage, security/privacy, and rollout controls for support.
- `GET /v1/admin/kyber/agentic-observability/release-candidate-evidence`
  evaluates tenant scenario evidence across ingestion, product surfaces,
  governance, and rollout controls.

## Observation-only boundary

These endpoints do not execute provider actions, revoke grants, post content,
trade, originate settlements, or mutate third-party state. DSR handling in this
slice is an audit-preserving preview/export manifest; destructive graph
execution remains a separately approved operator workflow.

## Release status

This PR upgrades governance, commercialization, rollout, and release-candidate
evidence from missing to partial. GA remains blocked until frontend/onboarding,
quarantine/rebuild actions, static scanners, performance/chaos gates, and the
full automated 39-step E2E scenario are complete.
