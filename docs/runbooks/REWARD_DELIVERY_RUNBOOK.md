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
last_synced_commit: "1c1b7416"
---

# Reward Delivery Runbook

Reward delivery runs on the durable delivery outbox
(`RewardDeliveryOutbox`): enqueue → leased dispatch → provider receipt →
mark delivered. **Every** sender-backed rail (`tenant_webhook`,
`internal_credit`, `stripe_credit`, `x402_credit`) delivers through the outbox
— the action is `pending` until a `ProviderReceipt` is recorded, and the
receipt carries the rail's real provider/channel (not a hardcoded webhook). A
transient credential-authority/DB/KMS outage while resolving a signing secret
is classified **retryable** (backoff), never dead-lettered on the first attempt
as if the credential were missing. Aether operates a **no-custody** model — it never holds or moves
funds; the on-chain rails are oracle-signed claims gated by
`EVM_REWARD_PROOFS_ENABLED`. Outside `local`/`test` an on-chain claim
fails closed unless the campaign carries an explicit chain identity
(`chain_id` + `contract_address`); the local Anvil chain id and the
default Anvil contract address are rejected, and the identity is validated
**before** the signer is resolved, so a misconfigured campaign never
produces a signed claim against the wrong chain. Core invariant: a reward
action is **never** marked `delivered` without a persisted `ProviderReceipt`.

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

## Webhook signing secret could not be resolved

The signing secret is resolved from the credential authority at the narrow send
site (`services/rewards/webhook_secret.py`), NOT stored plaintext in the job —
the job carries only a `secret_ref`. A `fatal` send outcome with
"signing secret could not be resolved" means the tenant has no ACTIVE
`webhook_signing_secret` credential for the `tenant_webhook` provider in this
environment (never delivered, never signed with an empty key). Remediate by
(re)submitting the credential via
`PUT /v1/providers/credentials/tenant_webhook/slots/webhook_signing_secret`
then `activate`; a rotation keeps the previous secret valid during the overlap
window so in-flight receivers still verify.

## Never do

- Never mark an action `delivered` without a persisted receipt.
- Never enable on-chain reward proofs (`EVM_REWARD_PROOFS_ENABLED`) before the
  external smart-contract audit is complete (see `EVM_DEPLOY_EMERGENCY_RUNBOOK`).
- Never hand-move funds — the platform is no-custody by construction.

See also: `docs/source-of-truth/REWARD_ENABLEMENT.md`,
`docs/source-of-truth/REWARD_NO_CUSTODY_MODEL.md`,
`docs/source-of-truth/REWARD_RAILS.md`, `docs/runbooks/DELIVERY-FAILURES.md`.
