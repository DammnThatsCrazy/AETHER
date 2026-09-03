---
title: Unified Intelligence Graph
slug: concepts/intelligence-graph
section: concepts
visibility: P
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.8.0"
source_files:
  - Backend Architecture/aether-backend/shared/graph/
  - docs/source-of-truth/GRAPH_ALIGNMENT.md
canonical_owner: graph@aether
estimated_read_minutes: 15
toc_depth: 3
last_synced_commit: "c19b048f"
---
# Unified On-Chain Intelligence Graph v8.12.0

## Overview

The Unified On-Chain Intelligence Graph extends the Aether platform with an 8-layer architecture for tracking human, agent, and protocol interactions across Web2, Web3, and autonomous agent workflows.

- **Additive extension** — all 11 ML models/scorers remain unchanged; no retraining required
- **Feature-flagged** — every layer activates independently via environment variables (all default to `false`)
- **GDPR + SOC 2 compliant** — 2 new consent purposes, DSR cascade for agent/payment vertices, 14 audit actions
- **Graph-native** — 6 new node types, 19 new edge types layered onto the existing Identity Graph
- **Lake-fueled** — graph mutations are driven by Silver/Gold lake tiers, not ad-hoc scripts

> **Infrastructure:** `GraphClient` auto-selects a backend at `connect()`: Neptune (via gremlinpython) when `NEPTUNE_ENDPOINT` is set; in-memory in `AETHER_ENV=local`; otherwise, in a non-local environment with no Neptune endpoint and `GRAPH_BACKEND=postgres` (the staging / production-lean default), the Postgres backend — `_PostgresGraphBackend` over the `graph_vertices` / `graph_edges` tables, whose observable semantics match the in-memory backend. A non-local environment with no usable backend (no Neptune, and no database pool for the declared Postgres backend) still fails closed with `RuntimeError`.

Tenant-scoped erasure is a first-class graph operation. The cleanup path uses
`GraphClient.delete_tenant_data(tenant_id)` and resolves both the canonical
`tenantId` and legacy `tenant_id` spellings. It removes owned vertices plus
tenant-tagged edges (including edges touching a shared endpoint) and fails
closed when the configured graph backend cannot complete the operation; system
vertices and unscoped edges are never selected.

## V1 Activation Guide

To enable the Intelligence Graph in staging/production:

```bash
# Enable graph layers (add to .env or deployment config)
IG_AGENT_LAYER=true       # L2: Agent behavioral tracking
IG_COMMERCE_LAYER=true    # L3a: Payment/hire tracking
IG_ONCHAIN_LAYER=true     # L0: On-chain action ingestion
IG_X402_LAYER=true        # L3b: x402 micropayment capture
IG_TRUST_SCORING=true     # Composite trust scoring
IG_BYTECODE_RISK=true     # Bytecode risk analysis
IG_RPC_GATEWAY=true       # Shared RPC infrastructure

# Required infrastructure
NEPTUNE_ENDPOINT=your-neptune-cluster.region.neptune.amazonaws.com
```

## Graph Mutation Path

Graph edges are created from lake data via deterministic mutation jobs:

```
Silver/Gold lake tiers
    ↓
graph_mutations.py
    ├── build_wallet_protocol_edges()   → INTERACTS_WITH
    ├── build_wallet_social_edges()     → RESOLVED_AS
    └── build_governance_edges()        → INTERACTS_WITH (governance)
    ↓
Neptune graph store
    ↓
Intelligence API
    ├── /v1/intelligence/wallet/{addr}/risk
    ├── /v1/intelligence/entity/{id}/cluster
    └── Trust/bytecode scoring
```

Graph can be rebuilt from lake state or incrementally updated.

A second, governed mutation path closes the "Gold is computed but never reaches
the graph" gap for semantic intelligence: the **semantic graph projector**
(`services/semantic_intelligence/graph_projector.py`) reads each tenant's
durable `gold_relationship_semantic_state` projections and writes one directed
`SEMANTIC_RELATES_TO` edge per relationship (`source_ref -> target_ref`) into
the graph **through the canonical `GraphMutationGateway`** — never a direct
graph write. See [Semantic relationship overlay](#semantic-relationship-overlay).

## Architecture Layers

| Layer | Name | Description | Key Components |
|-------|------|-------------|----------------|
| **L6** | Infrastructure Backbone | Single shared RPC gateway via QuickNode | Multi-chain RPC, x402 payment headers, rate limiting |
| **L0** | On-Chain Action Ingestion | Captures contract deployments, calls, and token transfers | `ActionRecord` schema, chain listener, bytecode indexer |
| **L1** | Human Behavioral | Existing Aether SDK v3.0 event pipeline | `identify()`, `track()`, `page()`, fingerprinting, consent |
| **L2** | Agent Behavioral | Autonomous agent lifecycle tracking | `registerAgent()`, task states, decision logs, ground truth |
| **L3a** | Commerce | Payment tracking, agent hiring, fee analysis | Payment records, hire events, fee elimination reports |
| **L3b** | x402 Interceptor | HTTP 402-based micropayment capture | Payment headers, economic graph edges, per-call cost tracking |
| **L3b+** | x402 Control Plane | Full commerce lifecycle — challenge → approval → settlement → entitlement | `ProtectedResourceRegistry`, `ApprovalService`, `SettlementTracker`, `EntitlementService` |
| **L4** | ML Intelligence | Scoring and anomaly detection | 9 existing models + Trust Score composite + Bytecode Risk scorer |
| **L5** | Unified Graph | Cross-layer relationship store | 18+ vertex types, 48+ edge types, Neptune (gremlinpython), Postgres (`graph_vertices`/`graph_edges`), or in-memory for local dev |

## Relationship Layers

### H2H (Human-to-Human)

This layer existed before the Intelligence Graph and remains unchanged.

- **Vertices:** `User`, `DeviceFingerprint`, `IPAddress`, `Email`, `Phone`, `Wallet`
- **Edges:** `HAS_FINGERPRINT`, `SEEN_FROM_IP`, `HAS_EMAIL`, `HAS_PHONE`, `OWNS_WALLET`
- **ML models used:** Identity Resolution (deterministic + probabilistic), Bot Detection, Intent Prediction

### H2A (Human-to-Agent)

Tracks delegation from humans to autonomous agents and attribution of agent actions back to the launching user.

- **Edges:** `LAUNCHED_BY` (user->agent), `DELEGATES` (user->agent+scope), `INTERACTS_WITH` (user<->agent)
- **Behaviors:** Delegation scope enforcement, reward passthrough to launching user, trust inheritance
- **Attribution:** All agent-generated events carry `originUserId` for analytics rollup

### A2H (Agent-to-Human)

Tracks agent-initiated interactions back to human users — the reverse direction of H2A. While H2A captures human delegation *to* agents, A2H captures agent-initiated contact *back to* humans.

- **Edges:** `NOTIFIES` (agent->user), `RECOMMENDS` (agent->user), `DELIVERS_TO` (agent->user), `ESCALATES_TO` (agent->user)
- **Behaviors:** Notification delivery, proactive recommendations, task result handoff, human-in-the-loop escalation
- **Privacy:** All A2H edges respect the `agent` consent purpose; users can revoke agent notification permissions

### A2A (Agent-to-Agent)

Captures orchestration, hiring, payments, and protocol composition between autonomous agents.

- **Edges:** `HIRED` (agent->agent), `PAYS` (agent->agent+amount), `CONSUMES` (agent->service), `DEPLOYED` (agent->contract), `CALLED` (agent->contract+method)
- **Behaviors:** Multi-hop hiring chains, payment splitting, SLA tracking
- **Protocol composition:** Agents consuming other agents' exposed services via x402 micropayments

## Graph Schema

`shared/graph/economic_schema.py` — `EconomicGraphSchema` declares all economic vertex and edge types (PAYMENT_REQUIREMENT, PAYMENT_AUTHORIZATION, SETTLEMENT, ENTITLEMENT, GRANTS_ACCESS_TO, etc.) used by L3b+. `shared/graph/graph_contract.py` — `GraphContract` is the authoritative Python schema registry; it mirrors the TypeScript `graph-contract.ts` and is the single source for vertex/edge type enumerations used by mutation services and tests.

### Node Types (6 new)

| Node Type | Description | Key Properties |
|-----------|-------------|----------------|
| `AGENT` | Autonomous agent instance | `agentId`, `ownerId`, `model`, `version`, `trustScore`, `registeredAt` |
| `SERVICE` | Exposed agent capability | `serviceId`, `agentId`, `endpoint`, `costPerCall`, `protocol` |
| `CONTRACT` | On-chain smart contract | `address`, `chain`, `deployer`, `bytecodeHash`, `riskScore`, `verified` |
| `PROTOCOL` | DeFi/infrastructure protocol | `protocolId`, `name`, `chain`, `tvl`, `category` |
| `PAYMENT` | Payment event (fiat or crypto) | `paymentId`, `from`, `to`, `amount`, `currency`, `method`, `x402` |
| `ACTION_RECORD` | On-chain action log entry | `actionId`, `agentId`, `chain`, `txHash`, `type`, `blockNumber` |

### Edge Types (17 new)

| Category | Edge | From -> To | Properties |
|----------|------|------------|------------|
| **H2A** | `LAUNCHED_BY` | Agent -> User | `timestamp`, `config` |
| **H2A** | `DELEGATES` | User -> Agent | `scope[]`, `expiresAt`, `revoked` |
| **H2A** | `INTERACTS_WITH` | User <-> Agent | `sessionId`, `channel`, `count` |
| **A2H** | `NOTIFIES` | Agent -> User | `content_summary`, `task_id`, `timestamp` |
| **A2H** | `RECOMMENDS` | Agent -> User | `content_summary`, `confidence`, `task_id` |
| **A2H** | `DELIVERS_TO` | Agent -> User | `task_id`, `content_summary`, `confidence` |
| **A2H** | `ESCALATES_TO` | Agent -> User | `task_id`, `content_summary`, `urgency` |
| **Economic** | `HIRED` | Agent -> Agent | `taskId`, `terms`, `sla` |
| **Economic** | `PAYS` | Agent/User -> Agent/User | `paymentId`, `amount`, `currency` |
| **Economic** | `CONSUMES` | Agent -> Service | `callCount`, `totalCost`, `lastCalledAt` |
| **Economic** | `EARNS_FROM` | Agent -> Service | `revenue`, `period` |
| **Protocol** | `DEPLOYED` | Agent -> Contract | `txHash`, `chain`, `blockNumber` |
| **Protocol** | `CALLED` | Agent -> Contract | `method`, `args_hash`, `txHash` |
| **Protocol** | `USES_PROTOCOL` | Agent -> Protocol | `frequency`, `volume` |
| **Action** | `PRODUCED` | Agent -> ActionRecord | `taskId`, `confidence` |
| **Action** | `REFERENCES` | ActionRecord -> Contract | `relationship` |
| **Action** | `TRIGGERED_BY` | ActionRecord -> ActionRecord | `causalChain`, `depth` |

## ML Intelligence (No Model Changes)

### Trust Score Composite

A weighted composite derived entirely from existing model outputs. No new model training required.

| Component | Weight | Source |
|-----------|--------|--------|
| Transaction Score | 40% | Existing Anomaly Detection + Fraud Engine signals |
| Identity Score | 35% | Existing Identity Resolution confidence + Bot Detection inverse |
| Behavioral Score | 25% | Existing Intent Prediction + Session Scoring heuristics |

**Output:** `trustScore` float `0.0 - 1.0`, written to `AGENT` node on every task completion.

### Bytecode Risk Scorer

Rule-based static analysis (not ML). Scores contract bytecode against 10 known risk patterns.

| Pattern | Weight | Description |
|---------|--------|-------------|
| `SELFDESTRUCT` opcode | 0.15 | Contract can destroy itself |
| `DELEGATECALL` to variable | 0.15 | Proxy pattern — upgrade risk |
| Unverified source | 0.10 | No verified source on block explorer |
| High `SSTORE` density | 0.10 | Excessive state manipulation |
| Flash loan callbacks | 0.10 | Reentrancy/manipulation risk |
| Token approval to EOA | 0.10 | Drain risk via unlimited approvals |
| Missing access control | 0.10 | Privileged functions callable by anyone |
| Unusual token minting | 0.08 | Unbounded or hidden mint functions |
| Hardcoded addresses | 0.07 | Centralization or backdoor risk |
| Short deployment age | 0.05 | Contract deployed < 24h ago |

**Output:** `riskScore` float `0.0 - 1.0`, written to `CONTRACT` node on ingestion.

### Anomaly Detection Extension

6 new feature columns appended to the existing `IsolationForest` + `Autoencoder` pipeline input. No model architecture changes — the existing models accept variable-width feature vectors.

New columns: `agent_task_frequency`, `avg_confidence_delta`, `hiring_depth`, `x402_spend_rate`, `contract_deploy_rate`, `cross_agent_payment_volume`

## API Endpoints

### Commerce Service (L3a)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/commerce/payments` | Record a payment event between any two participants |
| `POST` | `/v1/commerce/hires` | Record an agent hiring another agent for a task |
| `GET` | `/v1/commerce/fees/report` | Aggregate fee analysis across agents for a time range |
| `GET` | `/v1/commerce/agent/{id}/spend` | Total spend breakdown for a specific agent |

### On-Chain Service (L0)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/onchain/actions` | Submit an `ActionRecord` for chain activity |
| `GET` | `/v1/onchain/actions/{agent_id}` | Retrieve all action records for an agent |
| `GET` | `/v1/onchain/contracts/{address}` | Contract metadata + bytecode risk score |
| `POST` | `/v1/onchain/listener/configure` | Configure chain listener filters per project |

### x402 Service (L3b)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/x402/capture` | Capture an x402 payment header from an HTTP exchange |
| `GET` | `/v1/x402/graph` | Retrieve the economic graph of x402 payment flows |
| `GET` | `/v1/x402/agent/{id}` | x402 payment history and service consumption for an agent |

### Operational Intelligence / Graph Traversal (v8.8.0)

Full graph traversal, path-finding, and overlay services via `GraphTraversalEngine` in `shared/graph/traversal.py`. The in-memory (local), Postgres, and Neptune (staging/production) backends use identical interfaces.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/graph/traverse` | BFS traversal from a root vertex — depth, edge-type, and tenant-scope filters |
| `POST` | `/v1/graph/path` | Shortest-path (Dijkstra) between two vertices |
| `POST` | `/v1/graph/temporal` | Temporal BFS — traverse edges created within a time window |
| `POST` | `/v1/graph/overlay` | Fetch all vertices matching type/tenant predicates (uses `get_all_vertices()`) |
| `POST` | `/v1/graph/filter` | Filter vertices by risk level, relationship type, or property predicate |
| `GET` | `/v1/graph/contracts` | List smart-contract vertices visible in the tenant's graph |

### Path Intelligence (Phase 20)

Canonical ordered-path types, path scoring, stronger algorithms, and dedicated path API surface. See [`docs/CANONICAL-PATH-INTELLIGENCE.md`](./CANONICAL-PATH-INTELLIGENCE.md) and [`docs/MULTI-HOP-TRAVERSAL.md`](./MULTI-HOP-TRAVERSAL.md) for full details.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/graph/paths` | PathQuery → RelationshipPath[] — supports shortest, strongest, k_shortest, temporal, attribution, decision_outcome, multi_source, evidence modes |
| `POST` | `/v1/graph/paths/expand` | Expand a single node one hop in any direction |
| `POST` | `/v1/graph/paths/explain` | Generate human-readable narrative for a path (why_connected, hop_narrative, causal_language_allowed) |
| `POST` | `/v1/graph/paths/jobs` | Submit deep traversal as async job when max_depth > 6 or node budget > 500 |
| `GET` | `/v1/graph/paths/jobs/{id}` | Poll deep traversal job status and partial_path_ids |
| `POST` | `/v1/graph/snapshots` | Persist a TraversalSnapshot (path_ids + node_ids + edge_ids + digest) |
| `GET` | `/v1/graph/snapshots/{id}` | Retrieve a snapshot — fail-closed tenant ownership check |
| `POST` | `/v1/graph/snapshots/{id}/compare` | Diff two snapshots: added/removed node and edge IDs |
| `POST` | `/v1/graph/reconcile` | Operator-only: run silver reconciliation worker (read-only report) |

### Agent Extensions

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/agent/register` | Register a new agent with owner, model, and capabilities |
| `POST` | `/v1/agent/tasks/{id}/lifecycle` | Update task state (`started`, `paused`, `completed`, `failed`) |
| `POST` | `/v1/agent/tasks/{id}/decision` | Log an agent decision with reasoning and confidence |
| `POST` | `/v1/agent/tasks/{id}/feedback` | Submit ground truth feedback and compute `confidence_delta` |
| `GET` | `/v1/agent/{id}/graph` | Full subgraph for an agent (nodes, edges, action records) |
| `GET` | `/v1/agent/{id}/trust` | Current trust score with component breakdown |
| `POST` | `/v1/agent/{id}/a2h` | Record an agent-to-human interaction (notification, recommendation, delivery, escalation) |

## Configuration

### Feature Flags

All flags default to `false`. Enable progressively per layer.

| Environment Variable | Layer | Description |
|---------------------|-------|-------------|
| `IG_AGENT_LAYER` | L2 | Enable agent registration and task lifecycle tracking |
| `IG_COMMERCE_LAYER` | L3a | Enable payment and hiring event capture |
| `IG_X402_LAYER` | L3b | Enable x402 HTTP payment header interception |
| `IG_ONCHAIN_LAYER` | L0 | Enable on-chain action ingestion and chain listener |
| `IG_TRUST_SCORING` | L4 | Enable Trust Score composite computation |
| `IG_BYTECODE_RISK` | L4 | Enable bytecode risk scoring on contract ingestion |
| `IG_RPC_GATEWAY` | L6 | Route all RPC calls through shared QuickNode gateway |

### QuickNode Config

| Variable | Description | Default |
|----------|-------------|---------|
| `QUICKNODE_API_KEY` | QuickNode API authentication key | — |
| `QUICKNODE_ENDPOINT` | Base URL for QuickNode RPC gateway | — |
| `QUICKNODE_X402_ENABLED` | Enable x402 payment headers on RPC calls | `false` |
| `QUICKNODE_MAX_RPS` | Rate limit for RPC requests per second | `50` |

## Compliance

### Consent Purposes

5 total consent purposes presented in the SDK consent banner:

| Purpose | Status | Description |
|---------|--------|-------------|
| `analytics` | Existing | Web2 behavioral tracking |
| `marketing` | Existing | Campaign attribution and retargeting |
| `web3` | Existing | Wallet detection and transaction tracking |
| `agent` | **New** | Agent behavioral tracking and delegation |
| `commerce` | **New** | Payment capture and economic graph |

### DSR Cascade (Art. 17 Erasure)

When a Data Subject Request is received:

- `AGENT` vertices owned by the user: **deleted** (along with all edges)
- `PAYMENT` vertices involving the user: **deleted**
- `ACTION_RECORD` vertices produced by user-owned agents: **deleted**
- `CONTRACT` vertices: **pseudonymized** (deployer field hashed; on-chain data is immutable)
- All existing H2H vertices: handled by existing DSR cascade (unchanged)

### Audit Actions (14 new)

`AGENT_REGISTERED`, `AGENT_TASK_STARTED`, `AGENT_TASK_COMPLETED`, `AGENT_DECISION_LOGGED`, `AGENT_FEEDBACK_RECEIVED`, `AGENT_NOTIFICATION_SENT`, `AGENT_RECOMMENDATION_MADE`, `AGENT_RESULT_DELIVERED`, `AGENT_ESCALATION_RAISED`, `PAYMENT_RECORDED`, `HIRE_RECORDED`, `CONTRACT_INGESTED`, `BYTECODE_SCORED`, `X402_CAPTURED`

### ROPA Processing Activities (3 new)

1. **Agent Behavioral Processing** — collection and analysis of autonomous agent task data for trust scoring
2. **Commerce Graph Processing** — recording and aggregation of payment events between humans and agents
3. **On-Chain Action Processing** — ingestion and risk scoring of smart contract deployments and calls

## Event Flow — Agent Task Lifecycle

Complete flow for an agent executing a task with chain interaction:

```
1. User launches agent
   SDK: registerAgent({ model, capabilities })
   Graph: AGENT node created + LAUNCHED_BY edge to User

2. Agent starts task
   API: POST /v1/agent/tasks/{id}/lifecycle { state: "started" }
   Graph: state_snapshot stored
   Event: AGENT_TASK_STARTED -> Unified Pipeline

3. Agent needs chain data
   RPC: x402-enabled request through QuickNode gateway (L6)
   Graph: CONSUMES edge to SERVICE, PAYMENT node for micropayment

4. Agent deploys contract
   API: POST /v1/onchain/actions { type: "deploy", bytecode }
   Graph: ACTION_RECORD node + DEPLOYED edge to new CONTRACT node
   ML: Bytecode Risk Scorer runs -> riskScore written to CONTRACT

5. Agent hires specialist agent
   API: POST /v1/commerce/hires { hiredAgentId, terms }
   Graph: HIRED edge + PAYS edge + x402 payment captured
   Event: HIRE_RECORDED audit action

6. Task completes
   API: POST /v1/agent/tasks/{id}/lifecycle { state: "completed", confidence: 0.92 }
   Graph: Trust Score recomputed from 3 components
   Event: AGENT_TASK_COMPLETED -> Unified Pipeline

7. Ground truth feedback
   API: POST /v1/agent/tasks/{id}/feedback { groundTruth, rating }
   ML: confidence_delta = actual - predicted -> stored on AGENT node
   Event: AGENT_FEEDBACK_RECEIVED audit action

8. Unified Pipeline processing
   All events -> ClickHouse (columnar analytics)
             -> Graph DB (relationship queries)
             -> ML Pipeline (anomaly detection with 6 new features)
             -> WebSocket (real-time dashboard updates)
```

## Security Hardening (v8.1.0)

### Authentication & Authorization

- All IG endpoints are **feature-flagged** — each route checks its corresponding `IntelligenceGraphConfig` flag before execution
- All fraud service endpoints now require tenant-scoped permission checks (`fraud:evaluate`, `fraud:read`, `admin`)
- API key stubs are restricted to `LOCAL` environment only; non-local environments reject stub keys
- JWT secret validation enforced at startup — `RuntimeError` raised if default secret used in non-local environments

### Tenant Isolation

All in-memory stores are tenant-scoped:
- Agent registry keys: `f"{tenant_id}:{agent_id}"`
- x402 economic graph nodes: `f"{tenant_id}:{agent_id}"`
- Commerce service: all query methods accept and filter by `tenant_id`
- Lifecycle events and feedback records carry `tenant_id` from request context

### Input Validation

- **x402 headers:** 8KB size limit, amount validation (non-negative numeric), malformed non-JSON rejection
- **RPC gateway:** Method allowlist restricts execution to curated EVM/Solana read methods
- **Gremlin queries:** Escape regex expanded to include `"`, `` ` ``, and `;` to prevent injection
- **Middleware:** `Content-Length` parsing handles malformed values gracefully

### Error Handling

- x402 capture persists transactions before event publishing; publish failures are logged but don't block capture
- On-chain action recorder wraps graph operations in try/except; failures logged but actions still recorded locally
- `EventConsumer` retry uses bounded loop instead of recursive calls to prevent stack overflow
- SDK 429 retry respects `maxRetries` bound instead of infinite recursion

## Diagnostics Service (v8.1.0)

Centralized error tracking with automatic classification, circuit breakers, and health monitoring.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/diagnostics/health` | Quick health status (healthy/degraded/critical) |
| `GET` | `/v1/diagnostics/errors` | List tracked errors with filters (service, category, severity) |
| `GET` | `/v1/diagnostics/report` | Full diagnostics report with breakdowns and top offenders |
| `POST` | `/v1/diagnostics/errors/{fingerprint}/resolve` | Mark an error as resolved |
| `POST` | `/v1/diagnostics/errors/{fingerprint}/suppress` | Suppress alerts for a known error |
| `GET` | `/v1/diagnostics/circuit-breakers` | List all circuit breaker states |

### Error Classification

13 categories: `RACE_CONDITION`, `SECURITY`, `DATA_INTEGRITY`, `GRAPH_MUTATION`, `EVENT_PIPELINE`, `AUTH`, `RATE_LIMITING`, `VALIDATION`, `TIMEOUT`, `DEPENDENCY`, `MEMORY`, `CONFIGURATION`, `UNKNOWN`

5 severity levels: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `WARNING`

### Circuit Breaker

Per-operation circuit breaker prevents cascading failures:
- **Closed** (normal) → opens after 5 consecutive failures
- **Open** (blocking) → rejects all calls for 30 seconds
- **Half-open** (testing) → allows one call through to test recovery

---

## L3b+ Control Plane — Commerce Graph Additions (v8.9.0)

The x402 Commerce Control Plane (L3b+) extends the Intelligence Graph with
vertices and edges that represent the full payment lifecycle. All additions
are written deterministically from the control plane; the graph is fully
rebuildable from Silver lake tables.

### New Vertex Types

| Vertex | Description | Tenant scope | DSR |
|---|---|---|---|
| `PAYMENT_REQUIREMENT` | HTTP 402 challenge issued for a protected resource | prefixed | pseudonymize |
| `PAYMENT_AUTHORIZATION` | Authorization granted after approval decision | prefixed | pseudonymize |
| `PAYMENT_RECEIPT` | On-chain receipt after verification | prefixed | retain (financial) |
| `SETTLEMENT` | Settlement FSM record (pending → settled/failed/disputed) | prefixed | retain |
| `ENTITLEMENT` | Access entitlement minted after settlement | prefixed | pseudonymize |
| `ACCESS_GRANT` | Final access grant record | prefixed | pseudonymize |
| `FULFILLMENT` | Fulfillment record (latency, status) | prefixed | pseudonymize |
| `APPROVAL_REQUEST` | Approval request in the approval queue | prefixed | pseudonymize |
| `APPROVAL_DECISION` | Approver's decision (approve/reject/escalate) | prefixed | pseudonymize |
| `POLICY_DECISION` | Policy engine evaluation result | prefixed | retain |
| `FACILITATOR` | Payment facilitator (Circle, Aether Local, etc.) | global | N/A |
| `STABLECOIN_ASSET` | Stablecoin asset + network (USDC/Base, USDC/Solana) | global | N/A |
| `PRICE_POLICY` | Pricing policy bound to a protected resource | per-tenant | N/A |
| `BUDGET_POLICY` | Per-agent/cluster budget constraint | per-tenant | N/A |
| `TREASURY` | Tenant treasury balance and runway | per-tenant | N/A |
| `SERVICE_PLAN` | Subscription plan definition | per-tenant | N/A |
| `PAYMENT_ROUTE` | Routing decision (facilitator + chain selected) | per-tenant | N/A |
| `ECONOMIC_CLUSTER` | Analytics cluster grouping agents by spend pattern | per-tenant | pseudonymize |

All tenant-prefixed vertices use `{tenant_id}:{vertex_id}` keys consistent with
the existing `X402EconomicGraph` pattern.

### New Edge Types

| Edge | From → To | Key Properties |
|---|---|---|
| `REQUIRES_PAYMENT` | ProtectedResource → PAYMENT_REQUIREMENT | amount_usd, chain, asset |
| `AUTHORIZED_BY` | PAYMENT_REQUIREMENT → PAYMENT_AUTHORIZATION | decided_at |
| `VERIFIED_BY` | PAYMENT_AUTHORIZATION → FACILITATOR | tx_hash, verified_at |
| `SETTLED_BY` | PAYMENT_RECEIPT → SETTLEMENT | state, retries |
| `GRANTS_ACCESS_TO` | ENTITLEMENT → ProtectedResource | scope, expires_at |
| `FULFILLED_BY` | ACCESS_GRANT → FULFILLMENT | latency_ms, status |
| `FUNDED_BY` | PAYMENT_AUTHORIZATION → TREASURY | amount_usd |
| `ACCEPTS_ASSET` | ProtectedResource → STABLECOIN_ASSET | priority |
| `GUARDED_BY_POLICY` | ProtectedResource → PRICE_POLICY/BUDGET_POLICY | active |
| `ROUTES_VIA` | PAYMENT_AUTHORIZATION → PAYMENT_ROUTE | facilitator_id |
| `REUSES_ENTITLEMENT` | AGENT → ENTITLEMENT | count, last_used |
| `RETRIED_AS` | SETTLEMENT → SETTLEMENT | reason, attempt |
| `ESCALATES_PAYMENT_TO` | APPROVAL_REQUEST → USER | reason |
| `APPROVED_BY` | APPROVAL_DECISION → USER | role |
| `GOVERNED_BY` | TENANT/AGENT → POLICY_DECISION | context |
| `CONSTRAINED_BY` | AGENT/USER → BUDGET_POLICY | role |
| `SUBSCRIBES_TO` | USER/AGENT → SERVICE_PLAN | started_at, expires_at |

### Graph Query Purposes (L3b+)

| Query | Readers | Purpose |
|---|---|---|
| `trace_payment_lifecycle(challenge_id)` | Kyber Noesis, Review | Full lifecycle trace |
| `agent_entitlements(agent_id)` | Kyber Entities, SDK preflight | Active entitlements |
| `service_revenue(service_id, window)` | Kyber Mission | Revenue rollup |
| `cluster_spend(cluster_id)` | Kyber Entities, Diagnostics | Anomaly detection |
| `policy_chain(resource_id)` | Kyber explainability | Which policies fire |
| `facilitator_performance(facilitator_id)` | Kyber Command, Diagnostics | Reliability |
| `approval_backlog(tenant_id)` | Kyber Mission | Queue depth + latency |

### L3b+ API Extensions

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/x402/challenge` | Issue PAYMENT-REQUIRED for a protected resource |
| `POST` | `/v1/x402/verify` | Submit PaymentProof → receipt |
| `POST` | `/v1/x402/settle` | Trigger settlement FSM |
| `GET` | `/v1/x402/settlements/{id}` | Settlement state |
| `GET` | `/v1/x402/explain/{challenge_id}` | Full lifecycle trace |
| `GET` | `/v1/intelligence/commerce/lifecycle/{challenge_id}` | Commerce lifecycle trace (Intelligence service) |
| `GET` | `/v1/analytics/commerce/kpi` | Commerce KPI dashboard |

### Rebuildability

All L3b+ graph state is rebuildable from Silver lake tables:
- `settlement_events` → `SETTLEMENT` vertices + `SETTLED_BY` edges
- `payment_intents` → `PAYMENT_REQUIREMENT` vertices
- `approval_requests` → `APPROVAL_REQUEST` + `APPROVAL_DECISION` vertices
- `entitlements` → `ENTITLEMENT` vertices + `GRANTS_ACCESS_TO` edges

Trigger a rebuild via the existing lake-to-graph pipeline:
```python
await economic_graph.snapshot_to_graph(tenant_id)
```

---

## Universal Intelligence Graph (v8.10.0)

The Universal Intelligence Graph extends the base graph with production-grade query infrastructure, universal envelopes, Cluster360, semantic zoom, bitemporal replay, historical comparison, Kyber fleet graph, and a boolean filter language.

See `docs/source-of-truth/UNIVERSAL_GRAPH_CONTRACT.md` for the full contract reference.
See `docs/architecture/UNIVERSAL_GRAPH_ARCHITECTURE.md` for system architecture.
See `docs/security/UNIVERSAL_GRAPH_SECURITY_MODEL.md` for the security model.
See `docs/operations/UNIVERSAL_GRAPH_RUNBOOK.md` for operational procedures.

### Universal Query API (v8.10.0)

New routes added to `services/operational_intelligence/routes.py`:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/graph/query` | Universal query — BFS + boolean filter + overlays + temporal + cursor pagination |
| `POST` | `/v1/graph/facets` | Compute facet counts for a filter (node types, risk tiers, geography, etc.) |
| `POST` | `/v1/graph/compare` | Historical comparison — diff between two point-in-time snapshots |
| `POST` | `/v1/graph/replay` | Server-backed point-in-time replay (changes result set, not just labels) |
| `POST` | `/v1/graph/explain` | Query plan explanation with budget projection |
| `POST` | `/v1/graph/export` | Async export job (returns job_id; Celery-backed when `IG_EXPORT_JOBS=true`) |
| `POST` | `/v1/graph/flow` | Flow-of-funds trace via PAYS_FOR/TRANSFERS_TO/SETTLED_VIA edges |
| `GET` | `/v1/graph/capabilities` | Advertise supported operators, overlays, node types, edge types |
| `GET` | `/v1/graph/export/{job_id}` | Check export job status + download URL when complete |

### Boolean Filter Language

`POST /v1/graph/query` and `POST /v1/graph/facets` accept a structured `filter` field:

```json
{
  "filter": {
    "logic": "AND",
    "expressions": [
      {"field": "lifecycle_state", "op": "eq", "value": "active"},
      {"field": "risk_score", "op": "gt", "value": 0.7},
      {
        "logic": "OR",
        "expressions": [
          {"field": "vertex_type", "op": "eq", "value": "human"},
          {"field": "vertex_type", "op": "eq", "value": "agent"}
        ]
      }
    ]
  }
}
```

Supported operators: `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `exists`, `not_exists`, `contains`, `starts_with`, `between`, `relative_time`, `threshold`. Unknown operators return HTTP 400.

### Universal Envelopes

Every graph vertex and edge carries typed sub-objects:

| Envelope | Key Fields |
|----------|-----------|
| `TemporalEnvelope` | `valid_from`, `valid_to`, `recorded_at`, `superseded_at`, `lifecycle_state` |
| `ProvenanceEnvelope` | `source_system`, `observation_class`, `model_id`, `quality_score`, `evidence_refs` |
| `RiskEnvelope` | `risk_score`, `severity`, `confidence`, `reason_codes`, `alert_state` |
| `EconomicEnvelope` | `amount`, `currency`, `direction`, `rail`, `attribution_share` |
| `GovernanceEnvelope` | `tenant_id`, `consent_state`, `activation_eligible`, `jurisdiction` |
| `IdentityEnvelope` | `canonical_entity_id`, `cluster_memberships`, `resolution_state` |
| `OutcomeEnvelope` | `intended_outcome`, `observed_outcome`, `result_state`, `value` |

### Overlays

`POST /v1/graph/query` with `include_overlays: ["risk", "economic", "campaign", "geography", "consent", "confidence", "fraud", "agent"]` appends overlay data per node in the result.

### Semantic relationship overlay

The semantic-intelligence relationship Gold is projected into the graph as
governed `SEMANTIC_RELATES_TO` edges (directed `source_ref -> target_ref`) by
the **semantic graph projector**:

- **Scheduled worker** — WorkerSpec `semantic_graph_projector` (role
  `semantic-worker`), gated on `SEMANTIC_GRAPH_PROJECTOR_ENABLED` (default
  `false`, matching the graph layers' default-off posture); pass interval
  `SEMANTIC_GRAPH_PROJECTOR_INTERVAL_S` (default 6h).
- **Source** — durable `gold_relationship_semantic_state` rows read per tenant
  (`SemanticFactRepository`); on the in-memory local store there are no rows, so
  a pass is a no-op.
- **Governed write path** — every edge flows through the canonical
  `GraphMutationGateway` with an `edge_intent` (`operation=edge_created`,
  `actor_kind=system`, `causality_class=observed_sequence`), never a direct
  graph write. The gateway's mode (`off` / `shadow` / `enforce`, from
  `settings.temporal_observatory.mutation_gateway_mode`) decides whether the
  mutation is also recorded in the append-only ledger.
- **Relationship layer** — `SEMANTIC_RELATES_TO` is mapped to the `EXCLUDED`
  layer (a derived analytics overlay, not a human/agent interaction), so
  enforce-mode validation does not require a consent purpose.
- **Idempotent and tenant-scoped** — an edge already present for `(tenant,
  source, target)` is skipped, so repeated sweeps never duplicate; every edge
  carries the tenant on both `tenantId` and `tenant_id` properties, so one
  tenant's projection never matches another's edge.
- **Read-back** — `POST /v1/graph/semantic-overlay` returns the overlay's
  `edge_overlays` from durable Gold directly (`list_relationship_edges`), so the
  overlay is honest whether or not the projector has run; a subject filter
  restricts the edges to those touching the subject.

### Cluster360

Full Cluster360 surface available at `/clusters/:clusterId` in Aether. API routes:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/clusters/{cluster_id}` | Full cluster record with all 25 standard fields |
| `GET` | `/v1/clusters/{cluster_id}/members` | Paginated member list |
| `GET` | `/v1/clusters/{cluster_id}/timeline` | Merge/split/growth events |
| `GET` | `/v1/clusters/{cluster_id}/graph` | Cluster subgraph |
| `GET` | `/v1/clusters/{cluster_id}/economic` | Economic summary |
| `GET` | `/v1/clusters/{cluster_id}/risk` | Risk summary + evidence |
| `GET` | `/v1/clusters/{cluster_id}/geography` | Geographic distribution |

Supported cluster types: `identity`, `household`, `org`, `device`, `behavioral`, `geographic`, `economic_segment`, `campaign_cohort`, `journey`, `fraud_network`, `risk`, `dormant`, `reactivated`, `unresolved`, `wallet`.

### Semantic Zoom

Graph queries support server-backed macro→micro transitions:

- **Macro (zoom out):** `depth=0, include_clusters=true` returns `ClusterNode` aggregates (member_count, risk_score, cluster_type) without expanding individual nodes.
- **Expand (zoom in):** `anchors=[cluster_id], depth=1` expands a specific cluster into its member nodes.

Controlled by `IG_SEMANTIC_ZOOM` feature flag.

### Bitemporal Replay and Comparison

**Replay** — `POST /v1/graph/replay` with `as_of: "2026-01-01T00:00:00Z"` returns the graph as it existed at that point in time. Replay is a **knowledge-time** reconstruction (the `graph_history_replay` authority, temporal360 T2.1): the append-only mutation ledger is replayed as of τ (rows with `recorded_at <= τ`, applied in ledger insertion order — never re-sorted by wall-clock), rebuilding the vertices/edges Aether actually had at τ (`KNOWN_THEN`). The reconstruction is digest-verifiable (the same prefix always yields the same sha256) and strictly read-side — it never writes canonical state. Late-arriving rows recorded at `recorded_at <= τ` but appended later are honored idempotently; erased subjects stay terminal-tombstoned (never resurrected, so a KNOWN_THEN answer before an erasure remains a faithful audit record). Revoked edges remain in the canonical edge list flagged `revoked: true` — live reads filter them while the replay keeps the full audit trail intact. The result set is materially different (different nodes, different edges) — not just a timestamp label change.

**Comparison** — `POST /v1/graph/compare` with `as_of` and `compare_to` returns:
- `added_nodes` — nodes that appeared between the two snapshots
- `removed_nodes` — nodes that disappeared
- `changed_nodes` — nodes whose properties changed
- `added_edges` / `removed_edges` / `changed_edges` — same for edges

All nodes and edges carry `valid_from`/`valid_to`/`recorded_at`/`superseded_at` bitemporal fields.

### Kyber Fleet Graph and Operator Access

Available at `/noesis/fleet` in the Kyber console. Controlled by `IG_FLEET_GRAPH` feature flag.

**Fleet graph** shows the platform universe: tenant operational envelopes connected to their SDK, connector, pipeline, and model nodes.

**Tenant portfolio table** — all tenants × (graph_size, event_throughput, freshness, sdk_health, connector_health, fraud_volume, query_latency).

**Privileged operator entry** — Kyber operators call `POST /v1/kyber/operator/tenant-entry` with `access_reason` and `purpose`. An immutable audit record is created. An "OPERATOR SESSION ACTIVE — all actions audited" banner is shown. Exit via `DELETE /v1/kyber/operator/tenant-entry`.

### ObservationClass Visual Treatment

Aether graph nodes are styled based on `observation_class`:

| Class | Visual | Meaning |
|-------|--------|---------|
| `observed` | Solid border | Directly measured |
| `deterministic` | Solid border (dimmed) | Rule-resolved |
| `probabilistic` | Dashed border | ML confidence |
| `predicted` | Dotted border + future label | Model prediction |
| `derived` | Semi-transparent | Computed |
| `manually_asserted` | Solid + annotation icon | Human-annotated |

Predicted nodes must never render with the same visual weight as observed nodes.
