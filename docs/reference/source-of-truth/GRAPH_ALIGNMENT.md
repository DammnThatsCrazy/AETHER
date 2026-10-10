---
title: Graph Alignment
slug: source-of-truth/graph_alignment
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
source_files:
  - services/api/shared/graph/graph.py
  - services/api/shared/graph/relationship_layers.py
  - services/api/shared/graph/write_validator.py
  - services/api/shared/graph/edge_properties.py
  - services/api/shared/graph/mutation_gateway.py
  - services/api/graph/onchain/action_recorder.py
canonical_owner: graph@aether
last_synced_commit: 401f9bd
---

# Graph Alignment

This map records graph-layer event relationships and current write-path
availability. Vertex/edge definitions live in
`services/api/shared/graph/graph.py`. The lake mutation module formerly
used for Silver/Gold projections has been removed. On-chain action writes now
use `GraphMutationGateway`. The legacy identity-resolution graph mutation
methods and the legacy engine have been deleted; only the cluster,
merge-approval, and batch routes remain, failing closed until a tenant-safe
compatibility path is implemented. The graph write-path validator reports no
remaining direct service/repository writers.

## Layer L0 — on-chain (`IG_ONCHAIN_LAYER`)

| SDK event | Creates / updates | Notes |
|---|---|---|
| `wallet` | No active mapping documented here | connect/disconnect event; no lake projection builder is present |
| `transaction` | No automatic SDK-to-graph mapping established here | The separate on-chain action route writes `ActionRecord` and, for infra/call actions, `Contract` or `DEPLOYED`/`CALLED` facts through the gateway |
| `contract_action` | No automatic SDK-to-graph mapping established here | An explicit on-chain action request uses the gateway; this SDK event alone is not a graph-write guarantee |

## Layer L2 — agent behavioral (`IG_AGENT_LAYER`)

| SDK event | Creates / updates |
|---|---|
| `agent_task` | `Agent`, `ActionRecord`, `PERFORMS_ACTION` |
| `agent_decision` | `ActionRecord` with decision metadata |
| `a2h_interaction` | A2H edges: `NOTIFIES`, `RECOMMENDS`, `DELIVERS_TO`, `ESCALATES_TO` |

## Layer L3a — commerce (`IG_COMMERCE_LAYER`)

| SDK event | Creates / updates |
|---|---|
| `payment_initiated` | `Payment` (status=initiated) |
| `payment_completed` | `Payment` (status=completed), `PAYS` edge |
| `payment_failed` | `Payment` (status=failed) |
| `approval_requested` | `ApprovalRequest` |
| `approval_resolved` | `ApprovalDecision`, links to request |
| `entitlement_granted` | `Entitlement`, `ENTITLEMENT` edge to Resource |
| `entitlement_revoked` | revoke marker on `Entitlement` |
| `access_granted` / `access_denied` | `AccessGrant` / audit edge |

The `rail` field on payment events selects the downstream processing path
(fiat/stripe/invoice/onchain/x402/internal_credit).

## Layer L3b — x402 (`IG_X402_LAYER`)

| SDK event | Creates / updates |
|---|---|
| `x402_payment` | `Payment` (rail=x402), economic graph snapshot |

## H2H / H2A / A2H / A2A

- **H2H** legacy similarity and household graph construction from SDK signals
  is unavailable. The old repository's unscoped mutation methods were removed;
  its cluster and batch API routes return 503. Canonical identity decisions
  and their governed graph projection live under `services/api/identity/identity/`.
  The SDK does not emit H2H graph events.
- **H2A** edges (user → agent) are derived from `agent_task` events that
  reference the originating user.
- **A2H** edges are directly emitted by `a2h_interaction`.
- **A2A** edges (agent → agent, agent → service) are backend-inferred from
  payment + task events. The SDK does not emit A2A directly.

## Economic Observability extensions

Defined in `packages/shared/economic.ts` and re-exported from `@aether/shared`.
All fields are **optional** and additive — no migration is required.

| Primitive                | Where it attaches                        |
|--------------------------|-------------------------------------------|
| `EconomicPayload`        | Optional `economic` block on any Action  |
| `Authorization`          | Optional `authorization` block on Action / Agent |
| `Handshake`              | New node — `Action → initiates → Handshake → resolves_to → Action` |
| `ResourceNode`           | New node — generic `campaign / ad_account / bank_account / api / model` |
| `flow_ref`, `interaction_mode`, `economic_involved`, `outcome` | Optional Relationship/edge fields |
| `EconomicState`          | Derived state — never persisted; computed via `aggregateEconomicState` |

See [`docs/architecture/ECONOMIC-OBSERVABILITY.md`](../../architecture/ECONOMIC-OBSERVABILITY.md).

## Required edge properties

Every edge written to the graph (local or Neptune) must carry the following
properties in `edge.properties`. Enforced by `GraphWriteValidator` (logged in
local/test, raised in Neptune mode). Helper: `build_edge_properties()` in
`shared/graph/edge_properties.py`.

| Property | Type | Description |
|---|---|---|
| `tenant_id` | string | Owning tenant identifier |
| `idempotency_key` | string | SHA-256 of `tenant:type:from:to[:source_event]` — use `make_edge_idempotency_key()` |
| `actor_kind` | `human` \| `agent` \| `system` | Who originated this write |
| `actor_id` | string | Identity of the actor (user ID, agent ID, or system name) |
| `schema_version` | string | Currently `"1"` |
| `provenance` | string | Source system or service (e.g., `"onchain:action_recorder"`) |
| `valid_from` | ISO-8601 | Timestamp from which this edge is valid |
| `confidence` | float 0–1 (as string) | Write certainty; use `"1.0"` for deterministic writes |

H2A and A2H edges additionally require:

| Property | Type | Description |
|---|---|---|
| `consent_purpose` | string | Purpose string from the tenant consent record |

## Activation flags

Event emission is allowed client-side. Backend graph writes depend on the
individual service and route behavior as well as feature flags; the on-chain
action route requires `onchain:write` and records through the gateway. The
legacy identity-resolution cluster, merge-approval, and batch routes return
503. The removed lake projection module no longer rebuilds graph state from
stored events.
