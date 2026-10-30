---
title: Agentic Commerce — Approval Model
slug: ai/approval-model
section: architecture
visibility: P
audience: [architect, dev-senior]
status: stable
since_version: 0.1.0
source_files:
  - services/api/value/x402/commerce_routes.py
  - services/api/value/x402/commerce_models.py
  - services/api/value/x402/approvals.py
  - services/api/value/x402/commerce_store.py
  - services/api/actions/agent/user_agents.py
canonical_owner: commerce@aether
estimated_read_minutes: 4
toc_depth: 3
source_hashes:
  "services/api/actions/agent/user_agents.py": "sha256:dbe0d9bb0bc7fd83bc64fe628cc5c271d33024f22b8839c0cfd9fc0a5b47532a"
  "services/api/value/x402/approvals.py": "sha256:a91ab84affb2e46db240f218f428dd342539327abc1ce3e896cbc2a7ca523fd3"
  "services/api/value/x402/commerce_models.py": "sha256:50dbf80d7699ccdfcd5206d94a2dadc33ae73c1c06caac80da23e953320e282a"
  "services/api/value/x402/commerce_routes.py": "sha256:e9cbbefee1efb189141bace31cd793b551089e7263924046fc7846cbc51a55a8"
  "services/api/value/x402/commerce_store.py": "sha256:4edc09e2cd51b0a7eefbf0c12cb4894f389b4f01f4e66a1ffacf10d9c7bd46e9"
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

## Agent execution approval linkage

An x402 approval can be bound to one exact agent run with an `execution_id` and
`execution_action`. `POST /v1/x402/approval/request` accepts the action and the
server creates the execution ID. The approver must review the exact agent,
action, resource, and approved amount shown by the request. For a bound
approval, the decision route records the authenticated tenant user as the
decision actor; caller-supplied actor text is not accepted as attribution.
Execution-bound decisions also retain the server-recorded `commerce:approve`
check with the tenant, execution, approval, authenticated principal, and check
time. Workflow360 may expose that receipt with the decision evidence; it does
not establish effective agent access or replay historical policy inputs.

Each decision is retained as a typed commerce decision record and the approval
keeps a pointer to its latest decision. `POST /v1/agents/{agent_id}/execute`
with `approval_id` rechecks tenant, agent, action, resource, amount, current
approval status, and the exact latest decision before it records the run. A
revoked or mismatched approval is rejected. The subsequent delegation check
uses the request tenant and records that tenant with its decision. This linkage currently covers the
x402 commerce approval path; it does not make every agent action approval-bound
or prove that an external action occurred. The endpoint records admission and
run bookkeeping only; it does not invoke an agent tool or resource operation,
so the run row is not an invocation receipt.
