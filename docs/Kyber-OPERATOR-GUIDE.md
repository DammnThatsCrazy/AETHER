---
title: Kyber Operator Guide
slug: kyber/operator-guide
section: kyber
visibility: I
audience: [ops, dev-senior, architect]
status: stable
since_version: "8.9.0"
canonical_owner: kyber@aether
estimated_read_minutes: 20
---

# Kyber Operator Guide

Kyber is the Aether operator UI. This guide covers day-to-day workflows for
platform operators managing the Agentic Commerce control plane.

## Access & Roles

| Role | Description | Default |
|---|---|---|
| `observer` | Read-only across all pages | Production default |
| `reviewer` | Can approve/reject in Review queue | Assigned to designated reviewers |
| `operator` | Full read + commerce write (resources, policies, budgets) | Platform ops |
| `admin` | Full access including tenant settings | Senior ops only |

Production defaults to `observer`. Elevated roles require explicit assignment via
the identity service.

## Page Reference

### Mission

**Purpose:** Real-time platform health snapshot.

**Panels:** Treasury balance + runway, spend timeline, revenue cards per service,
fee elimination gauge, approval backlog count.

**Key actions:**
- Monitor treasury runway — alert if < 7 days
- Review spend rate trends
- Jump to blocked approvals from the backlog count

**Required scope:** `commerce:read`

### Live

**Purpose:** Real-time event stream and payment flow monitor.

**Panels:** Rail breakdown (chain/asset volume), settlement status strip (pending/
verifying/settled/failed counts), facilitator performance matrix.

**Key actions:**
- Watch for failed/disputed settlement counts rising
- Check facilitator health if success rate drops below 95%
- Use settlement status strip to drill into stuck states

**Required scope:** `commerce:read`

### Review

**Purpose:** Approval queue. The primary workspace for designated reviewers.

**Panels:** Approval queue (filterable by status/priority), approval detail card,
decision form, evidence panel, escalation router, graph impact preview.

**Standard review workflow:**
1. Open Review page — queue shows `pending` and `escalated` items
2. Select an approval — review resource, requester, amount, policy decision
3. Open Evidence panel to see the full policy rationale and payment requirement
4. Enter a decision reason (required)
5. Click Approve / Reject / Escalate
6. Escalation routes to the next assignee in the escalation chain

**Override decisions:** Check "mark as override" to bypass normal policy gates.
Override decisions are audit-logged with elevated visibility.

**Required scope:** `approvals:read` (view), `commerce:approve` (decide)

### Diagnostics

**Purpose:** System health and reconciliation monitoring.

**Panels:** Commerce KPI dashboard, circuit breaker states, verification failures,
settlement timeouts (stuck flow detection), approval expirations, duplicate payment
detection, reconciliation drift (intents without settlements).

**Stuck settlement workflow:**
1. Navigate to Diagnostics → Settlement Timeouts
2. Identify settlements stuck in `pending` or `verifying` > 5 minutes
3. Check facilitator health for the associated chain
4. If facilitator is healthy, retry via Command → Settlements
5. If facilitator is unhealthy, escalate to facilitator operator

**Required scope:** `admin` (system diagnostics), `commerce:read` (commerce diagnostics)

### Command

**Purpose:** Administrative control over commerce subsystems.

**Panels:** Treasury panel (balance + runway), resource registry, policy management,
facilitator registry, budget policies, tenant settings.

**Registering a new resource:**
1. Command → Resources → Register Resource
2. Fill: name, class, path pattern, owner service, price, accepted assets/chains
3. Set `approval_required: true` (mandatory at GA)
4. Set `entitlement_ttl_seconds` appropriate to access pattern
5. Submit — resource is immediately active

**Updating facilitator routing:**
1. Command → Facilitators → select facilitator
2. View health metrics (success rate, latency)
3. Disable or re-order routing priority as needed

**Required scope:** `commerce:admin`

### Entities

**Purpose:** Per-entity (agent/user) commerce profiles.

**Panels:** Entitlement list (active/expired/revoked), entitlement detail, reuse
history, cluster economics view.

**Revoking an entitlement:**
1. Entities → search agent/user
2. Entitlements tab → select active entitlement
3. Click Revoke → enter reason → confirm
4. Revocation is immediate and audit-logged

**Required scope:** `entitlements:read` (view), `entitlements:write` (revoke)

### Noesis (Graph Operator UI)

**Purpose:** Interactive graph exploration. Navigate payment lifecycle graphs,
policy decision trees, and economic clusters.

**Commerce-relevant graph queries:**
- `trace_payment_lifecycle(challenge_id)` — full lifecycle from challenge to fulfillment
- `agent_entitlements(agent_id)` — active entitlements per agent
- `policy_chain(resource_id)` — which policies fire for a resource
- `approval_backlog(tenant_id)` — queue size and latency

**Required scope:** `x402:read`

### Lab

**Purpose:** Deterministic replay and scenario testing.

**Commerce scenarios available:**
- `features/settlement` — pending/failed/disputed settlement scenarios
- `features/approvals` — full approval queue with all status variants
- `features/entitlements` — active/expired/revoked/SIWX-bound entitlements
- `features/resources` — resource class scenarios

**Running a Lab scenario:**
1. Lab → select "Commerce Control Plane"
2. Choose scenario (e.g. "Settlement Failure")
3. Step through — each step shows graph writes and events emitted
4. Replay decisions and verify outcomes match expected graph state

**Required scope:** read-only. Deterministic Lab scenarios are test/replay tools;
they are not a fallback data source for Kyber operational routes.

## Common Operator Workflows

### Stuck Approval Response

1. Diagnostics → Approval Expirations to find expired approvals
2. Review → filter by `expired` or `escalated`
3. For expired: no action needed (TTL-expired approvals do not block new requests)
4. For stuck escalated: use Escalation Router to re-route to available reviewer
5. Monitor: after approval decision, settlement should proceed within 30 s

### Facilitator Outage Response

1. Live → Facilitator Performance — identify failing facilitator (success rate < 90%)
2. Command → Facilitators → Disable the failing facilitator
3. Routing automatically falls back to next facilitator in priority order
4. Monitor settlement success rate recovers
5. Once facilitator recovers: re-enable and re-add to routing

### Treasury Low Runway Response

1. Mission → Treasury Panel shows runway < 7 days warning
2. Review spend rate — identify top-spend agents/services in Mission
3. Command → Budget Policies — temporarily tighten per-agent daily caps
4. Coordinate treasury top-up with finance team
5. Re-enable normal budget policies once runway > 30 days

### Reconciliation Drift Response

See [Support & Debug Guide](SUPPORT-DEBUG-GUIDE.md) for the full playbook.

## Production Defaults

| Setting | Default | Notes |
|---|---|---|
| `approval_required` | `true` | All resources at GA |
| Kyber default role | `observer` | Elevated roles require explicit grant |
| Budget per-agent | 10k pending approvals max | Platform hard cap |
| Entitlement hard cap | open entitlements per tenant | Advisory; enforced at review |
| Facilitator timeout | 30 s per attempt | Configurable per facilitator |
| Approval TTL | 1 hour | Expired approvals are re-requestable |
