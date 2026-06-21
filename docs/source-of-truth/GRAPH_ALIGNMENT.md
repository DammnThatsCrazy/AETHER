---
source_files:
  - Backend Architecture/aether-backend/shared/graph/graph.py
  - Backend Architecture/aether-backend/shared/graph/relationship_layers.py
  - Backend Architecture/aether-backend/shared/graph/write_validator.py
  - Backend Architecture/aether-backend/shared/graph/edge_properties.py
  - Backend Architecture/aether-backend/services/lake/graph_mutations.py
canonical_owner: graph@aether
last_synced_commit: 401f9bd
---

# Graph Alignment

Which SDK events feed which Intelligence Graph layer. Vertex/edge definitions
live in `Backend Architecture/aether-backend/shared/graph/graph.py`. Event→
mutation wiring lives in `services/lake/graph_mutations.py`.

## Layer L0 — on-chain (`IG_ONCHAIN_LAYER`)

| SDK event | Creates / updates | Notes |
|---|---|---|
| `wallet` | `Wallet`, `IDENTIFIED_BY` edge to User | connect/disconnect |
| `transaction` | `ActionRecord`, `Contract`, `CALLED` edge | confirmed txs |
| `contract_action` | `Contract`, `CALLED` edge | optional explicit form |

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

- **H2H** edges (identity similarity, household clustering) are created by
  the backend identity resolver from SDK signals (`anonymous_id`, `device_id`,
  fingerprint, wallet, email, phone). The SDK does not emit H2H events.
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

See [`docs/ECONOMIC-OBSERVABILITY.md`](../ECONOMIC-OBSERVABILITY.md).

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
| `provenance` | string | Source system or service (e.g., `"lake_graph_mutations"`) |
| `valid_from` | ISO-8601 | Timestamp from which this edge is valid |
| `confidence` | float 0–1 (as string) | Write certainty; use `"1.0"` for deterministic writes |

H2A and A2H edges additionally require:

| Property | Type | Description |
|---|---|---|
| `consent_purpose` | string | Purpose string from the tenant consent record |

## Activation flags

Event emission is always allowed client-side. Backend processing into the
graph is gated by `IG_AGENT_LAYER`, `IG_COMMERCE_LAYER`, `IG_X402_LAYER`,
`IG_ONCHAIN_LAYER` environment variables (see
`Backend Architecture/aether-backend/config/settings.py`). When a layer is
off, the event is still stored in the lake but does not mutate the graph.
