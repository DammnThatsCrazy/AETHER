---
title: Commerce Operator Runbook
slug: operations/commerce-runbook
section: operations
visibility: I
audience: [ops]
status: stable
since_version: "8.8.0"
source_files:
  - Backend Architecture/aether-backend/services/x402/
canonical_owner: commerce@aether
estimated_read_minutes: 3
toc_depth: 3
last_synced_commit: 94cdfaf
---
# Commerce Operator Runbook

## 1. Stuck approval (past SLA)

**Symptom:** Kyber Mission → Approval Backlog Summary shows items near/past SLA.

**Steps:**
1. Kyber Command → Commerce Subsystem → Approval Backlog.
2. Filter queue by `status=assigned` or `status=pending`.
3. If unassigned: `POST /v1/approvals/{id}/assign` with new approver.
4. If assigned but idle: escalate with `POST /v1/approvals/{id}/decide action=escalate`.
5. Sweeper runs via `GET /v1/diagnostics/commerce/stuck-approvals` — marks expired items.

## 2. Failed settlement

**Symptom:** Diagnostics page shows settlement failure rate climbing, or explicit `commerce.settlement.failed` event.

**Steps:**
1. Fetch failure list: `GET /v1/diagnostics/commerce/stuck-approvals` (reuses sweep endpoint; extend with settlement-specific if needed).
2. Inspect: `GET /v1/x402/settlements/{id}` returns state + `failure_reason` + attempts.
3. Retry via `SettlementTracker.retry(tenant_id, settlement_id)` or equivalent API.
4. If facilitator is unhealthy: update health via internal API, select alternate facilitator on retry.

## 3. Facilitator outage

**Symptom:** `avg_latency_ms` climbing, `success_rate` dropping on Command Facilitator panel.

**Steps:**
1. Update facilitator health: internal API or via registry method.
2. Control plane auto-routes around unhealthy facilitators on next `authorize_payment()`.
3. If all facilitators down: verification falls back to local verification per chain.

## 4. Duplicate payment detected

**Symptom:** `commerce_duplicate_payment_detected_total` metric rising, or Kyber alert.

**Steps:**
1. Idempotency store returns cached result → client sees deterministic replay.
2. If malicious replay: revoke approval via `POST /v1/approvals/{id}/revoke`.
3. Revoke entitlement: `POST /v1/entitlements/{id}/revoke`.

## 5. Reconciliation drift (graph vs lake)

**Symptom:** Nightly job reports drift > 0.

**Steps:**
1. Inspect drift report: (extension point, see `services/x402/commerce_store.py` patterns).
2. Replay silver into graph via `economic_mutations` rebuild helpers.
3. Verify drift resolved.

## 6. Override review

**Symptom:** `COMMERCE_APPROVAL_OVERRIDE` audit entry surfaces.

**Steps:**
1. Kyber Review → filter by `is_override=true`.
2. Validate override reason, approver scope.
3. If unauthorized: escalate to admin.

## 7. Evidence export

For audit/compliance:
```bash
curl /v1/approvals/{id}/evidence → JSON bundle
curl /v1/x402/explain/{challenge_id} → full lifecycle trace
```

Both responses include all context needed for SOC2/GDPR evidence.

## 8. Managing budget policies

Budget policies short-circuit the approval queue: an over-cap spend is denied
at policy time before an approval request is ever issued. Manage them via
three endpoints on the commerce router (require `x402:write` for mutation,
`x402:read` for query):

```bash
# Create or replace a per-subject policy
curl -X POST /v1/x402/policies/budget \
  -d '{"subject_id":"agent-42","subject_type":"agent",
       "daily_cap_usd":100,"monthly_cap_usd":1000,"per_transaction_cap_usd":50}'

# List tenant-wide policies
curl /v1/x402/policies/budget

# Get one subject's active policy
curl /v1/x402/policies/budget/agent-42
```

**When to use it:** a runaway agent or compromised key is racking up
charges. Set a tight `per_transaction_cap_usd` first (immediate
limitation), then a tighter `daily_cap_usd` for cumulative protection.
Re-issue the same `POST` with new caps to replace; there's no separate
PATCH/DELETE — an absent policy means no caps.
