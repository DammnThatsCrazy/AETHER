---
source_files:
  - packages/shared/payment-rails.ts
  - Backend Architecture/aether-backend/services/integrations/providers/payment_rails/base.py
  - Backend Architecture/aether-backend/services/integrations/providers/payment_rails/repository.py
  - Backend Architecture/aether-backend/services/integrations/providers/payment_rails/reconciliation.py
  - Backend Architecture/aether-backend/services/integrations/providers/payment_rails/service.py
  - Backend Architecture/aether-backend/services/integrations/providers/payment_rails/routes.py
  - Backend Architecture/aether-backend/services/integrations/providers/payment_rails/sync_worker.py
last_synced_commit: HEAD
---

# Payment Rail Observability V1 — Source of Truth

## Overview

Aether identifies, normalizes, reconciles, and displays how money enters,
exits, settles, or fails across users, wallets, agents, orgs, campaigns,
journeys, and providers. A tenant can see which onramp/offramp/deposit rail
was used, which provider processed it, which wallet/account received funds,
whether a human or agent initiated it, which journey/campaign attributed it,
whether it reconciled, and whether Aether/Kyber views are in parity.

**Aether observes payment rails — it never executes or settles payments,
custodies funds, or signs transactions.**

## Provider scope — named adapters only

Exactly five first-class adapters in
`services/integrations/providers/payment_rails/` — there is **no generic
webhook fallback**; unknown providers are 404:

| Provider | Module | Flows | Webhooks | Polling | Notes |
|---|---|---|---|---|---|
| Privy | `privy.py` | fiat_onramp, bank_deposit, crypto_deposit | ✓ | — | Underlying processor (Stripe/MoonPay/Coinbase/Meld) preserved as `provider_detail` for cross-provider reconciliation; deposit addresses as side records |
| Stripe | `stripe_onramp.py` | crypto_onramp | ✓ | — | Crypto onramp sessions; distinct from Aether's own billing Stripe |
| Coinbase | `coinbase.py` | fiat_onramp, offramp | ✓ | ✓ (`partnerUserRef`) | in-progress/started→pending/submitted, success→completed, failed→failed |
| MoonPay | `moonpay.py` | fiat_onramp (buy), offramp (sell) | ✓ | ✓ | Duplicate/out-of-order absorbed; AML/fraud/min-amount rejections → `failed` + `status_reason` |
| Bridge | `bridge.py` | bank_deposit, settlement, refund | ✓ | ✓ | Virtual accounts as side records; bank account refs stored masked (`****1234`) only |

Each adapter implements the `PaymentRailAdapter` ABC (`base.py`): descriptor,
`is_configured`, `test_connection`, `verify_webhook` (HMAC-SHA256 against the
tenant's vault secret, constant-time, no provider SDK imports),
`parse_webhook`, `status_sync`, `normalize_to_funding_session`,
`normalize_to_aether_events`, `status_map`, typed `not_configured` response,
audit/health hooks. Adapters are import-safe and offline by default.

## Canonical data model

Shared contract `packages/shared/payment-rails.ts`, Pydantic mirrors in
`models.py`, durable stores backed by migration `20260709_payment_rails.py`
(`payment_funding_sessions`, `payment_provider_events`,
`payment_provider_accounts`, `payment_deposit_addresses`,
`payment_virtual_accounts`, `payment_reconciliation_records`,
`payment_rails_audit`):

- **FundingSession** — one normalized record per observed flow; idempotent on
  `(tenant_id, idempotency_key)`; carries provider/provider_detail, flow_type,
  rail, canonical status + provider_status + status_reason, actor attribution
  (human/agent/org + journey/campaign), source/destination asset/chain/amount,
  fees, safe provider references, tx hash, sanitized metadata.
- **Status ordering** — `initiated < submitted < pending < completed/failed/
  refunded/cancelled`; final states never regress; downgrade attempts are
  recorded in `metadata.downgrade_attempts` and audited, never applied.
- **Provider event dedupe** — unique `(tenant_id, provider, provider_event_id)`;
  exact redelivery (same raw hash) → `ignored_duplicate`; same id with a
  different hash → `rejected` + audited.
- **ReconciliationRecord** — states `sdk_only | provider_only | matched |
  stale | conflict | ignored_duplicate`, with sanitized field-level
  discrepancies; stale after 24h without provider confirmation. The
  `sdk_only → stale` transition is produced only by the periodic sync worker
  (below) — provider-driven reconciliation always has a provider view and can
  never yield it, so without the worker an unconfirmed session would never age.
- **PaymentRailHealth** — per-provider configured/enabled state, webhook
  verified/rejected 24h, session counts, reconciliation matched rate,
  conflicts, `healthy|degraded|not_configured|error`.

## Canonical events

Sessions imply existing canonical commerce events — **no new event types**:
`payment_initiated` on first observation; `payment_completed` on
completed/refunded; `payment_failed` on failed/cancelled. Each type is
emitted at most once per session (tracked in `metadata.emitted_canonical`)
onto the validated-events bus (`SDK_EVENTS_VALIDATED`) with
rail/provider/session properties — the same pipeline `/v1/batch` feeds; no
parallel ingestion API.

## Background sync worker

`sync_worker.py` registers a supervised `payment_rail_sync` worker
(`services/runtime/specs.py`, gated on `AETHER_PAYMENT_RAILS_ENABLED`). Webhook
handling never runs on a timer, so two open sessions would otherwise never
resolve: one whose provider sends no terminal webhook, and one SDK-only session
no provider confirms. Each cycle (default 15 min) the worker sweeps all open
(non-final) funding sessions, tenant-scoped and best-effort:

1. **Provider-truth pull** — for each configured, polling-capable provider
   present among a tenant's open sessions, calls
   `PaymentRailsService.status_sync`. This is offline-safe by construction: an
   unconfigured tenant, a local process, or a provider with no live polling
   endpoint performs no network IO and processes no records — the pull is a
   no-op, never a fabricated advance.
2. **Staleness reconciliation** — re-runs reconciliation for every still-open
   session, reusing the stored record's `last_source` so the view selection is
   identical to its origin. This is the only producer of the
   `sdk_only → stale` transition.
3. **Card-linked Gold** — when `AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED` is on,
   materializes card-linked Gold rollups per tenant (the periodic hook the
   card-linked plane otherwise lacked).

Counters: `payment_rail_sync_cycle_total`,
`payment_rail_sync_session_scanned_total`,
`payment_rail_sync_provider_pulled_total`,
`payment_rail_sync_transitioned_total`, `payment_rail_sync_error_total`,
`card_linked_gold_materialized_total`.

## Routes

Public webhooks (HMAC-verified per adapter; tenant from `X-Aether-Tenant-ID`;
prefix already in feature-gate PUBLIC_PATH_PREFIXES):

```txt
POST /v1/integrations/webhooks/payment-rails/{provider}
```

Tenant (authed; service-catalog entry "Rail-Watch" → `/v1/integrations/providers/*`):

```txt
POST /v1/integrations/providers/{provider}/sync
GET  /v1/integrations/providers/{provider}/status
GET  /v1/integrations/providers/payment-rails/sessions
GET  /v1/integrations/providers/payment-rails/sessions/{session_id}
GET  /v1/integrations/providers/payment-rails/reconciliation
GET  /v1/integrations/providers/payment-rails/health
```

Kyber operator (operator-gated; aggregates only, no raw tenant payloads):

```txt
GET /v1/admin/kyber/payment-rails/health
GET /v1/admin/kyber/payment-rails/{tenant_id}
```

Profile360: `GET /v1/profile/{entity_id}/payment-rails` — per-entity funding
rollup (counts by provider/rail/status/reconciliation + per-currency native
totals; mixed currencies are never summed into one scalar).

## Secrets and privacy

- Tenant-scoped webhook/API secrets live in the BYOK key vault
  (`payment_privy`, `payment_stripe_onramp`, `payment_coinbase`,
  `payment_moonpay`, `payment_bridge`); never persisted in provider records,
  returned by APIs, logged, or exposed in UI (masked identifiers only).
- Recursive sensitive-key redaction (card/PAN/CVV/account/routing/IBAN/
  KYC/SSN…) applies to every parsed provider payload before persistence;
  Bridge account references survive only as `****`-masked suffixes.
- Currency safety: unknown cost stays unknown; the UI and Profile360 report
  native amounts per currency and never merge currencies into one scalar.

## Frontend

- Aether `/payment-rails`: provider health cards, funding sessions table with
  provider/status/reconciliation filters, session detail drawer with
  attribution + reconciliation discrepancies, sync action, not-configured/
  empty/error/flag-off states, and the copy "Aether observes payment rails —
  it does not execute or settle payments, or custody funds."
- Kyber `/payment-rails` (flag `enablePaymentRails`): fleet health per
  provider, tenant drill-down diagnostics.

## Feature flags (default OFF)

`AETHER_PAYMENT_RAILS_ENABLED` (master; mounts routes),
`AETHER_PROVIDER_PRIVY_ENABLED`, `AETHER_PROVIDER_STRIPE_ENABLED`,
`AETHER_PROVIDER_COINBASE_ENABLED`, `AETHER_PROVIDER_MOONPAY_ENABLED`,
`AETHER_PROVIDER_BRIDGE_ENABLED` (per-provider), `KYBER_PAYMENT_RAILS_ENABLED`.

## Testing

`BE/tests/payment_rails/` — 41 tests: adapter registry (exactly five; unknown
→ 404), status-map canonicality, HMAC verification, PII redaction, Privy
processor detail + deposit addresses, Coinbase partnerUserRef polling,
MoonPay AML rejection + buy/sell + fee summation, Bridge masked virtual
accounts + activity, canonical event implication + at-most-once emission,
duplicate delivery, final-state non-regression, reconciliation states,
tenant isolation, flag gating, Kyber operator permission, secret safety.
Frontend: aether payment-rails tests (93-suite green), kyber component tests
(115-suite green).

## Known limitations / non-goals

- **Observability is webhook-primary.** Live provider polling *fetch*
  (`_fetch_poll_records`) is an intentional per-provider seam: the base returns
  no records and no adapter implements a live HTTP fetch yet, so `status_sync`
  advances sessions only from operator/test-supplied provider records
  (`records=` injection) or when a verified provider polling endpoint +
  credential is later wired. The sync worker, staleness reconciliation, and the
  `records=` sync path are complete and tested; live polling fetch is not
  fabricated against unverified provider APIs.
- Reconciliation against SDK-side signals activates as SDK payment events
  arrive; provider-only sessions report `provider_only` until then.
- No payment execution, settlement, custody, refund initiation, or
  provider-account provisioning. No generic webhook receiver.

## Certification & readiness (staging-capstone)

The five adapters (Privy, Stripe onramp, Coinbase, MoonPay, Bridge) resolve to
`CREDENTIAL_WAITING` in the credentialless certification matrix
(`docs/_generated/adapter-certification-matrix.json`) — code-complete and
credential-gated, with no live provider validated in staging. To move a provider
toward live, follow
`docs/productization/staging-capstone/CREDENTIAL_WAITING_PROMOTION_GUIDE.md` and
capture evidence per `PILOT_EVIDENCE_GUIDE.md`. Operator triage lives in
`docs/runbooks/PAYMENT_RAILS_RUNBOOK.md`; credentialless recovery behaviour
(duplicate-webhook storm, idempotent worker restart) is pinned by
`tests/chaos/test_webhook_idempotency.py`.
