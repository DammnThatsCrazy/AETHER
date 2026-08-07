---
title: Fraud Network Architecture
slug: architecture/fraud-network-architecture
section: architecture
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "9.0.0"
source_files:
  - Backend Architecture/aether-backend/services/fraud_networks/
  - Backend Architecture/aether-backend/services/flow_trace/
  - Backend Architecture/aether-backend/services/risk_overlay/
  - Backend Architecture/aether-backend/repositories/repos.py
  - packages/shared/graph-contract.ts
last_synced_commit: "99da74c0"
---

# Fraud Network Architecture

## Component Interaction

```
┌───────────────────────────────────────────────────────────┐
│  Kyber Operator Frontend                                  │
│  /fraud-networks    /fraud-networks/:id    /flow-trace    │
│  FraudNetworksPage  FraudNetworkDetailPage  FlowTracePage  │
└──────────────────────────┬────────────────────────────────┘
                           │ REST
┌──────────────────────────▼────────────────────────────────┐
│  FastAPI — fraud_networks.routes / flow_trace.routes      │
│  risk_overlay.routes / investigation.routes               │
└──┬──────────┬──────────────────┬───────────────────────────┘
   │          │                  │
   ▼          ▼                  ▼
FraudNetwork  FlowTrace      Investigation
Repository    Repository     Repository
   │          │                  │
   └──────────┴──────────────────┘
                │
         ┌──────▼──────────────────────────┐
         │  GraphClient                    │
         │  add_vertex / add_edge          │
         │  VertexType.FRAUD_NETWORK       │
         │  VertexType.FLOW_TRACE          │
         │  EdgeType.MEMBER_OF_FRAUD_NETWORK│
         │  EdgeType.PART_OF_FLOW_TRACE    │
         └─────────────────────────────────┘
                │
         ┌──────▼───────────────┐
         │  EventProducer       │
         │  Topic.FRAUD_NETWORK_CREATED  │
         │  Topic.FLOW_TRACE_COMPLETED  │
         └──────────────────────┘
```

---

## Data Flow — Fraud Network Build

```
POST /v1/fraud/networks/build
  │
  ├─ Load transfers (TransferRepository.find_many)
  ├─ Load wallets (WalletRepository.find_many)
  ├─ Load sessions (from transfer attributes)
  │
  ├─ Run 8 detectors (pure sync functions)
  │     detect_shared_device, detect_shared_ip,
  │     detect_wallet_cluster, detect_circular_transfers,
  │     detect_split_merge, detect_reward_farming,
  │     detect_agentic_delegation_abuse, detect_commerce_abuse
  │
  ├─ Build evidence refs (build_evidence_refs)
  ├─ Classify member roles (assign_roles_to_members)
  ├─ Score cluster risk (score_cluster_risk)
  ├─ Score confidence (score_confidence)
  │
  ├─ Persist FraudNetwork → FraudNetworkRepository
  ├─ Persist FraudNetworkMembers → FraudNetworkMemberRepository
  ├─ Persist FraudNetworkEdges → FraudNetworkEdgeRepository
  │
  ├─ Project to graph (try/except — non-fatal)
  │     upsert_vertex(FRAUD_NETWORK)
  │     add_edge(MEMBER_OF_FRAUD_NETWORK) for each member
  │
  └─ publish(Topic.FRAUD_NETWORK_CREATED)
```

---

## Data Flow — Flow Trace

```
POST /v1/flow-trace/trace
  │
  ├─ Instantiate FlowTraceEngine(TransferRepository)
  ├─ engine.trace(tenant_id, anchor_entity_id, direction, max_hops)
  │     BFS traversal
  │     cycle detection
  │     sink / source / aggregation identification
  │     pattern tagging
  │
  ├─ score_trace() and score_path() for each path
  │
  ├─ Persist FlowTrace → FlowTraceRepository
  ├─ Persist FlowTracePaths → FlowTracePathRepository
  │
  ├─ Project to graph (try/except)
  │     upsert_vertex(FLOW_TRACE)
  │     add_edge(PART_OF_FLOW_TRACE) for each node
  │     add_edge(FLOW_PATH_NEXT) for adjacent path nodes
  │
  └─ publish(Topic.FLOW_TRACE_COMPLETED)
```

---

## Graph Schema

### New Vertex Types

| VertexType | Description |
|---|---|
| `FraudNetwork` | A detected fraud cluster |
| `FlowTrace` | A BFS traversal result |
| `RiskOverlay` | A snapshot graph overlay |

### New Edge Types (16)

| EdgeType | Layer | Description |
|---|---|---|
| `MEMBER_OF_FRAUD_NETWORK` | H2H | Entity belongs to a fraud network |
| `HAS_RISK_ROLE` | H2H | Entity has a classified risk role |
| `SCORED_AS_RISKY` | H2H | Entity scored above threshold |
| `SUPPORTED_BY_EVIDENCE` | H2H | Network supported by evidence ref |
| `PART_OF_FLOW_TRACE` | H2H | Entity is a node in a flow trace |
| `FLOW_PATH_NEXT` | H2H | Adjacent nodes in a path |
| `HAS_SOURCE` | H2H | Trace has a source node |
| `HAS_SINK` | H2H | Trace has a sink node |
| `HAS_CONTROLLER` | H2H | Orchestrator → controlled entity |
| `USES_MULE` | H2H | Entity uses a mule |
| `LINKED_BY_DEVICE` | H2H | Entities share a device fingerprint |
| `LINKED_BY_IP` | H2H | Entities share an IP address |
| `LINKED_BY_WALLET` | H2H | Entities share a wallet address |
| `LINKED_BY_AGENT` | A2A | Agents linked via attribution |
| `LINKED_BY_DELEGATION` | H2A | Human delegates to agent |
| `ATTACHED_TO_CASE` | H2H | Network/trace attached to a case |

---

## Tenant Isolation Guarantees

1. **Repository layer**: All `find_many` calls filter by `tenant_id`
2. **Route layer**: `request.state.tenant.tenant_id` injected into all queries; cross-tenant access raises `ForbiddenError`
3. **Graph layer**: Vertex and edge creation uses the authenticated tenant's entity IDs; graph projection is wrapped in try/except and failure is non-fatal (does not expose cross-tenant data)
4. **Event layer**: Every published event carries `tenant_id` in the payload
5. **Evidence refs**: Generated only from the tenant's own transfer and session data

---

## Repository Classes (6 new)

| Class | Table | Primary Methods |
|---|---|---|
| `FraudNetworkRepository` | fraud_networks | create, get, list_by_tenant, update_status |
| `FraudNetworkMemberRepository` | fraud_network_members | create, list_by_network, list_by_entity |
| `FraudNetworkEdgeRepository` | fraud_network_edges | create, list_by_network |
| `FlowTraceRepository` | flow_traces | create, get, list_by_tenant |
| `FlowTracePathRepository` | flow_trace_paths | create, list_by_trace |
| `RiskOverlaySnapshotRepository` | risk_overlay_snapshots | create, get, list_by_tenant |

---

## Additive-Only Guarantee

No existing files were deleted or had code removed. All new endpoints are mounted conditionally on feature flags. The existing fraud evaluation (`/v1/fraud/evaluate`), flows (`/v1/flows/*`), and investigation endpoints are unchanged.
