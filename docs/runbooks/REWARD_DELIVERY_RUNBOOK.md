---
title: "Reward Delivery Runbook"
slug: runbooks/reward-delivery
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/rewards/delivery_outbox.py
  - Backend Architecture/aether-backend/services/rewards/rails.py
canonical_owner: platform@aether
last_synced_commit: "67271129"
---

# Reward Delivery Runbook

Reward delivery runs on the durable delivery outbox
(`RewardDeliveryOutbox`): enqueue → leased dispatch → provider receipt →
mark delivered. Aether operates a **no-custody** model — it never holds or moves
funds; the on-chain rails are oracle-signed claims gated by
`EVM_REWARD_PROOFS_ENABLED` (EVM proofs production-warrantied) with an SVM
(`program_id`) proof path exercised on devnet (sandbox tier). The `onchain_claim`
rail completes through the claim reconciler (`services/rewards/reconcile.py`):
a receipt confirming an on-chain claim marks the linked proof `used` (single-use
— nonce replay protection) and transitions the action to `delivered`; a proof
whose nonce is already used is refused. Core invariant: a reward action is
**never** marked `delivered` without a persisted `ProviderReceipt`.

Abandoned budget reservations are reclaimed by the reservation-release worker
(`services/rewards/reservation_release.py`): a `reserved`-only reservation older
than `REWARD_RESERVATION_TTL_SECONDS` (default 3600s) is resolved — committed if
the linked action was actually delivered, otherwise released and the leaked
non-terminal action marked failed/abandoned. A reservation that never reaches a
terminal state otherwise leaks budget until a human intervenes, so a rising
`reward_reservation_release` dead-letter count is a real signal.

## Deliveries stuck in `failed` (retrying)

1. A retryable send outcome (timeout, HTTP 5xx) schedules a backoff retry:
   `state = failed`, `attempt_count` incremented, `next_attempt_at` pushed into
   the future. The job is NOT runnable until `next_attempt_at` — a job sitting
   in `failed` with a future `next_attempt_at` is healthy, not stuck.
2. If `attempt_count` reaches `max_attempts`, the job dead-letters and the
   reward action is marked `failed` — never silently delivered. Confirm via
   `status()` counts.

## Dead-letter queue growing

1. Inspect the `last_error` on dead-lettered jobs. A cluster of the same error
   (e.g. a tenant webhook host down) is an integration issue, not a platform
   bug.
2. Operator replay (`redeliver`) requeues a dead-lettered job (`state = queued`)
   once the downstream is fixed. Redeliver is idempotent at the receipt layer.

## Webhook destination rejected before enqueue

The SSRF/transport check runs BEFORE a durable job is written, so a blocked
destination (private IP, plain-HTTP outside local) never becomes a job. A
`ValueError: webhook destination rejected` at enqueue is correct hardening, not
an outage.

## Never do

- Never mark an action `delivered` without a persisted receipt.
- Never enable on-chain reward proofs (`EVM_REWARD_PROOFS_ENABLED`) before the
  external smart-contract audit is complete (see `EVM_DEPLOY_EMERGENCY_RUNBOOK`).
- Never hand-move funds — the platform is no-custody by construction.

See also: `docs/source-of-truth/REWARD_ENABLEMENT.md`,
`docs/source-of-truth/REWARD_NO_CUSTODY_MODEL.md`,
`docs/source-of-truth/REWARD_RAILS.md`, `docs/runbooks/DELIVERY-FAILURES.md`.
