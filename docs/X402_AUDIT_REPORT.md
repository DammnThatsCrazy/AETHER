---
title: x402 Protocol Support Audit
slug: security/x402-audit
section: security
visibility: P
audience: [security, architect, compliance]
status: stable
since_version: "8.8.0"
source_files:
  - Backend Architecture/aether-backend/services/x402/
canonical_owner: security@aether
estimated_read_minutes: 12
toc_depth: 3
last_synced_commit: "41c79d4"
---
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
| **Graph persistence (Neptune)** | Implemented | `economic_graph.py` — `snapshot_to_graph()` creates tenant-scoped `PAYS`/`CONSUMES` edges; vertex IDs use `{tenant_id}:{entity_id}` format; every edge carries `tenant_id` property for cross-tenant isolation |
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
| **Facilitator / Institution** | Implemented | `services/x402/facilitators.py` — `FacilitatorRegistry` with per-chain facilitator lookup; `services/x402/verification.py` — `VerificationEngine` delegates to external facilitator via HTTP (x402 wire format) with local USDC fallback |
| **Payment deduplication (idempotency)** | Implemented | `services/x402/idempotency.py` — async `_InMemoryIdempotencyStore` (local) + `_RedisIdempotencyStore` (staging/production, key: `aether:x402:idempotency:{tenant_id}:{payment_identifier}`); multi-instance safe |
| **Settlement state machine** | Implemented | `services/x402/settlement.py` — multi-state lifecycle (pending → clearing → settled / failed); `SettlementEngine.start()` transitions `PaymentReceipt` through states |
| **On-chain verification** | Implemented | `services/x402/verification.py` — facilitator-delegated verification (primary); direct on-chain RPC fallback via `_verify_evm()` (Base: `eth_getTransactionReceipt` + ERC-20 Transfer log) and `_verify_solana()` (Solana: `getTransaction` + SPL token transfer). Active when `AETHER_ENV != "local"`. Fail-closed on RPC error/timeout. |
| **Entitlement / access gating** | Latent | Reward eligibility engine exists (`services/rewards/eligibility.py`) but x402 does not gate access — it is observational/capture-only |
| **HTTP 402 response middleware** | Implemented | `services/x402/challenge_middleware.py` — `X402ChallengeMiddleware` intercepts requests to registered protected resources, returns HTTP 402 with `PAYMENT-REQUIRED` header, honors `X-Payment-Identifier` idempotency and active entitlements (SIWX reuse). Wired via `register_challenge_middleware()` controlled by `commerce_enable_challenge_middleware` setting. |

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

**Implemented.**

- `VertexType.INSTITUTION` exists with `InstitutionType` enum including `payment_processor`, `custodian`, `exchange`, `transfer_agent`
- `oracle/verifier.py` performs off-chain signature verification (ecrecover)
- `shared/graph/economic_schema.py` — `EconomicGraphSchema` now declares a dedicated `Facilitator` vertex type with `ROUTES_VIA`, `ACCEPTS_ASSET`, and `PREFERS_NETWORK` edge types; `repositories/commerce_repos.py:FacilitatorsRepository` provides Postgres-backed upsert/list for facilitator records.
- The x402 protocol facilitator concept is now a first-class graph entity with full schema, repository, and registry support (`services/x402/facilitators.py`).

### 2.5 Can the graph represent transactions/receipts/settlement states?

**Yes — Implemented (with partial settlement).**

- `CapturedX402Transaction` is the full receipt: capture_id, payer, payee, terms, proof, response, USD amount, fee eliminated, timestamp
- `PaymentResponse.verified` (bool) and `settled_at` (timestamp) capture settlement outcome
- `ActionRecord` vertex tracks on-chain transactions (tx_hash, chain_id, vm_type)
- `PAYS` edge properties include `capture_id`, `amount`, `token`, `chain`, `method="x402"`, `tenant_id`
- Edge IDs are deterministic: `{tenant_id}:{capture_id}:pays` — idempotent across replays
- `X402LifecycleMapper` routes 14 canonical lifecycle events to `PaymentIntentRepository` / `SettlementEventRepository` with tenant isolation; settlement state is now: intent_created → submitted → settled|failed|timeout
- **Partial gap resolved:** Multi-state settlement lifecycle (intent→submitted→settled/failed/timeout) implemented via lifecycle mapper; full distributed retry/dispute flows remain Phase 2

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
Neptune: {tenant_id}:AGENT vertex + {tenant_id}:SERVICE vertex + PAYS edge (tenant_id property) + CONSUMES edge (tenant_id property)
    ↓
AuditAction.X402_CAPTURED logged in compliance audit trail
```

### 3.2 Challenge → Payment → Access

The canonical x402 flow is:

```
Client request → Server returns HTTP 402 with PAYMENT-REQUIRED header
    → Client pays on-chain → Client retries with X-PAYMENT header
    → Server/facilitator verifies payment → Server returns 200 + X-PAYMENT-RESPONSE
```

**This challenge-side flow is now implemented.** `X402ChallengeMiddleware` (`services/x402/challenge_middleware.py`):
- Returns HTTP 402 with `PAYMENT-REQUIRED` header for requests to registered protected resources
- Honors `X-Payment-Identifier` for idempotent payment reuse (SIWX entitlement check)
- Wired via `register_challenge_middleware(app, protected_paths)` controlled by `commerce_enable_challenge_middleware` feature flag

Aether's x402 support is now **full-stack**: challenge-side (returning HTTP 402 and gating access) plus capture-side (recording transactions, building economic graph, analytics).

---

## 4. File Index

### Core x402 Service (Layer 3b)

| File | Role |
|---|---|
| `Backend Architecture/aether-backend/services/x402/models.py` | PaymentTerms, PaymentProof, PaymentResponse, CapturedX402Transaction, X402Node, SpendingSummary |
| `Backend Architecture/aether-backend/services/x402/commerce_models.py` | Facilitator, PaymentAuthorization, PaymentReceipt — commerce control plane types |
| `Backend Architecture/aether-backend/services/x402/interceptor.py` | X402Interceptor — header parsing, capture, event publishing |
| `Backend Architecture/aether-backend/services/x402/challenge_middleware.py` | X402ChallengeMiddleware — challenge-side HTTP 402 gating with idempotency and SIWX entitlement reuse |
| `Backend Architecture/aether-backend/services/x402/economic_graph.py` | X402EconomicGraph — in-memory subgraph, Neptune snapshots, spending patterns |
| `Backend Architecture/aether-backend/services/x402/facilitators.py` | FacilitatorRegistry — per-chain facilitator lookup and HTTP endpoint resolution |
| `Backend Architecture/aether-backend/services/x402/verification.py` | VerificationEngine — facilitator-delegated verification (x402 wire format) + USDC/Base, USDC/Solana local fallback |
| `Backend Architecture/aether-backend/services/x402/idempotency.py` | Async idempotency store — in-memory (local) or Redis-backed (staging/prod) deduplication |
| `Backend Architecture/aether-backend/services/x402/settlement.py` | SettlementEngine — multi-state settlement lifecycle (pending → clearing → settled / failed) |
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

**Classification: Implemented (full-stack: capture-side + challenge-side)**

Aether has a **production-grade x402 capture and analytics subsystem** that:

1. **Parses** all three x402 HTTP payment headers (`PAYMENT-REQUIRED`, `X-PAYMENT`, `X-PAYMENT-RESPONSE`)
2. **Records** complete transaction data with USD conversion and fee elimination tracking
3. **Builds** an economic subgraph (PAYS + CONSUMES edges) snapshotted to Neptune
4. **Exposes** REST APIs for capture ingestion, graph queries, and per-agent spending analytics
5. **Integrates** with the event bus, audit trail, GDPR/DSR compliance, and SDK event types
6. **Scopes** access via dedicated `x402:read`/`x402:write` permissions
7. **Isolates** data per tenant for multi-tenancy

**Update (post-audit):** The facilitator, idempotency, settlement gaps identified in the original audit have been closed, and tenant-scoped persistent graph writes have been added:
- `FacilitatorRegistry` + `VerificationEngine` implement facilitator-aware verification with x402 wire format
- `SettlementEngine` implements the full pending → clearing → settled / failed state machine
- Idempotency store is now Redis-backed in staging/production for multi-instance safety
- **Economic identity materialization** — `EconomicGraphMutations.write_agent_economic_identity()`
  now idempotently materializes the `AGENT_ECONOMIC_IDENTITY` vertex and links it to its
  `AGENT` vertex via the `ECONOMICALLY_IDENTIFIED_AS` edge, so the economic identity layer
  defined in the graph schema is populated, not just declared
- **Budget policy CRUD** has been added — operators can now cap per-subject spend
  via `POST/GET /v1/x402/policies/budget` and `GET /v1/x402/policies/budget/{subject_id}`.
  The policy engine consults these caps before reaching the approval queue,
  giving operators an immediate-effect control surface against runaway agents
  or compromised credentials. Each `BudgetPolicy` carries
  `daily_cap_usd`, `monthly_cap_usd`, `per_transaction_cap_usd`. See
  `COMMERCE-CONTROL-PLANE.md §9` and `COMMERCE-OPERATOR-RUNBOOK.md §8`.

**Challenge-side gap is now closed.** `X402ChallengeMiddleware` implements the missing HTTP 402 gating layer (`services/x402/challenge_middleware.py`). Deployment is controlled by `commerce_enable_challenge_middleware` setting.

Direct on-chain RPC verification is now implemented for EVM (Base) and Solana chains via `_verify_evm()` and `_verify_solana()` in `verification.py`. These run as the fallback path when facilitator delegation is unavailable, active in all non-local environments. Arbitrary EVM-compatible chains beyond Base are not yet supported; adding a new chain requires a `_ASSET_CONTRACT` entry and an RPC URL setting.

**Update (build-wave):** three observation-only additions extend the x402 surface without changing the no-custody posture:
- **Tenant Signer Authority** (`services/x402/signer_authority.py` + `signer_repos.py`,
  table `commerce_signer_refs`) binds a tenant to the signer *references* (public
  addresses) authorized to present payment proofs and sign x402 challenges on its
  behalf. It never holds private key material, never signs, and is fail-closed: a
  tenant with zero signer refs resolves to `False` for any address.
- **Commerce rail support matrix** (`services/commerce/rail_matrix.py`) declares an
  honest support bucket per rail (supported_production / supported_sandbox /
  supported_beta / intentionally_unsupported) — a mis-configured rail is refused
  loudly, never silently supported. `x402_credit` is `supported_beta` (export-only).
- **Usage metering** — the control plane meters challenged/paid/entitled usage as
  immutable audit facts (`services/metering_evidence/`), and an observability
  middleware (`services/diagnostics/observability_middleware.py` +
  `trace_writer.py`) ships per-request trace/span telemetry for the commerce and
  x402 write paths. None of these surfaces execute, settle, or custody anything.
