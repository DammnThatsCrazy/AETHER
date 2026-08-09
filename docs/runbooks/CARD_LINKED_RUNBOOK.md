---
title: "Card-Linked Payment Rails Runbook"
slug: runbooks/card-linked
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/card_linked_payments/ingestion.py
  - Backend Architecture/aether-backend/services/card_linked_payments/gold.py
canonical_owner: platform@aether
last_synced_commit: "ac900d5"
---

# Card-Linked Payment Rails Runbook

Operator surface: card-linked activity surfaces under `Profile360 → Economic
Activity → Payment Rails → Card-linked Activity` and the Kyber payment-rails
drill-down. This plane is **observation-only** and the least mature economic
domain (scorecard 2/5): every rollout flag defaults OFF and no live provider
data has ever flowed through it.

## Rollout flags (all default OFF)

`AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED` (master),
`AETHER_PAYMENTSCAN_CATALOG_ENABLED`, `AETHER_PAYMENTSCAN_BENCHMARKS_ENABLED`,
`AETHER_CARD_LINKED_PROFILE360_ENABLED`,
`AETHER_CARD_LINKED_CAMPAIGN_ATTRIBUTION_ENABLED`,
`AETHER_CARD_LINKED_CLUSTERING_ENABLED`, `KYBER_CARD_LINKED_PAYMENT_RAILS_ENABLED`.
With every flag off the plane is inert; `PaymentScan` stays catalog/benchmark
only and never reads tenant-authorized provider evidence.

## Ingestion rejected (PII / region / consent gate)

1. Card-linked ingestion (`ingestion.py`) applies PII, region, and consent
   gates before any flow upsert. A rejected ingest is correct behavior, not an
   incident — inspect the rejection reason in the audit trail.
2. Flow upserts are idempotent; a duplicate ingest of the same flow must not
   create a second row. If it does, treat as a P2 idempotency bug.

## Gold materialization not appearing

1. Card-linked Gold is materialized by the payment-rail sync worker only when
   `AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED` is true. With the flag off,
   `materialize_gold` is never called — expected.
2. When enabled, Gold materialization is best-effort and periodic; a single
   failed cycle is retried next sweep and should not be hand-repaired.

## Tenant import stuck / failed mid-import

Tenant imports run through the canonical import-session FSM
(`services/card_linked_payments/import_session.py` +
`services/imports/session_persistence.py`): `CREATED → UPLOADED → VALIDATING →
VALIDATED → NORMALIZING → COMMITTING → PROJECTING → RECONCILING → COMPLETED`,
with `REJECTED`, `FAILED` (retryable), `DEAD_LETTERED`, and `ROLLED_BACK`
terminals. `COMMITTING` is re-entrant — a crash mid-commit is resumed by a
restart or operator requeue, never re-staged from scratch. A session dead-letters
only after its retry budget is exhausted or it strands in an in-flight state past
the hard deadline (`sweep_stranded_sessions`). Inspect the session's
`failure_reason` / `retry_count` and the `import.commit` job timeline before
requeueing.

## Never do

- Never enable card-linked flags in production without a tenant-authorized
  provider evidence source and a completed privacy review.
- Never join card-linked flows to identities outside the consent scope.
- Never treat catalog/benchmark rows as observed tenant activity.

See also: `docs/source-of-truth/CARD_LINKED_PAYMENT_RAILS.md`,
`docs/source-of-truth/PAYMENTSCAN_CATALOG.md`,
`docs/runbooks/PAYMENT_RAILS_RUNBOOK.md`.
