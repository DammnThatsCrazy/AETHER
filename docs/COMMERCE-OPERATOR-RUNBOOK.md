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
