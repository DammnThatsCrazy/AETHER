---
title: Reward Enablement Demo — Web2 Rails (recommend_only + tenant_webhook)
slug: examples/reward-demo-web2
section: examples
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "8.10.0"
canonical_owner: platform@aether
estimated_read_minutes: 8
---

# Reward Enablement Demo — Web2 Rails

This walkthrough shows the end-to-end flow for verifying reward eligibility and
delivering a reward payload to a tenant system via webhook or manual recommendation.

**No-custody model**: Aether verifies eligibility and generates action payloads.
Your systems execute rewards. Aether never holds funds, sends payments, or
distributes rewards directly.

---

## Prerequisites

```bash
export API_KEY="ak_live_your_key_here"
export BASE="https://api.aether.io/v1"
```

---

## Step 1: Create a Campaign

```bash
curl -X POST "$BASE/rewards/campaigns" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Q3 Conversion Incentive",
    "description": "Reward users who complete a conversion event",
    "attribution_model": "last_touch",
    "default_rail": "recommend_only",
    "budget_policy": { "max_total_decisions": 5000 }
  }'
```

Response:
```json
{
  "data": {
    "id": "cmp_01abc...",
    "status": "active",
    "default_rail": "recommend_only"
  }
}
```

---

## Step 2: Add a Reward Rule

```bash
CAMPAIGN_ID="cmp_01abc..."

curl -X POST "$BASE/rewards/campaigns/$CAMPAIGN_ID/rules" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "First conversion reward",
    "event_types": ["conversion"],
    "min_attribution_weight": 0.4,
    "min_attribution_confidence": 0.6,
    "max_fraud_score": 30.0,
    "requires_consent_purposes": ["commerce"],
    "cooldown_seconds": 86400,
    "max_per_user": 1,
    "reward_amount": "10.00",
    "reward_currency": "USD",
    "reward_unit": "credit",
    "execution_mode": "recommend_only",
    "rail": "recommend_only"
  }'
```

---

## Step 3: Evaluate Eligibility

When a user triggers a `conversion` event, call evaluate to get an eligibility decision:

```bash
curl -X POST "$BASE/rewards/evaluate" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "conversion",
    "event_id": "evt_user123_conversion_20260614",
    "user_id": "user_123",
    "account_ref": "acc_123",
    "idempotency_key": "user_123:cmp_01abc:conversion:2026-06-14",
    "attribution_result_id": "attr_result_001",
    "fraud_decision_id": "fraud_decision_001",
    "consent_snapshot_id": "cs_001",
    "properties": { "amount": 49.99, "currency": "USD" }
  }'
```

**Eligible response** (Aether verifies eligibility — your system acts on this):
```json
{
  "data": {
    "eligible": true,
    "decision": "eligible",
    "decision_reason": "All gates passed",
    "execution_mode": "recommend_only",
    "rail": "recommend_only",
    "next_action": "retrieve_action_payload",
    "attribution": { "weight": 0.72, "confidence": 0.84, "model": "last_touch" },
    "fraud": { "score": 12.3, "decision": "approve" },
    "identity": { "user_id": "user_123", "confidence": 0.95 },
    "decision_id": "dec_01xyz...",
    "action_id": "act_01xyz..."
  }
}
```

**Blocked example** (no action needed — Aether blocked on fraud):
```json
{
  "data": {
    "eligible": false,
    "decision": "blocked_fraud",
    "denial_reason": "Fraud score 67.2 exceeds rule maximum 30.0"
  }
}
```

---

## Step 4: Retrieve the Action Payload

```bash
ACTION_ID="act_01xyz..."

curl -X GET "$BASE/rewards/actions/$ACTION_ID" \
  -H "Authorization: Bearer $API_KEY"
```

Response (recommend_only rail — your system reads and acts):
```json
{
  "data": {
    "id": "act_01xyz...",
    "rail": "recommend_only",
    "status": "ready",
    "payload": {
      "user_id": "user_123",
      "campaign_id": "cmp_01abc...",
      "rule_name": "First conversion reward",
      "reward_amount": "10.00",
      "reward_currency": "USD",
      "reward_unit": "credit",
      "eligible_at": "2026-06-14T12:00:00Z"
    }
  }
}
```

Your CRM or billing system reads this payload and issues the credit.
**Aether's role ends here.** Aether produced the verified eligibility decision;
your system executes the reward.

---

## Step 5 (Optional): Configure Tenant Webhook for Automatic Delivery

Instead of polling for action payloads, configure a webhook rail so Aether
delivers signed payloads to your system automatically.

```bash
curl -X POST "$BASE/rewards/rails" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "rail": "tenant_webhook",
    "enabled": true,
    "webhook_url": "https://your-system.example.com/webhooks/rewards",
    "signing_secret_ref": "vault://rewards/webhook-signing-secret"
  }'
```

Update your rule to use `tenant_webhook`:

```bash
RULE_ID="rule_01..."
curl -X PATCH "$BASE/rewards/rules/$RULE_ID" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "rail": "tenant_webhook", "execution_mode": "deliver" }'
```

**Webhook delivery headers** (your endpoint must verify these):
```
X-Aether-Signature: hmac-sha256=<hex>
X-Aether-Timestamp: 1718366400
X-Aether-Idempotency-Key: user_123:cmp_01abc:conversion:2026-06-14
Content-Type: application/json
```

Verify the signature using your `signing_secret`:
```python
import hmac, hashlib, time

def verify_aether_webhook(body: bytes, headers: dict, secret: str) -> bool:
    ts = headers.get("X-Aether-Timestamp", "")
    if abs(time.time() - int(ts)) > 300:
        return False  # reject stale webhooks
    expected = "hmac-sha256=" + hmac.new(
        secret.encode(), f"{ts}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, headers.get("X-Aether-Signature", ""))
```

---

## Step 6: Post Receipt (Optional)

Confirm delivery back to Aether for audit trail completeness:

```bash
curl -X POST "$BASE/rewards/receipts" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "action_payload_id": "act_01xyz...",
    "rail": "tenant_webhook",
    "execution_mode": "deliver",
    "external_execution_id": "your-system-tx-id-001",
    "status": "confirmed",
    "receipt_payload": { "credited_at": "2026-06-14T12:05:00Z", "amount": "10.00" }
  }'
```

---

## Idempotency

If the same event fires twice, the second call returns the existing decision:

```bash
# Second call with the same idempotency_key returns the first decision
curl -X POST "$BASE/rewards/evaluate" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{ ..., "idempotency_key": "user_123:cmp_01abc:conversion:2026-06-14" }'
# → same decision_id, same action_id, no duplicate reward
```
