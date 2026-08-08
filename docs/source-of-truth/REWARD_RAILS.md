# Reward Rails

A reward rail is the delivery mechanism through which a reward action payload reaches
the tenant's system for execution. Aether generates the payload; the tenant executes it.

## Rail Overview

The canonical, machine-readable classification is generated from
`services/rewards/rail_matrix.py` into
`docs/_generated/reward-rail-matrix.json` and enforced by
`scripts/release/check_reward_rail_matrix.py` (bidirectional agreement between
adapters, the matrix, and the outbox senders). Tiers:

| Rail | Delivery | Who Executes | Tier |
|---|---|---|---|
| `recommend_only` | None | Tenant (manual) | Production |
| `manual_approval` | None until approved | Tenant operator | Production |
| `manual_export` | CSV/JSON download | Tenant batch process | Production |
| `tenant_webhook` | HTTPS POST to tenant URL (durable outbox) | Tenant webhook handler | Production |
| `onchain_claim` | Proof returned in payload | User or tenant dApp | Production (EVM) |
| `internal_credit` | Double-entry internal ledger (durable outbox) | Aether internal ledger (no custody) | Production |
| `stripe_credit` | Idempotent Stripe customer-balance credit (durable outbox) | Tenant's Stripe key via credential authority | Sandbox (live key = external) |
| `x402_credit` | x402 credit grant via commerce control plane | No-custody credit ledger | Explicit beta (sandbox) |
| `loyalty_points` | — | — | Intentionally unsupported (needs provider partner) |
| `coupon` | — | — | Intentionally unsupported (needs provider partner) |

## recommend_only

- Produces an eligibility recommendation with campaign, rule, and reward metadata.
- No payload delivered outside Aether's API.
- Tenant reads decisions via `GET /v1/rewards/decisions` or Aether tenant app.
- Status transitions: `created` → `ready`.
- Use case: A/B testing reward programs before activating delivery.

## manual_approval

- Produces an action payload that remains in `pending_approval` status.
- Operator or tenant admin must approve via `POST /v1/rewards/actions/{id}/approve`.
- After approval, status moves to `ready` (or `delivered` if rail auto-delivers on approval).
- Rejection via `POST /v1/rewards/actions/{id}/reject` moves status to `rejected`.
- Every approval/rejection is audit-logged.
- Use case: High-value rewards requiring human review before execution.

## manual_export

- Produces a row in the batch export dataset for the campaign.
- Tenant downloads via `GET /v1/rewards/actions?rail=manual_export&status=ready&format=csv`.
- Status: `created` → `ready` (immediately); `delivered` (after tenant marks exported).
- Use case: Weekly payout runs, loyalty point allocations, creator payouts.

## tenant_webhook

- Aether delivers a signed JSON payload to the tenant's configured webhook URL.
- Signing: HMAC-SHA256 of the payload body using the tenant's webhook signing
  secret, resolved from the **durable credential authority** at the narrow send
  site (`services/rewards/webhook_secret.py`). A submitted `signing_secret` is
  dual-written into the authority (provider `tenant_webhook`, slot
  `webhook_signing_secret`, domain `rewards`) and replaced by a `secret_ref`
  before the rail config is persisted — plaintext never reaches the JSONB row,
  the durable outbox job, an audit record, or an API response. Rotation keeps a
  bounded overlap window (active + previous) so in-flight deliveries verify
  across a rotation. Resolution is fail-closed: no active credential ⇒ the
  delivery is not signed with an empty key, it fails and is retried/dead-lettered.
- Headers sent:
  - `X-Aether-Signature: hmac-sha256=<hex>` — signature for verification
  - `X-Aether-Timestamp: <unix_seconds>` — timestamp for replay protection
  - `X-Aether-Idempotency-Key: <key>` — deduplication key
  - `Content-Type: application/json`
- Tenant must reject webhooks where `|now - timestamp| > 300` seconds.
- Tenant must reject webhooks with invalid signature.
- Aether retries up to `REWARD_WEBHOOK_MAX_RETRIES` times with exponential backoff.
- Failed deliveries after max retries are dead-lettered with status `dead_lettered`.
- Webhook payload schema:

```json
{
  "event": "reward.action.ready",
  "idempotency_key": "...",
  "tenant_id": "tenant_...",
  "action_id": "act_...",
  "decision_id": "dec_...",
  "campaign_id": "cmp_...",
  "rule_id": "rule_...",
  "rail": "tenant_webhook",
  "reward": {
    "amount": "25",
    "unit": "USD",
    "currency": "USD",
    "type": "store_credit",
    "metadata": {}
  },
  "recipient": {
    "user_id": "user_...",
    "account_ref": "acct_...",
    "email_hash": "sha256:..."
  },
  "attribution": {
    "model": "last_touch",
    "weight": 0.82,
    "channel": "referral"
  },
  "created_at": "2026-06-13T00:00:00Z"
}
```

- Note: PII (plain email, phone, name) is not included in webhook payloads unless tenant
  config explicitly allows and consent permits. Use hashed identifiers.

## onchain_claim

- Generates a cryptographic proof (EIP-191 or EIP-712) signed by Aether's oracle key.
- Proof is returned in the action payload for the tenant dApp or user to submit on-chain.
- The tenant's smart contract verifies the oracle signature and transfers reward tokens.
- Aether never submits the transaction (no-custody model).
- Tenant dApp submits claim; tenant contract validates; tenant contract transfers tokens.
- After claim, tenant or chain watcher submits receipt via `POST /v1/rewards/receipts`.
- See `REWARD_PROOFS.md` for proof format and lifecycle.
- Configuration requires `tenant_contract_registry` entry.

## Native rails and intentionally-unsupported rails

`internal_credit` (production), `stripe_credit` (sandbox), and `x402_credit`
(explicit beta) are **native, deliverable** rails: they dispatch through the
same durable outbox as `tenant_webhook`, resolving the tenant's credential
from the credential authority at the narrow send site (fail-closed without it).

- `internal_credit` posts a durable, idempotent double-entry credit (no
  custody; provable end-to-end in-repo).
- `stripe_credit` performs an idempotent Stripe customer-balance credit through
  the tenant's own Stripe key (provider `stripe_credit`, slot `server_api_key`);
  live-mode activation requires a live tenant key (external).
- `x402_credit` records a no-custody x402 credit grant (sandbox-only at release).

`loyalty_points` and `coupon` are **intentionally unsupported** in this release
(they need a designated provider partner — a commercial + integration external
action). `POST /v1/rewards/rails` **refuses** to configure them (HTTP 422), so
they can never be presented as usable.

## Rail Configuration

Configure rails via `POST /v1/rewards/rails`:

```json
{
  "rail": "tenant_webhook",
  "enabled": true,
  "webhook_url": "https://rewards.example.com/webhook",
  "secret_ref": "secret/aether_webhook_hmac_key",
  "config": {
    "timeout_ms": 10000,
    "max_retries": 3,
    "retry_backoff_multiplier": 2
  }
}
```

Verify rail configuration via `POST /v1/rewards/rails/{id}/verify`. This sends a test
delivery to confirm connectivity.

## Delivery Status Transitions

```
created → pending_approval (manual_approval rail)
        → ready (recommend_only, manual_export)
        → queued → processing → delivered (tenant_webhook)
                              → failed → dead_lettered
        → cancelled
        → expired
```

## Observability

Metrics exposed:
- `rewards_actions_created_total{rail, tenant_id}`
- `rewards_actions_delivered_total{rail, tenant_id}`
- `rewards_actions_failed_total{rail, tenant_id, reason}`
- `rewards_webhook_delivery_latency_ms{tenant_id}`
- `rewards_queue_depth{rail}`
- `rewards_dead_letter_count{rail}`
