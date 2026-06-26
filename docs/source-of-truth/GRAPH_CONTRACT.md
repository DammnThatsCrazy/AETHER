---
title: Intelligence Graph Contract
slug: source-of-truth/graph-contract
section: source-of-truth
visibility: internal
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/shared/graph/graph.py
  - Backend Architecture/aether-backend/shared/graph/relationship_layers.py
  - packages/shared/graph-contract.ts
canonical_owner: graph@aether
last_synced_commit: fae02a9
---
# Intelligence Graph Contract

Canonical definition of the four-layer Intelligence Graph. This file is the
single source of truth for vertex types, edge types, relationship layer
classification, consent requirements, tenant isolation rules, and observability
requirements.

All backend Python code, frontend TypeScript code, and generated docs must
agree with this contract. Validators run in CI (`make ci-check`).

---

## 1. Relationship Layers

The graph has exactly four relationship layers:

| Layer | Abbreviation | Direction | Description |
|-------|-------------|-----------|-------------|
| Human-to-Human | **H2H** | Human ↔ Human | Identity graph: merges, referrals, clusters, behavioral similarity |
| Human-to-Agent | **H2A** | Human → Agent | Delegation, configuration, ownership, supervision |
| Agent-to-Human | **A2H** | Agent → Human | Notifications, recommendations, result delivery, escalations |
| Agent-to-Agent | **A2A** | Agent ↔ Agent/Service/Protocol | Orchestration, hiring, payments, trust propagation |

**Every edge type must map to exactly one of these four layers.**

---

## 2. Canonical Vertex Types

| Vertex Type | Layer(s) | Description |
|------------|---------|-------------|
| `User` | H2H, H2A, A2H | Human actor |
| `Session` | H2H | User browsing/app session |
| `Device` | H2H | Physical device |
| `DeviceFingerprint` | H2H | Browser/device fingerprint |
| `IPAddress` | H2H | Network address |
| `Location` | H2H | Geographic location |
| `Email` | H2H | Email address identity signal |
| `Phone` | H2H | Phone number identity signal |
| `Wallet` | H2H, A2A | Blockchain wallet address |
| `IdentityCluster` | H2H | Probabilistic identity merge cluster |
| `Company` | H2H | Organization entity |
| `PageView` | H2H | Page or screen view event |
| `Event` | H2H | SDK-tracked behavioral event |
| `Agent` | H2A, A2H, A2A | Autonomous agent instance |
| `Service` | H2A, A2A | Exposed agent capability or external service |
| `Campaign` | H2A | Marketing/outreach campaign |
| `Contract` | A2A | On-chain smart contract |
| `Protocol` | A2A | DeFi/infrastructure protocol |
| `Payment` | A2A | Payment event record |
| `ActionRecord` | A2A | On-chain or agent action log entry |

---

## 3. Canonical Edge Types by Layer

### H2H — Human-to-Human Edges

| Edge Type | From | To | Description |
|-----------|------|----|-------------|
| `HAS_SESSION` | User | Session | User owns session |
| `VIEWED_PAGE` | User | PageView | User viewed page |
| `TRIGGERED_EVENT` | User | Event | User triggered event |
| `USED_DEVICE` | User | Device | User used device |
| `BELONGS_TO` | User | Company | User belongs to company |
| `RESOLVED_AS` | User | IdentityCluster | Identity resolution result |
| `ENRICHED_BY` | User | User | Enrichment from external source |
| `HAS_FINGERPRINT` | User | DeviceFingerprint | User has device fingerprint |
| `SEEN_FROM_IP` | User | IPAddress | User seen from IP |
| `LOCATED_IN` | User | Location | User located in region |
| `HAS_EMAIL` | User | Email | User has email address |
| `HAS_PHONE` | User | Phone | User has phone number |
| `OWNS_WALLET` | User | Wallet | User owns wallet |
| `MEMBER_OF_CLUSTER` | User | IdentityCluster | User in identity cluster |
| `SIMILAR_TO` | User | User | Probabilistic similarity edge |
| `IP_MAPS_TO` | IPAddress | Location | IP resolves to location |

### H2A — Human-to-Agent Edges

| Edge Type | From | To | Description |
|-----------|------|----|-------------|
| `LAUNCHED_BY` | Agent | User | Agent was launched by user |
| `DELEGATES` | User | Agent | User delegates scope to agent |
| `INTERACTS_WITH` | User | Agent | User interacts with agent |
| `ATTRIBUTED_TO` | Agent | User | Agent action attributed to launching user |

### A2H — Agent-to-Human Edges

| Edge Type | From | To | Description |
|-----------|------|----|-------------|
| `NOTIFIES` | Agent | User | Agent notifies user |
| `RECOMMENDS` | Agent | User | Agent recommends action to user |
| `DELIVERS_TO` | Agent | User | Agent delivers result to user |
| `ESCALATES_TO` | Agent | User | Agent escalates issue to user for approval |
| `HAS_RECOMMENDATION` | Agent | User | Agent has pending recommendation for user |
| `SUPPORTED_BY` | Agent | User | Agent is supervised/supported by user |
| `SELECTED_BY` | Agent | User | Agent action was selected by user review |

### A2A — Agent-to-Agent Edges

| Edge Type | From | To | Description |
|-----------|------|----|-------------|
| `PAYS` | Agent | Agent/User | Agent pays another agent or user |
| `CONSUMES` | Agent | Service | Agent consumes a service |
| `HIRED` | Agent | Agent | Agent hires another agent |
| `DEPLOYED` | Agent | Contract | Agent deployed smart contract |
| `CALLED` | Agent | Contract | Agent called contract method |
| `COMPOSED_WITH` | Agent | Service | Agent composed with service |
| `UPGRADED` | Agent | Agent | Agent upgraded another agent |
| `GOVERNED_BY` | Agent | Protocol | Agent governed by protocol |
| `DEPENDS_ON` | Agent | Service | Agent depends on service |
| `PERFORMED_ACTION` | Agent | ActionRecord | Agent performed an action |
| `EXECUTED_AS` | ActionRecord | Agent | Action executed as agent |
| `PRODUCED` | Agent | ActionRecord | Agent produced action record |
| `UPDATES_CONFIDENCE_FOR` | Agent | Agent | Agent updates trust/confidence of another |

---

## 4. Tenant Isolation Requirements

Every vertex and edge **must** carry a `tenant_id` field unless explicitly
classified as `global` (operator-only, never exposed through tenant routes).

| Requirement | Enforcement |
|-------------|-------------|
| All tenant-graph reads filtered by `tenant_id` at the GraphClient layer | `GraphClient.get_neighbors`, `GraphClient.get_edges` scope by tenant |
| Cross-tenant traversal is forbidden | `GraphTraversalEngine` enforces tenant scope |
| Kyber global graph views require `operator` permission | Backend middleware check on `/v1/admin/kyber/graph/*` |
| Aether tenant routes return only tenant-scoped data | `_require_read` + `tenantId` mismatch → 403 |
| Path search cannot cross tenants | `shortest_path` and `temporal_bfs` respect `tenant_id` |

---

## 5. Consent Requirements

| Layer | Consent Purpose Required |
|-------|--------------------------|
| H2H (identity resolution) | `analytics` |
| H2A (agent delegation) | `agent` |
| A2H (agent notifications) | `agent` |
| A2A (economic/agent ops) | `agent` |

Graph mutations for H2A, A2H, A2A edges must verify the `agent` consent
purpose before writing. Revocation of `agent` consent must cascade to remove
or suppress related edges.

---

## 6. Feature Flag Requirements

Graph layer activation is gated by environment variables (all default `false`):

| Flag | Layer(s) | Description |
|------|---------|-------------|
| `IG_RELATIONSHIP_LAYERS` | H2H, H2A, A2H, A2A | Master toggle for all relationship layer tracking |
| `IG_AGENT_LAYER` | H2A, A2H, A2A | Agent behavioral tracking |
| `IG_COMMERCE_LAYER` | A2A | Payment/hire tracking |
| `IG_ONCHAIN_LAYER` | A2A | On-chain action ingestion |
| `IG_X402_LAYER` | A2A | x402 micropayment capture |

---

## 7. Replayability Requirements

All graph mutations must be:
- Sourced from Silver/Gold lake tier events (deterministic replay)
- Recorded in the mutation ledger with `event_id`, `tenant_id`, `layer`, `edge_type`
- Replayable by `tenant_id`, `entity_id`, `event_id`, time window, and layer
- Idempotent — replaying the same event must produce the same graph state

---

## 8. Observability Requirements per Layer

| Metric | H2H | H2A | A2H | A2A |
|--------|-----|-----|-----|-----|
| Edge count | ✓ | ✓ | ✓ | ✓ |
| Node count by vertex type | ✓ | ✓ | ✓ | ✓ |
| Mutation success/rejection rate | ✓ | ✓ | ✓ | ✓ |
| Cross-tenant sentinel (must be 0) | ✓ | ✓ | ✓ | ✓ |

---

## 9. Aether Tenant Visibility Rules

Tenant-facing routes (`/v1/graph/*`) expose:
- Tenant-scoped graph topology
- Layer classification on edges
- Own-tenant overlay scores (layer coverage, health)

Tenant-facing routes **never** expose:
- Other tenants' data
- Global graph health aggregates
- Operator-level mutation internals
- Cross-tenant growth metrics

---

## 10. Kyber Operator Visibility Rules

Operator routes (`/v1/admin/kyber/graph/*`) expose:
- Global graph health aggregates (requires `operator` permission)
- Per-tenant graph health (requires `operator` permission)
- Layer coverage across all tenants
- Mutation queue health and replay lag
- Cross-tenant leakage sentinel metrics
- Failed graph mutations (requires `operator` permission)

Operator routes **never** expose raw PII or tenant-specific event payloads
unless explicitly scoped to that tenant's operator-approved access.
