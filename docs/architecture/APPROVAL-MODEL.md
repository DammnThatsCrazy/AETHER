---
title: Agentic Commerce — Approval Model
slug: ai/approval-model
section: architecture
visibility: P
audience: [architect, dev-senior]
status: stable
since_version: 0.1.0
source_files: [services/api/value/x402/commerce_routes.py]
canonical_owner: commerce@aether
estimated_read_minutes: 4
toc_depth: 3
source_hashes:
  "services/api/value/x402/commerce_routes.py": "sha256:73a9f03a50f3a43b6d17cc2f9e118aec853f6a5d6d2a3c29c1348f66d94d00c4"
---
# Agentic Commerce — Approval Model

**Locked requirement:** Mandatory approval on ALL spend classes at Day-1 GA.

## States

```
pending → assigned → (approved | rejected | escalated | expired | revoked)
escalated → assigned | approved | rejected | expired
approved → revoked
```

## SLA defaults

| Priority | SLA |
|---|---|
| critical | 5 minutes |
| high | 15 minutes |
| normal | 1 hour |
| low | 4 hours |

Configurable per tenant via `ApprovalService` SLA_SECONDS dict.

## Enforcement layers

1. **Policy engine** (`policies.py`): marks `requires_approval=True` for every spend class via `mandatory_approval_all_spend_classes` active rule.
2. **Control plane** (`control_plane.py:apply_decision`): rejects payment authorization if approval status is not `approved`.
3. **Authorization flow** (`control_plane.py:authorize_payment`): hard-fails if `approval.status != APPROVED`.
4. **Graph writes** (`economic_mutations.py`): `GRANTS_ACCESS_TO` edge never written without approval reference.

## Operator actions (Kyber Review page)

| Action | Permission | Result |
|---|---|---|
| View queue | `approvals:read` (canViewAll) | Filtered/sorted queue |
| Assign | `approvals:write` | Sets `assigned_to` |
| Approve | `commerce:approve` (canApprove) | Status → `approved`, emits `commerce.approval.approved` |
| Reject | `commerce:approve` (canApprove) | Status → `rejected` |
| Escalate | `approvals:write` | `POST /v1/approvals/{id}/escalate` — status → `escalated`, appends to escalation chain |
| Graph impact preview | `approvals:read` | `GET /v1/approvals/{id}/preview` — returns projected graph-edge delta before committing |
| Revoke (post-approval) | `approvals:write` | Status → `revoked`, cancels downstream entitlement |
| Replay (Lab) | `approvals:read` | Deterministic re-evaluation, no mutation |
| View evidence | `approvals:read` | Returns approval + policy decision + requirement |

## Override

`apply_decision(action="approve", is_override=True)` bypasses a policy-denied request.
Requires `commerce:admin`. Always audited with `COMMERCE_APPROVAL_OVERRIDE` action.
Event emitted with `is_override=true` flag.

## Budget policies

Per-subject spend caps that feed the policy engine. Operators (or admins) can
create budget policies via three endpoints on the commerce router:

| Endpoint | Permission | Purpose |
|---|---|---|
| `POST /v1/x402/policies/budget` | `x402:write` | Create / replace a budget policy for an agent or user |
| `GET  /v1/x402/policies/budget` | `x402:read`  | List active budget policies for the tenant |
| `GET  /v1/x402/policies/budget/{subject_id}` | `x402:read` | Get one subject's active policy |

Each policy carries `daily_cap_usd`, `monthly_cap_usd`, and
`per_transaction_cap_usd` (defaults: 100 / 1000 / 50). The policy engine
consults these caps when evaluating a payment authorization; an over-cap
spend is denied at policy time, *before* the approval queue, so operators
don't see requests they couldn't ever approve.

## No self-service opt-down

Mandatory approval is not configurable by a setting or a route. `PolicyEngine`
enforces it for every spend class (`DEFAULT_APPROVAL_REQUIRED_ALL = True` in
`services/api/value/x402/policies.py`). The one way to turn it off is the engine's
`set_mandatory_approval(False)`, which no production code calls (only tests do);
whether to remove that setter is a decision for the commerce owner. A
`commerce_approval_required_all` setting used to be documented here; no code read it,
so it was retired.

## Evidence bundle contents

Returned by `GET /v1/approvals/{id}/evidence`:
- Full approval request record
- Policy decision with rationale + active rules
- Payment requirement (challenge)

Used by Kyber Review → Commerce Approvals tab for operator inspection before decision.
