---
title: "Payment Rail Observability Runbook"
slug: runbooks/payment-rails
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/integrations/providers/payment_rails/sync_worker.py
  - Backend Architecture/aether-backend/services/integrations/providers/payment_rails/reconciliation.py
canonical_owner: platform@aether
last_synced_commit: "41c79d4"
---

# Payment Rail Observability Runbook

Operator surface: `/payments/ops` (Kyber) → `/v1/admin/kyber/payment-rails`.
Requires the payment-rails operator role; all actions are audited. Aether is
**observation-only** — it never initiates, modifies, or settles a payment. The
five first-release adapters (Privy, Stripe crypto onramp, Coinbase, MoonPay,
Bridge) are `CREDENTIAL_WAITING` in the certification matrix
(`docs/_generated/adapter-certification-matrix.json`): code-complete and
credential-gated, with no live provider validated in staging yet.

## Rollout flags (all default OFF)

`AETHER_PAYMENT_RAILS_ENABLED` is the master switch; per-provider gates are
`AETHER_PROVIDER_{PRIVY,STRIPE,COINBASE,MOONPAY,BRIDGE}_ENABLED`; the Kyber
surface is `KYBER_PAYMENT_RAILS_ENABLED`. Do not enable a provider until it has
a verified webhook signing secret in the vault and one session has been
reconciled end to end in staging (see `CREDENTIAL_WAITING_PROMOTION_GUIDE`).

## Sessions stuck in `sdk_only` / ageing to `stale`

1. The supervised sync worker (`sync_worker.run_sync_cycle`) is the ONLY
   producer of the `sdk_only → stale` transition. A rising `stale` count means
   SDK-observed sessions received no provider confirmation within
   `STALE_AFTER_SECONDS`.
2. Confirm the provider webhook is actually arriving: check the webhook
   ingestion audit for that provider/tenant. A signature-verification failure
   (per-provider HMAC scheme) drops the webhook silently by design — inspect the
   `rejected` metric, not the session.
3. For polling-capable providers (Coinbase, MoonPay, Bridge), confirm
   `provider_enabled(provider)` is true and `_fetch_poll_records` has a
   configured endpoint + credential. Until then the plane is webhook-primary and
   staleness is expected for SDK-only sessions.
4. A provider pull raising mid-cycle must NOT abort the sweep — staleness
   handling still applies to the rest of the tenant. If the whole cycle aborts,
   that is a bug: capture `run_sync_cycle` stats and file it.

## Reconciliation mismatch (SDK signal vs provider truth)

1. Provider truth always wins: the session status upsert is status-ordered and
   non-regressing, so a provider `completed` never reverts to an SDK `pending`.
2. If the SDK and provider disagree on amount/asset, do not hand-edit — record
   an operator note and let the next provider event supersede.
3. Duplicate webhook deliveries are idempotent (keyed per session); a webhook
   storm must not double-emit `payment_*` canonical events. If it does, treat as
   a P2 idempotency bug.

## Never do

- Never initiate, cancel, or modify a payment from Aether — observation only.
- Never enable a provider flag without a vault-backed signing secret.
- Never hand-edit a funding session or reconciliation record; supersede via a
  provider event instead.

See also: `docs/source-of-truth/PAYMENT_RAIL_OBSERVABILITY.md`,
`docs/runbooks/CARD_LINKED_RUNBOOK.md`, `docs/runbooks/CREDENTIAL-ROTATION.md`.
