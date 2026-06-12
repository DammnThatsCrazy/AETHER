---
title: Support & Debug Guide — Agentic Commerce Incidents
slug: support/debug-guide
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: "8.9.0"
canonical_owner: backend@aether
estimated_read_minutes: 15
---

# Support & Debug Guide — Agentic Commerce Incidents

This guide provides incident runbooks for the most common commerce control plane
failures. For routine operator workflows see [Kyber Operator Guide](Kyber-OPERATOR-GUIDE.md).

## Diagnostic Entry Points

| Question | Endpoint |
|---|---|
| Is the commerce system healthy? | `GET /v1/diagnostics/commerce/health` |
| Which approvals are stuck? | `GET /v1/diagnostics/commerce/approval-expirations` |
| Which settlements are stuck? | `GET /v1/diagnostics/commerce/settlement-timeouts` |
| Are there duplicate payments? | `GET /v1/diagnostics/commerce/duplicate-payments` |
| Is there reconciliation drift? | `GET /v1/diagnostics/commerce/reconciliation-drift` |
| What happened in a payment? | `GET /v1/intelligence/commerce/lifecycle/{challenge_id}` |
| Which circuit breakers are open? | `GET /v1/diagnostics/circuit-breakers` |
| What errors are registered? | `GET /v1/diagnostics/errors` |

All diagnostic endpoints require `admin` or `commerce:read` scope.

---

## Runbook: Stuck Approval

**Symptom:** Approval request remains in `pending` or `escalated` state for > 15 minutes.

**Steps:**

1. **Identify the stuck approval:**
   ```http
   GET /v1/diagnostics/commerce/approval-expirations
   ```
   Or filter in Review page by `escalated` / check expiry timestamp.

2. **Check the escalation chain:**
   ```http
   GET /v1/approvals/{approval_id}
   ```
   Look at `escalation_chain` and `assigned_to`. Is the assignee active?

3. **Re-route to an available reviewer:**
   ```http
   POST /v1/approvals/{approval_id}/assign
   { "assignee_id": "ops_alice", "assigned_by": "ops_admin" }
   ```

4. **If no reviewer available, escalate to override:**
   ```http
   POST /v1/approvals/{approval_id}/decide
   { "action": "approve", "decided_by": "ops_admin",
     "reason": "Emergency override: reviewer unavailable", "is_override": true }
   ```

5. **Verify resolution:** Approval status transitions to `approved`; settlement
   should proceed within 30 seconds.

6. **Post-incident:** Review escalation chain configuration in Command → Policies.

---

## Runbook: Failed Settlement

**Symptom:** Settlement stuck in `failed` or `verifying` state.

**Steps:**

1. **Identify failed settlements:**
   ```http
   GET /v1/diagnostics/commerce/verification-failures?limit=50
   GET /v1/diagnostics/commerce/settlement-timeouts?timeout_seconds=300
   ```

2. **Get settlement details:**
   ```http
   GET /v1/x402/settlements/{settlement_id}
   ```
   Check `failure_reason`, `attempts`, `facilitator_id`, `chain`.

3. **Check facilitator health:**
   ```http
   GET /v1/x402/facilitators/{facilitator_id}/health
   ```
   If `health_status != "healthy"` or `success_rate < 0.9`:

4. **If facilitator outage:**
   - Disable the failing facilitator in Command → Facilitators
   - Routing falls back automatically
   - Retry settlement via `POST /v1/x402/settle` with the original `receipt_id`

5. **If on-chain failure (tx reverted):**
   - Check `tx_hash` on the relevant block explorer
   - If reverted due to gas: settlement system will retry with higher gas on next attempt
   - If reverted due to contract error: escalate to blockchain ops

6. **If max retries exceeded:**
   - Settlement enters `disputed` state
   - Requires manual reconciliation (see Reconciliation Drift runbook)

7. **Monitor:** Settlement `state` should transition to `settled` within 2 minutes
   of facilitator recovery.

---

## Runbook: Facilitator Outage

**Symptom:** Settlement success rate drops, facilitator health reports `unhealthy`.

**Steps:**

1. **Detect outage:**
   ```http
   GET /v1/x402/facilitators
   GET /v1/commerce/facilitators/performance
   ```
   Look for `success_rate < 0.9` or `health_status = "unhealthy"`.

2. **Disable failing facilitator:**
   ```http
   PATCH /v1/x402/facilitators/{facilitator_id}
   { "active": false }
   ```
   Routing automatically shifts to the next available facilitator.

3. **Verify fallback:** Run `GET /v1/x402/facilitators` — check next facilitator
   is `active: true` and `health_status: "healthy"`.

4. **Monitor settlement success rate** in Live → Facilitator Performance.
   Should recover to > 99% within 5 minutes.

5. **Process stuck settlements:**
   For each settlement in `failed` state from the outage window:
   ```http
   POST /v1/x402/settle
   { "receipt_id": "<receipt_id>" }
   ```

6. **Re-enable facilitator** once it reports healthy:
   ```http
   PATCH /v1/x402/facilitators/{facilitator_id}
   { "active": true }
   ```

7. **Post-incident:** Review `avg_latency_ms` trends. If chronic, consider
   adjusting facilitator priority order.

---

## Runbook: Reconciliation Drift

**Symptom:** Payment intents exist without corresponding settlement events.

**Steps:**

1. **Identify drifted intents:**
   ```http
   GET /v1/diagnostics/commerce/reconciliation-drift
   ```
   Returns `drifted_intents` — intents in non-terminal state with no settlement.

2. **For each drifted intent, get the lifecycle:**
   ```http
   GET /v1/intelligence/commerce/lifecycle/{challenge_id}
   ```
   Identify where in the lifecycle the flow stopped (`lifecycle_stage` field).

3. **If stuck at `challenged` (no authorization):**
   - Check if the corresponding approval expired
   - If yes: flow legitimately abandoned — mark intent as `expired` in DB
   - If no: investigate why authorization was not attempted after approval

4. **If stuck at `authorized` (no receipt):**
   - Payment was authorized but verification was never called
   - Retry: `POST /v1/x402/verify { "authorization_id": ..., "tx_hash": ... }`

5. **If stuck at `receipt_verified` (no settlement):**
   - Receipt exists but settlement FSM was not triggered
   - Retry: `POST /v1/x402/settle { "receipt_id": ... }`

6. **If stuck at `settled` (no entitlement):**
   - Settlement completed but entitlement was not minted
   - Investigate `EntitlementService.mint()` error logs
   - Manual mint may be required (ops-only procedure)

7. **Post-incident:** Check `duplicate-payments` endpoint to ensure retries did not
   create double-charges.

---

## Runbook: Override Review

**Symptom:** A `is_override: true` decision was made. Requires post-hoc review.

**Steps:**

1. **Find recent overrides:**
   ```http
   GET /v1/approvals?status=approved
   ```
   Filter for `is_override: true` in the response.

2. **Review each override:**
   ```http
   GET /v1/approvals/{approval_id}/evidence
   ```
   Verify the decision reason is legitimate and the approver was authorized.

3. **If override was unauthorized:**
   ```http
   POST /v1/approvals/{approval_id}/revoke
   { "revoked_by": "ops_admin", "reason": "Unauthorized override" }
   ```

4. **Check downstream impact:**
   - Was access already granted via the override entitlement?
   - If yes: revoke the entitlement
   ```http
   POST /v1/entitlements/{entitlement_id}/revoke
     ?reason=unauthorized_override&revoked_by=ops_admin
   ```

5. **Post-incident:** Review RBAC configuration. Override capability should only
   be available to `admin` role.

---

## Key Log Patterns

| Pattern | Meaning |
|---|---|
| `challenge.issued` | HTTP 402 issued for a protected resource |
| `approval.requested` | Approval request entered queue |
| `approval.approved/rejected/escalated` | Decision made |
| `settlement.completed` | On-chain settlement confirmed |
| `settlement.failed` | Settlement failed after max retries |
| `entitlement.granted` | Access entitlement minted |
| `entitlement.revoked` | Entitlement manually revoked |
| `access.granted` | Final access grant to protected resource |
| `circuit_breaker.opened` | Service circuit breaker tripped |

All events include `correlation_id`, `tenant_id`, and `challenge_id` for
cross-service correlation.

## Health Check Summary

| Passing | Warning | Critical |
|---|---|---|
| Settlement success rate > 99% | 95–99% | < 95% |
| Approval queue depth < 100 | 100–500 | > 500 |
| Facilitator latency < 500 ms avg | 500 ms–2 s | > 2 s |
| Treasury runway > 30 days | 7–30 days | < 7 days |
| Drift ratio < 0.1% | 0.1–1% | > 1% |
