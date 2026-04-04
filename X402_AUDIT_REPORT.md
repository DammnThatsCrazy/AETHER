# x402 Protocol Support Audit — Aether Repository

**Date:** 2026-04-04
**Scope:** Full repository audit for x402 protocol support with emphasis on the intelligence graph
**Methodology:** Source-level inspection of all code, schemas, configurations, events, documentation, and compliance artifacts

---

## Executive Summary

**Final Classification: IMPLEMENTED**

Aether has a dedicated, purpose-built x402 subsystem (designated **Layer 3b** of the Intelligence Graph) with:

- A complete data model for x402 payment terms, proofs, responses, and captured transactions
- An interceptor that parses the three HTTP 402 payment headers
- An economic subgraph that materializes `PAYS` and `CONSUMES` edges into Neptune
- API routes for capture, graph querying, and agent spending history
- Event-bus integration (`aether.x402.payment.captured`)
- Audit trail action (`X402_CAPTURED`)
- GDPR/DSR cascade rules for x402 data erasure
- SDK-level event types (`X402PaymentEvent`)
- Feature-flagged deployment (`IG_X402_LAYER`, `QUICKNODE_X402_ENABLED`)
- Permission scoping (`x402:read`, `x402:write`)

This is not speculative or merely extensible infrastructure. The x402 support is explicitly named, purpose-coded, and integrated end-to-end across the backend, graph, event bus, compliance, and SDK layers.

---

## 1. Capability Matrix

| Capability | Status | Evidence |
|---|---|---|
| **x402 HTTP header parsing** | Implemented | `services/x402/interceptor.py` — parses `PAYMENT-REQUIRED`, `X-PAYMENT`, `X-PAYMENT-RESPONSE` |
| **Payment terms model** | Implemented | `services/x402/models.py:14-21` — `PaymentTerms` (amount, token, chain CAIP-2, recipient, memo, expires_at) |
| **Payment proof model** | Implemented | `services/x402/models.py:24-30` — `PaymentProof` (tx_hash, payer, chain, amount, token) |
| **Payment response/receipt** | Implemented | `services/x402/models.py:33-37` — `PaymentResponse` (verified, receipt_id, settled_at) |
| **Captured transaction record** | Implemented | `services/x402/models.py:40-54` — `CapturedX402Transaction` with USD conversion + fee elimination |
| **Economic graph (in-memory)** | Implemented | `services/x402/economic_graph.py` — `X402EconomicGraph` with tenant-isolated nodes |
| **Graph persistence (Neptune)** | Implemented | `economic_graph.py:78-149` — `snapshot_to_graph()` creates `PAYS`/`CONSUMES` edges via GraphClient |
| **API: capture endpoint** | Implemented | `services/x402/routes.py:24` — `POST /v1/x402/capture` (requires `x402:write`) |
| **API: economic graph query** | Implemented | `services/x402/routes.py:47` — `GET /v1/x402/graph` (requires `x402:read`) |
| **API: agent spending history** | Implemented | `services/x402/routes.py:56` — `GET /v1/x402/agent/{agent_id}` (requires `x402:read`) |
| **API: manual snapshot trigger** | Implemented | `services/x402/routes.py:65` — `POST /v1/x402/graph/snapshot` (requires `admin`) |
| **Event bus integration** | Implemented | `shared/events/events.py:115` — `Topic.X402_PAYMENT_CAPTURED = "aether.x402.payment.captured"` |
| **Audit trail action** | Implemented | `audit/trails/audit_engine.py:46` — `AuditAction.X402_CAPTURED = "x402_captured"` |
| **GDPR/DSR erasure cascade** | Implemented | `gdpr/data_subject_rights/dsr_engine.py` — x402 in-memory store deletion rules |
| **SDK event type** | Implemented | `packages/web/src/types.ts:566-575` — `X402PaymentEvent` interface |
| **Feature flag** | Implemented | `config/settings.py` — `enable_x402_layer`, `IG_X402_LAYER` env var |
| **RPC gateway x402 mode** | Implemented | `services/onchain/rpc_gateway.py` — `x402_enabled` config for QuickNode pay-per-request |
| **Permission scoping** | Implemented | `shared/auth/auth.py` — `x402:read`, `x402:write` permission constants |
| **Paid resource graph vertex** | Implemented | `shared/graph/graph.py:66` — `VertexType.PAYMENT = "Payment"` |
| **PAYS edge type** | Implemented | `shared/graph/graph.py:135` — `EdgeType.PAYS` (Agent/User → Agent/Service) |
| **CONSUMES edge type** | Implemented | `shared/graph/graph.py:136` — `EdgeType.CONSUMES` (Agent → Service API consumption) |
| **HIRED edge type** | Implemented | `shared/graph/graph.py:137` — `EdgeType.HIRED` (Agent → Agent task hiring) |
| **Wallet vertex** | Implemented | `shared/graph/graph.py:56` — `VertexType.WALLET` |
| **OWNS_WALLET edge** | Implemented | `shared/graph/graph.py:124` — `EdgeType.OWNS_WALLET` |
| **Stablecoin support (USDC)** | Implemented | Default token in `PaymentTerms` is `"USDC"`; web3 seed includes stablecoin registry |
| **Multi-chain (CAIP-2)** | Implemented | Chain field uses CAIP-2 format (e.g., `eip155:1`, `solana:mainnet`) |
| **Fee elimination tracking** | Implemented | `interceptor.py:30` — 2.9% card fee rate, computed per transaction |
| **Agent→Tool→Paid Resource** | Implemented | `CONSUMES` edges track API URL + method; `PAYS` edges track amount/token/chain |
| **Commerce layer (broader)** | Implemented | `services/commerce/` — `PaymentRecord` with method enum including `x402` |
| **Facilitator / Institution** | Partial | `VertexType.INSTITUTION` exists with types (payment_processor, custodian, etc.) but no x402-specific facilitator role |
| **Settlement state machine** | Partial | `PaymentResponse.verified` + `settled_at` capture settlement, but no multi-state lifecycle (pending→clearing→settled→failed) |
| **On-chain verification** | Partial | `oracle/verifier.py` verifies reward proofs via ecrecover, but x402 payment proof on-chain verification is not implemented |
| **Entitlement / access gating** | Latent | Reward eligibility engine exists (`services/rewards/eligibility.py`) but x402 does not gate access — it is observational/capture-only |
| **HTTP 402 response middleware** | Missing | No middleware that *returns* HTTP 402 to clients; x402 is capture-side only, not challenge-side |

---

## 2. Intelligence Graph Representation

### 2.1 Can the graph represent paid resources/endpoints?

**Yes — Implemented.**

- `VertexType.SERVICE` represents paid API endpoints
- `VertexType.PAYMENT` is a dedicated payment vertex
- `CapturedX402Transaction.request_url` and `request_method` track the specific paid endpoint
- `X402Node` aggregates total paid/received USD per node

### 2.2 Can the graph represent payment requirements?

**Yes — Implemented.**

- `PaymentTerms` model: amount, token (USDC default), chain (CAIP-2), recipient, memo, expires_at
- Parsed from `PAYMENT-REQUIRED` HTTP header on 402 responses
- Stored as part of `CapturedX402Transaction.terms`

### 2.3 Can the graph represent wallets/accounts?

**Yes — Implemented.**

- `VertexType.WALLET` — crypto wallets
- `VertexType.FINANCIAL_ACCOUNT` — cross-domain accounts (brokerage, bank, custody, wallet, etc.)
- `EdgeType.OWNS_WALLET` — User → Wallet ownership
- `EdgeType.HOLDS_TOKEN` — Wallet → Token holdings
- `PaymentProof.payer` captures payer wallet address
- `PaymentTerms.recipient` captures payee wallet address

### 2.4 Can the graph represent facilitators/verifiers?

**Partial.**

- `VertexType.INSTITUTION` exists with `InstitutionType` enum including `payment_processor`, `custodian`, `exchange`, `transfer_agent`
- `oracle/verifier.py` performs off-chain signature verification (ecrecover)
- However, no dedicated x402 **facilitator** vertex or edge exists. The x402 protocol concept of a facilitator (the intermediary that verifies payment and grants access) is not modeled as a first-class graph entity.

### 2.5 Can the graph represent transactions/receipts/settlement states?

**Yes — Implemented (with partial settlement).**

- `CapturedX402Transaction` is the full receipt: capture_id, payer, payee, terms, proof, response, USD amount, fee eliminated, timestamp
- `PaymentResponse.verified` (bool) and `settled_at` (timestamp) capture settlement outcome
- `ActionRecord` vertex tracks on-chain transactions (tx_hash, chain_id, vm_type)
- `PAYS` edge properties include `capture_id`, `amount`, `token`, `chain`, `method="x402"`
- **Gap:** No multi-state settlement lifecycle (e.g., pending → clearing → settled → disputed → failed)

### 2.6 Can the graph represent entitlements/access grants?

**Latent.**

- `RewardRule` + `Campaign` + `EligibilityResult` in `services/rewards/eligibility.py` implement a full entitlement engine (predicates, tiers, cooldowns, per-user caps, fraud gates)
- RWA policies (`services/rwa/models.py`) enforce whitelist, accreditation, jurisdiction, lockup, AML/KYC policies
- Privacy access control (`shared/privacy/access_control.py`) enforces role-based field masking and graph traversal restrictions
- **However:** x402 does not currently use any of these to gate access. The x402 layer is purely observational — it captures payments that already happened. It does not enforce "pay before access" entitlements.

### 2.7 Can the graph represent Agent → Tool → Paid Resource?

**Yes — Implemented.**

- `VertexType.AGENT` → `EdgeType.CONSUMES` → `VertexType.SERVICE` (with `api_call_url`, `method`)
- `VertexType.AGENT` → `EdgeType.PAYS` → `VertexType.SERVICE` (with `amount`, `token`, `chain`, `capture_id`)
- `VertexType.AGENT` → `EdgeType.DEPLOYED` → `VertexType.CONTRACT`
- `VertexType.AGENT` → `EdgeType.CALLED` → `VertexType.CONTRACT`
- `VertexType.AGENT` → `EdgeType.HIRED` → `VertexType.AGENT`
- `SpendingSummary` provides per-agent spending analytics

---

## 3. End-to-End Runtime Flow Analysis

### 3.1 Implemented Flow: Capture → Graph → Audit

```
External agent-to-service HTTP exchange (x402 headers present)
    ↓
POST /v1/x402/capture (requires x402:write permission)
    ↓
X402Interceptor.capture() parses terms/proof/response
    ↓
CapturedX402Transaction created (UUID capture_id, USD conversion, fee elimination)
    ↓
EventProducer.publish(Topic.X402_PAYMENT_CAPTURED, payload)
    ↓
X402EconomicGraph.add_payment() — updates in-memory nodes (tenant-isolated)
    ↓
[Every 30s or manual trigger] snapshot_to_graph()
    ↓
Neptune: AGENT vertex + SERVICE vertex + PAYS edge + CONSUMES edge
    ↓
AuditAction.X402_CAPTURED logged in compliance audit trail
```

### 3.2 Missing Flow: Challenge → Payment → Access

The canonical x402 flow would be:

```
Client request → Server returns HTTP 402 with PAYMENT-REQUIRED header
    → Client pays on-chain → Client retries with X-PAYMENT header
    → Server/facilitator verifies payment → Server returns 200 + X-PAYMENT-RESPONSE
```

**This challenge-side flow is not implemented.** Aether does not:
- Return HTTP 402 responses from any endpoint
- Act as a facilitator that verifies payment proofs before granting access
- Gate endpoint access behind payment verification middleware

Aether's x402 support is **capture-side**: it observes and records x402 transactions that occurred elsewhere, builds an economic graph from them, and provides analytics.

---

## 4. File Index

### Core x402 Service (Layer 3b)

| File | Role |
|---|---|
| `Backend Architecture/aether-backend/services/x402/models.py` | PaymentTerms, PaymentProof, PaymentResponse, CapturedX402Transaction, X402Node, SpendingSummary |
| `Backend Architecture/aether-backend/services/x402/interceptor.py` | X402Interceptor — header parsing, capture, event publishing |
| `Backend Architecture/aether-backend/services/x402/economic_graph.py` | X402EconomicGraph — in-memory subgraph, Neptune snapshots, spending patterns |
| `Backend Architecture/aether-backend/services/x402/routes.py` | FastAPI routes: /v1/x402/capture, /graph, /agent/{id}, /graph/snapshot |

### Graph Layer

| File | Role |
|---|---|
| `Backend Architecture/aether-backend/shared/graph/graph.py` | VertexType (AGENT, SERVICE, PAYMENT, WALLET, etc.), EdgeType (PAYS, CONSUMES, HIRED, OWNS_WALLET, etc.) |
| `Backend Architecture/aether-backend/shared/graph/relationship_layers.py` | H2H/H2A/A2H/A2A layer classification |

### Commerce Integration

| File | Role |
|---|---|
| `Backend Architecture/aether-backend/services/commerce/models.py` | PaymentRecord (method enum includes "x402"), AgentHireRecord, FeeEliminationReport |
| `Backend Architecture/aether-backend/services/commerce/routes.py` | /v1/commerce/payments, /hires, /fees/report, /agent/{id}/spend |

### Event & Audit Infrastructure

| File | Role |
|---|---|
| `Backend Architecture/aether-backend/shared/events/events.py:115` | `Topic.X402_PAYMENT_CAPTURED` |
| `GDPR & SOC2/aether-compliance/audit/trails/audit_engine.py:46` | `AuditAction.X402_CAPTURED` |
| `GDPR & SOC2/aether-compliance/gdpr/data_subject_rights/dsr_engine.py` | x402 data erasure cascade |

### Configuration & Auth

| File | Role |
|---|---|
| `Backend Architecture/aether-backend/config/settings.py` | `enable_x402_layer`, `QUICKNODE_X402_ENABLED` |
| `Backend Architecture/aether-backend/main.py:264-267` | Feature-flagged mount of x402 router via `IG_X402_LAYER` |
| `Backend Architecture/aether-backend/shared/auth/auth.py` | `x402:read`, `x402:write` permissions |

### SDK & Frontend

| File | Role |
|---|---|
| `packages/web/src/types.ts:566-575` | `X402PaymentEvent` TypeScript interface |
| `packages/web/src/core/event-queue.ts` | x402_payment classified as 'commerce' category |

### Supporting Infrastructure

| File | Role |
|---|---|
| `Backend Architecture/aether-backend/services/onchain/rpc_gateway.py` | QuickNode RPC with `x402_enabled` config |
| `Backend Architecture/aether-backend/services/oracle/verifier.py` | Off-chain signature verification (ecrecover) |
| `Backend Architecture/aether-backend/services/rewards/eligibility.py` | Entitlement engine (adjacent, not wired to x402) |
| `Backend Architecture/aether-backend/services/rwa/models.py` | RWA policy enforcement (adjacent) |

---

## 5. Conclusion

**Classification: Implemented (capture-side) / Partial (challenge-side)**

Aether has a **production-grade x402 capture and analytics subsystem** that:

1. **Parses** all three x402 HTTP payment headers (`PAYMENT-REQUIRED`, `X-PAYMENT`, `X-PAYMENT-RESPONSE`)
2. **Records** complete transaction data with USD conversion and fee elimination tracking
3. **Builds** an economic subgraph (PAYS + CONSUMES edges) snapshotted to Neptune
4. **Exposes** REST APIs for capture ingestion, graph queries, and per-agent spending analytics
5. **Integrates** with the event bus, audit trail, GDPR/DSR compliance, and SDK event types
6. **Scopes** access via dedicated `x402:read`/`x402:write` permissions
7. **Isolates** data per tenant for multi-tenancy

The **two gaps** preventing a "fully implemented end-to-end x402" classification are:

1. **No challenge-side middleware** — Aether does not return HTTP 402 responses or gate access behind x402 payment verification. It is an observer/recorder, not a facilitator.
2. **No on-chain payment proof verification** — The `PaymentProof.tx_hash` is stored but not verified against a blockchain. The oracle verifier exists but is wired to reward proofs, not x402 proofs.

These gaps are architectural choices (Aether is an intelligence platform, not a payment gateway), but they mean Aether cannot independently enforce the x402 protocol — it relies on external facilitators for the challenge/verification steps.
