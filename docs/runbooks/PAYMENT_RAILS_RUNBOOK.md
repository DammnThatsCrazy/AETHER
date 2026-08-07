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
last_synced_commit: "380de9d"
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
an **active** webhook signing secret in the durable CredentialAuthority (the
in-memory BYOK vault is retired for payment providers outside local dev) and one
session has been reconciled end to end in staging (see
`CREDENTIAL_WAITING_PROMOTION_GUIDE`). Full activation/rollback/certification
steps live in `docs/PAYMENT-RAILS-ACTIVATION.md`.

`STALE_AFTER_SECONDS` and the sync cadence are environment-tunable
(`AETHER_PAYMENT_RECON_STALE_AFTER_SECONDS`, `AETHER_PAYMENT_SYNC_INTERVAL_SECONDS`).

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

## Delivery integrity: receipts, canonical delivery & repair

1. Every delivery (verified webhook or polled record) has one durable, metadata-
   only **receipt** (`payment_provider_receipts`) tracking it through the stage
   machine (`received → … → completed`) plus terminal states (`rejected`,
   `quarantined`, `retry_pending`, `repair_pending`, `dead_lettered`). Inspect a
   receipt to see exactly where a delivery stopped and its linked funding
   session / canonical event id(s) / outbox record.
2. The supervised **canonical-repair worker** (`payment_canonical_repair`,
   `AETHER_PAYMENT_CANONICAL_REPAIR_ENABLED`) idempotently re-drives incomplete
   deliveries; the admin `canonical-backlog/repair` endpoint does the same on
   demand (audited). Repair never double-emits or double-bills (deterministic
   canonical id). A growing `PaymentRailCanonicalBacklog` /
   `PaymentRailOutboxDeadLetterGrowth` alert means delivery is falling behind —
   confirm the outbox relay is enabled **with** the canonical outbox.
3. Alerts live in the `aether_payment_rails` Prometheus group; alert meanings are
   catalogued in `docs/PAYMENT-RAILS-ACTIVATION.md#alerts`. Derived conditions
   with no single-series PromQL form (reconciliation-conflict backlog, backlog
   *growth*, outbox stalling, provider silence) are classified by an in-process
   evaluator (`alert_eval.py`) with env-tunable `AETHER_PAYMENT_ALERT_*`
   thresholds; it reports `unknown` (no data) distinctly from `ok`.
4. **Ledger truth on the durable-outbox path.** When the canonical outbox is on,
   ingestion parks a receipt at `outbox_enqueued`/`"enqueued"` and the relay
   drains the row out of band. The supervised repair sweep records the
   `outbox_published` transition (publication state → `"published"`) before it
   marks the receipt `completed`, so a completed durable-path receipt reflects
   the stage it actually passed rather than a stale `"enqueued"`. This is
   forward-only and idempotent (direct-publish receipts already passed the stage;
   a re-run skips completed receipts) — do not "fix" a `completed` receipt whose
   publication state reads `published`; that is the correct terminal shape.

### Delivery-integrity guarantees (what the tests pin)

These invariants are enforced by regression tests
(`tests/payment_rails/test_provider_pipeline_matrix.py`, `test_delivery_relay.py`,
`test_crash_recovery.py`, `test_webhook_admission_edges.py`,
`test_polling_fetch_paths.py`) so a refactor can't silently break them:

- **One observation → one receipt → one funding session → one canonical id per
  event type**, for all five providers end to end.
- **Idempotent recovery after a crash at *any* receipt stage:** the repair worker
  re-drives to `completed` without a second session, a second canonical event, or
  a second usage-meter charge; a crash *before* the session is linked bounds to
  `no_funding_session` and dead-letters after the attempt cap — it never
  fabricates a session.
- **Replayed / duplicate / malformed webhooks** map to one receipt (no double
  metering) or are rejected with a uniform, secret-free error plus a server-side
  audit record.
- **Polling never raises:** a provider 5xx/4xx/timeout/unparseable-body degrades
  poll health and returns the partial records gathered; webhook-only providers
  (Privy, Stripe onramp) no-op the poll path (`webhook_only`).

## Never do

- Never initiate, cancel, or modify a payment from Aether — observation only.
- Never enable a provider flag without a vault-backed signing secret.
- Never hand-edit a funding session or reconciliation record; supersede via a
  provider event instead.

See also: `docs/source-of-truth/PAYMENT_RAIL_OBSERVABILITY.md`,
`docs/runbooks/CARD_LINKED_RUNBOOK.md`, `docs/runbooks/CREDENTIAL-ROTATION.md`.
