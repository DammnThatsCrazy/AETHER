# Reward Policy Engine

The reward policy engine evaluates eligibility decisions by applying a chain of gates to
each event. Every decision is explainable — every denial includes a reason.

## Decision Values

| Decision | Eligible | Meaning |
|---|---|---|
| `eligible` | true | All gates passed; reward action payload generated |
| `ineligible` | false | No matching rule found for this event |
| `needs_review` | false | Fraud score in review range; routed to manual review |
| `blocked_fraud` | false | Fraud decision is reject or block |
| `blocked_consent` | false | Required consent purpose not granted |
| `blocked_budget` | false | Tenant-declared budget policy exceeded |
| `blocked_cap` | false | Per-user claim cap reached |
| `blocked_cooldown` | false | Within cooldown period since last eligible decision |
| `blocked_identity` | false | Identity confidence below rule threshold |
| `blocked_wallet_binding` | false | Wallet binding confidence below threshold or wallet required but absent |
| `no_matching_rule` | false | No rule matched the event type in any active campaign |

## Gate Evaluation Order

Gates are evaluated in this order (fail-fast):

1. **Campaign active** — campaign status must be `active`
2. **Campaign time window** — current time within `start_time` and `end_time`
3. **Rule active** — rule `active=true`
4. **Event type** — `event_type` in rule's `event_types` list
5. **Required channel** — `channel` matches `required_channel` (if set)
6. **Required properties** — all keys in `required_properties` match event payload
7. **Consent** — all `requires_consent_purposes` granted in `consent_snapshot`
8. **Identity confidence** — `identity_confidence` ≥ `identity_confidence_min`
9. **Wallet binding** — if `requires_wallet=true`, wallet present and `wallet_binding_confidence` ≥ threshold
10. **Fraud decision** — `fraud_decision.decision` maps to approve/review/reject/block
11. **Attribution weight** — `attribution_weight` ≥ `min_attribution_weight`
12. **Attribution confidence** — `attribution_confidence` ≥ `min_attribution_confidence`
13. **Cooldown** — time since last eligible decision for this user+campaign ≥ `cooldown_seconds`
14. **Per-user cap** — user's total eligible decisions for this campaign < `max_per_user`
15. **Total uses cap** — total eligible decisions for this campaign < `max_total_uses` (if set)
16. **Budget policy** — tenant-declared budget not exceeded (observational)
17. **Idempotency** — duplicate `idempotency_key` returns existing decision, not a new one

## Fraud Score Mapping

| fraud_decision.decision | Policy result |
|---|---|
| `approve` | Eligible path continues |
| `review` | `needs_review` unless rule `max_fraud_score` covers the score |
| `reject` | `blocked_fraud` |
| `block` | `blocked_fraud` |

## Decision Object

```json
{
  "eligible": true,
  "decision": "eligible",
  "decision_reason": "Rule matched: referral_first_purchase",
  "denial_reason": null,
  "campaign_id": "cmp_...",
  "rule_id": "rule_...",
  "execution_mode": "manual_approval",
  "rail": "tenant_webhook",
  "attribution": {
    "result_id": "attr_...",
    "weight": 0.82,
    "confidence": 0.94,
    "model": "last_touch"
  },
  "fraud": {
    "decision_id": "fraud_...",
    "score": 6.2,
    "decision": "approve"
  },
  "identity": {
    "cluster_id": "cluster_...",
    "confidence": 0.91,
    "wallet_binding_confidence": 0.96
  },
  "next_action": {
    "type": "create_reward_action_payload"
  }
}
```

## Idempotency Behavior

- `idempotency_key` is per-tenant; the same key from two different tenants is independent.
- Duplicate key within the same tenant returns the existing `reward_eligibility_decisions`
  record and its associated action payload/proof, without creating new records.
- Idempotency key should be set to the source event ID when available.
- In local mode, idempotency is enforced in-memory per session.
- In non-local environments, enforced via unique constraint on `(tenant_id, idempotency_key)`.

## Priority and Multi-Rule Campaigns

- Rules within a campaign are evaluated in ascending `priority` order (lowest number = highest priority).
- First matching rule wins.
- Multiple campaigns are evaluated independently; the first eligible result across campaigns
  is returned (ordered by campaign `created_at`).
- A future configuration option `strategy: all_matching` (not yet implemented) would return
  all matching rules across campaigns.

## Budget Policy

Budget is observational in Aether. The `budget_policy` JSON on a campaign specifies:

```json
{
  "max_total_reward_amount": 50000,
  "reward_unit": "USD",
  "track_spend": true
}
```

When `track_spend=true`, Aether tracks the sum of `reward_amount` from eligible decisions
and blocks new eligibility when the sum exceeds `max_total_reward_amount`. This is advisory —
hard enforcement happens in the tenant's contract or webhook system.

## Policy Engine Environment Guards

| Check | local | staging/production |
|---|---|---|
| Attribution result required | No | Yes (unless `recommend_only_without_attribution=true`) |
| Fraud decision required | No | Yes |
| Consent snapshot required | No | Yes (if any rule has `requires_consent_purposes`) |
| Durable decision storage | No (in-memory) | Yes (PostgreSQL) |
| Idempotency key required | No | Yes |
