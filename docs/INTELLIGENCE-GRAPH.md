# Unified On-Chain Intelligence Graph v8.7.1

## Overview

The Unified On-Chain Intelligence Graph extends the Aether platform with an 8-layer architecture for tracking human, agent, and protocol interactions across Web2, Web3, and autonomous agent workflows.

- **Additive extension** — all 11 ML models/scorers remain unchanged; no retraining required
- **Feature-flagged** — every layer activates independently via environment variables (all default to `false`)
- **GDPR + SOC 2 compliant** — 2 new consent purposes, DSR cascade for agent/payment vertices, 14 audit actions
- **Graph-native** — 6 new node types, 19 new edge types layered onto the existing Identity Graph
- **Lake-fueled** — graph mutations are driven by Silver/Gold lake tiers, not ad-hoc scripts

> **Infrastructure:** `GraphClient` auto-selects Neptune (via gremlinpython) when `NEPTUNE_ENDPOINT` is set, falling back to in-memory in `AETHER_ENV=local`. Non-local environments without Neptune will fail-closed with `RuntimeError`.

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

## Architecture Layers

| Layer | Name | Description | Key Components |
|-------|------|-------------|----------------|
| **L6** | Infrastructure Backbone | Single shared RPC gateway via QuickNode | Multi-chain RPC, x402 payment headers, rate limiting |
| **L0** | On-Chain Action Ingestion | Captures contract deployments, calls, and token transfers | `ActionRecord` schema, chain listener, bytecode indexer |
| **L1** | Human Behavioral | Existing Aether SDK v3.0 event pipeline | `identify()`, `track()`, `page()`, fingerprinting, consent |
| **L2** | Agent Behavioral | Autonomous agent lifecycle tracking | `registerAgent()`, task states, decision logs, ground truth |
| **L3a** | Commerce | Payment tracking, agent hiring, fee analysis | Payment records, hire events, fee elimination reports |
| **L3b** | x402 Interceptor | HTTP 402-based micropayment capture | Payment headers, economic graph edges, per-call cost tracking |
| **L4** | ML Intelligence | Scoring and anomaly detection | 9 existing models + Trust Score composite + Bytecode Risk scorer |
| **L5** | Unified Graph | Cross-layer relationship store | 18+ vertex types, 48+ edge types, Neptune (gremlinpython) with in-memory fallback for local dev |

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
