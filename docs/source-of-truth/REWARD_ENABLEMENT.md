# Reward Enablement (A6)

A6 is Aether's attribution-verified reward enablement feature. It produces eligibility
decisions, signed proofs, and action payloads that tenant-owned systems consume to execute
rewards. Aether is not a custodian or payer. See `REWARD_NO_CUSTODY_MODEL.md`.

## What Aether Does

```
SDK / webhook / connector event
  ↓
Canonical event validation
  ↓
Identity + wallet/account resolution
  ↓
Journey reconstruction + attribution resolution
  ↓
Fraud / bot / Sybil / abuse evaluation
  ↓
Tenant reward policy engine
  ↓
Eligibility decision
  ↓
Reward action payload
  ↓
Execution mode
    ├── recommend_only
    ├── manual_approval
    ├── tenant_webhook
    ├── scheduled_batch / manual_export
    ├── web2_loyalty_api (beta)
    ├── internal_credit (beta)
    └── onchain_claim_proof
  ↓
Tenant executes reward through their own rails
  ↓
Aether stores audit trail + execution outcome
```

## Supported Rails

| Rail | Status | Notes |
|---|---|---|
| `recommend_only` | Production | No delivery; eligibility surfaced via API/UI |
| `manual_approval` | Production | Requires operator approve/reject before action |
| `manual_export` | Production | CSV/JSON batch export for tenant processing |
| `tenant_webhook` | Production | Signed HMAC payload delivered to tenant URL |
| `onchain_claim` | Production (EVM) | EIP-191 proof for tenant-owned EVM contract |
| `onchain_claim` (SVM/NEAR/etc.) | Beta | Proof format defined; not production-verified |
| `stripe_credit` | Beta | Action payload only; tenant executes |
| `loyalty_points` | Beta | Action payload only; tenant executes |
| `coupon` | Beta | Action payload only; tenant executes |
| `internal_credit` | Beta | Action payload only; tenant executes |
| `x402_credit` | Beta | Action payload only; tenant executes |

## Attribution Requirements

- Non-local environments require a valid `attribution_result_id` linked to a result from
  the attribution service, OR `recommend_only_without_attribution=true` in the evaluate request.
- Minimum attribution weight and confidence are configurable per rule.
- Supported models: first_touch, last_touch, linear, time_decay, position_based, data_driven,
  actor_weighted, exposure_aware, and custom channel models.
- Override is supported only if tenant policy explicitly allows `attribution_weight_override`.
  Every override is audit-logged.

## Fraud Requirements

- Non-local environments require a valid `fraud_decision_id` OR manual-review fallback.
- Fraud decisions: `approve` → eligible path; `review` → `needs_review`; `reject`/`block` → `blocked_fraud`.
- Configurable per-rule: `max_fraud_score` threshold.
- Signals: bot_probability, velocity, device_fingerprint, vpn_detected, proxy_detected,
  geo_anomaly, impossible_travel, self_referral, wallet_age, multi_accounting, etc.

## Consent Requirements

- Reward evaluation must honor the consent model defined in `CONSENT_MODEL.md`.
- Before generating a decision, the engine checks:
  - `marketing` consent for attribution-based rewards
  - `web3` consent for on-chain rewards
  - `commerce` consent where payment data is used
  - `agent` consent where agent actions trigger eligibility
- Missing consent → `blocked_consent` decision; no proof or payload generated.
- Consent snapshot ID is recorded in every decision for audit.

## Identity Requirements

- Supports Web2 user (no wallet), Web3 wallet (no account), mixed identity.
- If `requires_wallet=true` and wallet missing → `blocked_wallet_binding`.
- If `wallet_binding_confidence` below rule threshold → `blocked_wallet_binding` or `needs_review`.
- Identity cluster ID links across devices and accounts without merging for reward purposes
  unless existing identity rules allow it.

## Data Models

See migration `20260613_reward_enablement.py` for full schema. Key tables:

- `reward_campaigns` — tenant-scoped campaigns
- `reward_rules` — rules within campaigns
- `reward_eligibility_decisions` — durable, explainable eligibility decisions
- `reward_action_payloads` — generated payloads per eligible decision
- `reward_proofs` — cryptographic proofs for on-chain claim
- `reward_execution_receipts` — tenant-reported execution outcomes
- `reward_audit_log` — append-only audit record
- `tenant_reward_rail_configs` — per-tenant rail configuration
- `tenant_contract_registry` — tenant-registered smart contracts

## API Contracts

See `BACKEND-API.md` and `API-REFERENCE.md` for full endpoint listing.

Base path: `/v1/rewards`

- Campaigns: CRUD + pause/resume/archive
- Rules: CRUD per campaign
- Evaluate: `POST /v1/rewards/evaluate` and `/evaluate/batch`
- Decisions: GET by ID, list with filters
- Action payloads: GET, approve, reject, deliver, cancel
- Proofs: GET, verify, revoke
- Receipts: POST, GET
- Rails: CRUD + verify + disable

## Event Requirements

Events that can trigger reward eligibility (from `EVENT_REGISTRY.md`):

- `conversion` — primary reward trigger
- `journey_completed` — milestone reward
- `wallet` — wallet connection event
- `transaction` — on-chain transaction
- `contract_action` — contract function call
- `payment_initiated`, `payment_completed` — commerce rewards
- `x402_payment` — x402 payment reward

## Local vs Staging vs Production

| Behavior | local | staging | production |
|---|---|---|---|
| In-memory campaigns | ✓ | ✗ | ✗ |
| Test oracle signer key | ✓ | ✗ | ✗ |
| Fake contract address | ✓ | ✗ | ✗ |
| Attribution required | ✗ | ✓ | ✓ |
| Fraud decision required | ✗ | ✓ | ✓ |
| Durable storage required | ✗ | ✓ | ✓ |
| Contract registry required | ✗ | configurable | ✓ |

## Release Status

**EVM on-chain claim proof**: Production-ready (pending external smart contract audit).
**Web2 rails**: Production-ready.
**Non-EVM proofs**: Beta.
**Beta rails** (stripe_credit, loyalty_points, coupon, internal_credit, x402_credit): Beta.

## Known Limitations

1. Non-EVM VM proof formats (SVM, Bitcoin, MoveVM, NEAR, TVM, Cosmos) are defined but not
   production-verified. Marked `beta` in rail configs.
2. Budget enforcement is observational in Aether; hard enforcement is on the tenant's contract
   or webhook system.
3. Attribution service requires `ML_SERVING_URL` or `ATTRIBUTION_SERVICE_URL` for full
   multi-touch model support. Heuristic fallback is available for local environments only.
4. No external security audit of `AnalyticsRewards.sol` has been completed. Recommended
   before production deployment with real funds.
