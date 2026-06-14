# Reward Rails

A reward rail is the delivery mechanism through which a reward action payload reaches
the tenant's system for execution. Aether generates the payload; the tenant executes it.

## Rail Overview

| Rail | Delivery | Who Executes | Production Status |
|---|---|---|---|
| `recommend_only` | None | Tenant (manual) | Production |
| `manual_approval` | None until approved | Tenant operator | Production |
| `manual_export` | CSV/JSON download | Tenant batch process | Production |
| `tenant_webhook` | HTTPS POST to tenant URL | Tenant webhook handler | Production |
| `onchain_claim` | Proof returned in payload | User or tenant dApp | Production (EVM) |
| `stripe_credit` | Action payload only | Tenant Stripe integration | Beta |
| `loyalty_points` | Action payload only | Tenant loyalty platform | Beta |
| `coupon` | Action payload only | Tenant coupon system | Beta |
| `internal_credit` | Action payload only | Tenant database | Beta |
| `x402_credit` | Action payload only | Tenant x402 system | Beta |

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
- Signing: HMAC-SHA256 of the payload body using the tenant's configured `signing_secret_ref`.
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

## Beta Rails Configuration

Beta rails (stripe_credit, loyalty_points, coupon, internal_credit, x402_credit) can be
configured via `POST /v1/rewards/rails` but returning `beta_unavailable` when delivery is
attempted. They generate action payloads that tenants can process manually or via export.

Rail config for a beta rail:
```json
{
  "rail": "stripe_credit",
  "enabled": false,
  "config": {
    "api_key_ref": "secret/stripe_key",
    "credit_object_type": "customer_balance"
  },
  "status": "beta_unavailable"
}
```

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
