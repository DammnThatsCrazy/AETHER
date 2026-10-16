---
title: Observability and SLOs
slug: productization/economic-interoperability-intelligence/observability-and-slos
section: operations
visibility: I
audience: [architect, ops, buyer]
status: beta
since_version: 0.1.0
source_files: [services/api/journeys/notification_intelligence/consumer.py]
canonical_owner: platform@aether
source_hashes:
  "services/api/journeys/notification_intelligence/consumer.py": "sha256:ac3057954385cd9bbcf0428169affdcb71ddb5fa6358070d7b11c81c77bd917f"
---

# Observability and SLOs

## Signals shipped in 8.12.0

- Best-effort metrics at intake/materialization/run sites (the 8
  canonical meters double as usage signals).
- Alert topics: `aether.stablecoin.depeg.detected` (P1),
  `aether.derivatives.reconciliation.variance` (P2),
  `aether.derivatives.stream.gap.stalled` (P2),
  `aether.interop.message.stuck` (P2),
  `aether.interop.security.policy.changed` (P1).
- The notification consumer drops an alert event that carries no tenant
  (logged as `notification_dropped_no_tenant`, counted in
  `aether_notifications_dropped_total{reason="missing_tenant"}`) instead of
  fanning it out to channels.
- Operator health surfaces: Kyber ops pages expose checkpoint lag,
  open gaps, unresolved variances, correlation health, and policy drift.

## Target SLOs (proposed — to be validated in staging, not yet claimed)

| Signal | Target |
|---|---|
| Stream gap recovery | < 15 min from detection |
| Checkpoint lag (enabled providers) | < confirmation horizon + 10 blocks |
| Reconciliation variance triage | < 1 business day |
| Message-stuck alert latency | < SLA window + 5 min |

These SLOs are declared targets only; no staging soak has run yet
(see RELEASE_READINESS blockers).
