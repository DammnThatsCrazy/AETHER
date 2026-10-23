---
title: x402 Protocol Support Audit
slug: security/x402-audit
section: security
visibility: P
audience: [security, architect, compliance]
status: stable
since_version: "0.1.0"
source_files:
  - services/api/value/x402/
  - services/api/actions/agent/user_agents.py
  - services/api/alembic/versions/20261022_execution_approval_decisions.py
  - services/api/actions/agent/deployment_routes.py
  - services/api/actions/agent_marketplace/authority.py
  - services/api/actions/agent_marketplace/identity_binding.py
  - services/api/actions/agent_marketplace/graph_state_check.py
  - services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py
  - services/api/alembic/versions/20261011_agent_delegated_to_namespace.py
  - services/api/ingestion/ingestion/lifecycle_worker.py
  - services/api/repositories/repos.py
canonical_owner: security@aether
estimated_read_minutes: 12
toc_depth: 3
reviewed_source_commits:
  - commit: "482948261"
    reason: "Reviewed 482948261 (Codex findings on fleet hypotheses, bounded lineage reads and journey handoff): repositories/repos.py only gains the additive BaseRepository.insert_if_absent and replace_if_matches conditional-write primitives, deployment_routes.py reads lineage through a shared bounded reader that reports truncation, middleware.py lets site-bound publishable keys reach the two journey-handoff POSTs, and route_registry.yaml classifies the /sdk/journey-handoff prefix; nothing this doc describes changed behavior, so no body change was required."
source_hashes:
  "services/api/actions/agent/deployment_routes.py": "sha256:46ace5ea27e1c0a95bb62b7d63cd9c53f383f0ae759e30c795914f41e5e2a8b4"
  "services/api/actions/agent/user_agents.py": "sha256:e00d936cb05ab3ba530c9208a98932e45dec4b1175330d8d24aa8d87a13cc81c"
  "services/api/actions/agent_marketplace/authority.py": "sha256:b136984919ab302e7140815f5984f4cfad11494c3a591853af33d4c741a88b29"
  "services/api/actions/agent_marketplace/graph_state_check.py": "sha256:595617063afe604a7a5b1c421fa73916141a37b374a008606bb6dab460cd0983"
  "services/api/actions/agent_marketplace/identity_binding.py": "sha256:0508f1094a8d369cd6c02004a18456c4b21b3b15f7160742d0ba6c9155aae352"
  "services/api/alembic/versions/20261011_agent_delegated_to_namespace.py": "sha256:446edfe924829cc75d627af169fb12c975f11f2ab13cf17b735ff14a8fed1c10"
  "services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py": "sha256:ab8553556c2c9d6e0e46fe55899132946dcfef9c432b8aed72d394da8e5a3269"
  "services/api/alembic/versions/20261022_execution_approval_decisions.py": "sha256:6f3c2ff0235a78fd144f0b26bb76a36556c23a1bc5a8285e58588608e9fa7fb6"
  "services/api/ingestion/ingestion/lifecycle_worker.py": "sha256:7b6d7d2323a5646c0f7a7093e7ae256f943c70af07557080ef5949d09d07e5d8"
  "services/api/repositories/repos.py": "sha256:1784df01b61c04f087c80397c3eab3b7167aef930bf199b7a82da4bfdc18dbf4"
  "services/api/value/x402/": "sha256:49f3660ba1468f6481b067fcd46ad230199aee60d7e7316ba57b7c69c368c4a9"
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
| **x402 HTTP header parsing** | Implemented | `services/api/value/x402/interceptor.py` — parses `PAYMENT-REQUIRED`, `X-PAYMENT`, `X-PAYMENT-RESPONSE` |
| **Payment terms model** | Implemented | `services/api/value/x402/models.py:14-21` — `PaymentTerms` (amount, token, chain CAIP-2, recipient, memo, expires_at) |
| **Payment proof model** | Implemented | `services/api/value/x402/models.py:24-30` — `PaymentProof` (tx_hash, payer, chain, amount, token) |
| **Payment response/receipt** | Implemented | `services/api/value/x402/models.py:33-37` — `PaymentResponse` (verified, receipt_id, settled_at) |
| **Captured transaction record** | Implemented | `services/api/value/x402/models.py:40-54` — `CapturedX402Transaction` with USD conversion + fee elimination |
| **Economic graph (in-memory)** | Implemented | `services/api/value/x402/economic_graph.py` — `X402EconomicGraph` with tenant-isolated nodes |
| **Graph persistence (Neptune)** | Implemented | `economic_graph.py` — `snapshot_to_graph()` creates tenant-scoped `PAYS`/`CONSUMES` edges; vertex IDs use `{tenant_id}:{entity_id}` format; every edge carries `tenant_id` property for cross-tenant isolation |
| **API: capture endpoint** | Implemented | `services/api/value/x402/routes.py:24` — `POST /v1/x402/capture` (requires `x402:write`) |
| **API: economic graph query** | Implemented | `services/api/value/x402/routes.py:47` — `GET /v1/x402/graph` (requires `x402:read`) |
| **API: agent spending history** | Implemented | `services/api/value/x402/routes.py:56` — `GET /v1/x402/agent/{agent_id}` (requires `x402:read`) |
| **API: manual snapshot trigger** | Implemented | `services/api/value/x402/routes.py:65` — `POST /v1/x402/graph/snapshot` (requires `admin` and a platform operator) |
| **Event bus integration** | Implemented | `shared/events/events.py:115` — `Topic.X402_PAYMENT_CAPTURED = "aether.x402.payment.captured"` |
| **Audit trail action** | Implemented | `audit/trails/audit_engine.py:46` — `AuditAction.X402_CAPTURED = "x402_captured"` |
| **GDPR/DSR erasure cascade** | Implemented | `gdpr/data_subject_rights/dsr_engine.py` — x402 in-memory store deletion rules |
| **SDK event type** | Implemented | `packages/sdk/web/src/types.ts:566-575` — `X402PaymentEvent` interface |
| **Feature flag** | Implemented | `config/settings.py` — `enable_x402_layer`, `IG_X402_LAYER` env var |
| **RPC gateway x402 mode** | Implemented | `services/api/graph/onchain/rpc_gateway.py` — `x402_enabled` config for QuickNode pay-per-request |
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
| **Commerce layer (broader)** | Implemented | `services/api/value/commerce/` — `PaymentRecord` with method enum including `x402` |
| **Facilitator / Institution** | Implemented | `services/api/value/x402/facilitators.py` — `FacilitatorRegistry` with per-chain facilitator lookup, filtered by the authorization environment (`supported_environments`) so a live authorization never routes through a sandbox-only facilitator; `services/api/value/x402/verification.py` — `VerificationEngine` delegates to an external facilitator via HTTP (x402 wire format), attaching the facilitator's tenant/environment-bound API key (credential authority slot `facilitator_api_key`) as a bearer token — falling through to the on-chain RPC verifier when the key is not configured, rather than firing a doomed unauthenticated request |
| **Payment deduplication (idempotency)** | Implemented | `services/api/value/x402/idempotency.py` — async `_InMemoryIdempotencyStore` (local) + `_RedisIdempotencyStore` (staging/production, key: `aether:x402:idempotency:{tenant_id}:{payment_identifier}`); multi-instance safe |
| **Settlement state machine** | Implemented | `services/api/value/x402/settlement.py` — multi-state lifecycle (pending → clearing → settled / failed); `SettlementEngine.start()` transitions `PaymentReceipt` through states |
| **On-chain verification** | Implemented | `services/api/value/x402/verification.py` — facilitator-delegated verification (primary); direct on-chain RPC fallback via `_verify_evm()` (Base: `eth_getTransactionReceipt` + ERC-20 Transfer log) and `_verify_solana()` (Solana: `getTransaction` + SPL token transfer). Active when `AETHER_ENV != "local"`. Fail-closed on RPC error/timeout. |
| **Entitlement / access gating** | Latent | Reward eligibility engine exists (`services/api/value/rewards/eligibility.py`) but x402 does not gate access — it is observational/capture-only |
| **HTTP 402 response middleware** | Implemented | `services/api/value/x402/challenge_middleware.py` — `X402ChallengeMiddleware` intercepts requests to registered protected resources, returns HTTP 402 with `PAYMENT-REQUIRED` header, honors `X-Payment-Identifier` idempotency and active entitlements (SIWX reuse). Wired via `register_challenge_middleware()` controlled by `commerce_enable_challenge_middleware` setting. |
| **Signer-authority enforcement** | Implemented | `services/api/value/x402/signer_authority.py` + `services/api/value/x402/verification.py` — fail-closed payer gate at the proof-verification boundary: a tenant that has registered signer references only accepts payment proofs from an active, tenant-authorized signer (unregistered or deactivated payer → `unauthorized_signer` verdict), while a tenant with no signer registry (the default) is unaffected |

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
- The x402 protocol facilitator concept is now a first-class graph entity with full schema, repository, and registry support (`services/api/value/x402/facilitators.py`).

### 2.5 Can the graph represent transactions/receipts/settlement states?

**Yes — Implemented (with partial settlement).**

- `CapturedX402Transaction` is the full receipt: capture_id, payer, payee, terms, proof, response, USD amount, fee eliminated, timestamp
- `PaymentResponse.verified` (bool) and `settled_at` (timestamp) capture settlement outcome
- `ActionRecord` vertex tracks on-chain transactions (tx_hash, chain_id, vm_type)
- `PAYS` edge properties include `capture_id`, `amount`, `token`, `chain`, `method="x402"`, `tenant_id`
- Edge IDs are deterministic: `{tenant_id}:{capture_id}:pays` — idempotent across replays
- `X402LifecycleMapper` routes 14 canonical lifecycle events to `PaymentIntentRepository` / `SettlementEventRepository` with tenant isolation; settlement state is now: intent_created → submitted → settled|failed|timeout
- **Partial gap resolved:** Multi-state settlement lifecycle (intent→submitted→settled/failed/timeout) implemented via lifecycle mapper; full distributed retry/dispute flows remain Phase 2

Server-authoritative lifecycle ingestion now also projects agent PaymentIntent
and SettlementEvent facts into the existing tenant-scoped graph types through
`GraphMutationGateway`. Registered `PAYS_FOR` and `SETTLED_AS` edges preserve
their source relationships; the authorization owner uses the existing
`AUTHORIZED_BY` edge. Agent 360 includes exact-matched execution evidence, but
no graph execution edge is projected because current records do not prove the
causal semantics of `RESULTED_IN_EXECUTION`. The evidence-only operation
contract and Agent 360 view reference source-owned records without creating a
competing operation vertex or financial aggregate.
SDK terminal claims remain observational and cannot drive these graph writes.

### 2.6 Can the graph represent entitlements/access grants?

**Latent.**

- `RewardRule` + `Campaign` + `EligibilityResult` in `services/api/value/rewards/eligibility.py` implement a full entitlement engine (predicates, tiers, cooldowns, per-user caps, fraud gates)
- RWA policies (`services/api/graph/rwa/models.py`) enforce whitelist, accreditation, jurisdiction, lockup, AML/KYC policies
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

**This challenge-side flow is now implemented.** `X402ChallengeMiddleware` (`services/api/value/x402/challenge_middleware.py`):
- Returns HTTP 402 with `PAYMENT-REQUIRED` header for requests to registered protected resources
- Honors `X-Payment-Identifier` for idempotent payment reuse (SIWX entitlement check)
- Wired via `register_challenge_middleware(app, protected_paths)` controlled by `commerce_enable_challenge_middleware` feature flag

Aether's x402 support is now **full-stack**: challenge-side (returning HTTP 402 and gating access) plus capture-side (recording transactions, building economic graph, analytics).

---

## 4. File Index

### Core x402 Service (Layer 3b)

| File | Role |
|---|---|
| `services/api/value/x402/models.py` | PaymentTerms, PaymentProof, PaymentResponse, CapturedX402Transaction, X402Node, SpendingSummary |
| `services/api/value/x402/commerce_models.py` | Facilitator, PaymentAuthorization, PaymentReceipt — commerce control plane types |
| `services/api/value/x402/interceptor.py` | X402Interceptor — header parsing, capture, event publishing |
| `services/api/value/x402/challenge_middleware.py` | X402ChallengeMiddleware — challenge-side HTTP 402 gating with idempotency and SIWX entitlement reuse |
| `services/api/value/x402/economic_graph.py` | X402EconomicGraph — in-memory subgraph, Neptune snapshots, spending patterns |
| `services/api/value/x402/facilitators.py` | FacilitatorRegistry — per-chain facilitator lookup and HTTP endpoint resolution |
| `services/api/value/x402/verification.py` | VerificationEngine — facilitator-delegated verification (x402 wire format) + USDC/Base, USDC/Solana local fallback; consults the signer authority at the proof boundary |
| `services/api/value/x402/signer_authority.py` | SignerAuthority — tenant signer registry; fail-closed `is_payer_authorized()` gate consulted at proof verification |
| `services/api/value/x402/idempotency.py` | Async idempotency store — in-memory (local) or Redis-backed (staging/prod) deduplication |
| `services/api/value/x402/settlement.py` | SettlementEngine — multi-state settlement lifecycle (pending → clearing → settled / failed) |
| `services/api/value/x402/routes.py` | FastAPI routes: /v1/x402/capture, /graph, /agent/{id}, /graph/snapshot |

### Graph Layer

| File | Role |
|---|---|
| `services/api/shared/graph/graph.py` | VertexType (AGENT, SERVICE, PAYMENT, WALLET, etc.), EdgeType (PAYS, CONSUMES, HIRED, OWNS_WALLET, etc.) |
| `services/api/shared/graph/relationship_layers.py` | H2H/H2A/A2H/A2A layer classification |

### Commerce Integration

| File | Role |
|---|---|
| `services/api/value/commerce/models.py` | PaymentRecord (method enum includes "x402"), AgentHireRecord, FeeEliminationReport |
| `services/api/value/commerce/routes.py` | /v1/commerce/payments, /hires, /fees/report, /agent/{id}/spend |

### Event & Audit Infrastructure

| File | Role |
|---|---|
| `services/api/shared/events/events.py:115` | `Topic.X402_PAYMENT_CAPTURED` |
| `services/compliance/audit/trails/audit_engine.py:46` | `AuditAction.X402_CAPTURED` |
| `services/compliance/gdpr/data_subject_rights/dsr_engine.py` | x402 data erasure cascade |

### Configuration & Auth

| File | Role |
|---|---|
| `services/api/config/settings.py` | `enable_x402_layer`, `QUICKNODE_X402_ENABLED` |
| `services/api/main.py:264-267` | Feature-flagged mount of x402 router via `IG_X402_LAYER` |
| `services/api/shared/auth/auth.py` | `x402:read`, `x402:write` permissions |

### SDK & Frontend

| File | Role |
|---|---|
| `packages/sdk/web/src/types.ts:566-575` | `X402PaymentEvent` TypeScript interface |
| `packages/sdk/web/src/core/event-queue.ts` | x402_payment classified as 'commerce' category |

### Supporting Infrastructure

| File | Role |
|---|---|
| `services/api/graph/onchain/rpc_gateway.py` | QuickNode RPC with `x402_enabled` config |
| `services/api/graph/oracle/verifier.py` | Off-chain signature verification (ecrecover) |
| `services/api/value/rewards/eligibility.py` | Entitlement engine (adjacent, not wired to x402) |
| `services/api/graph/rwa/models.py` | RWA policy enforcement (adjacent) |

---

## Scoped update — external-agent economic correlation (2026-10-11)

External-agent run events may report payment-intent and settlement-event IDs
as source references. They resolve only when an exact same-tenant record has
server-owned x402 provenance and its agent reference matches the tenant's
deployment registry reference. Public SDK x402 observations remain
observations; they do not establish or overwrite canonical payment state. The
run graph links use amount, currency and lifecycle state from the authoritative
record. They do not verify that the external action occurred as reported,
establish causality, or prove settlement finality. Same-ID lifecycle writes
cannot overwrite another tenant's record, and a delayed lower-state event
cannot roll back a later settlement. See the Agent Marketplace Lineage
source-of-truth page for the implementation boundaries.

Commerce objects are stored per tenant outside local: `CommerceStore` keys each
row `{tenant}:{object id}`, so the seeded facilitators and assets
(`fac_circle_v2`, `fac_local_aether`, `ast_usdc_*`) and client-chosen resource
ids exist once per tenant, and one tenant registering an id another tenant
uses never replaces that tenant's resource or paywall definition. Migration
`20261015_tenant_owned_row_keys` re-keys existing rows to the tenant their JSON
names; `make tenant-row-keys` re-runs that step after a rollout.

The run authority path separately resolves delegation references to exact
tenant-owned records. External deployment and delegated-target identities
require explicit tenant-admin bindings scoped by source namespace; target
resolution uses the source-declared `delegatedToNamespace` and does not infer
the actor's namespace. Backend-owned delegation parties, scope, status, and
effective/revoked times are compared with the source-reported action,
resource, event time, and (when available) authoritative economic amount. The
result is `within_scope`, `out_of_scope`, or `indeterminate`; this evaluates a
grant, not whether the external action occurred. Without a server-owned
execution receipt, occurrence remains `source_reported` and unverified.

The separate Kyber graph-state check is bounded and read-only. It compares
supported tenant source references with graph links and reports coverage and
findings on a best-effort, non-snapshot basis; it does not mutate graph state,
drain the projection outbox, or certify the complete tenant graph.

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
- **Signer-authority enforcement at proof verification** — a tenant that has
  registered signer references is enforced fail-closed at the proof-verification
  boundary (`services/api/value/x402/signer_authority.py` consulted by `verification.py`):
  proofs from an unregistered or deactivated payer are rejected with an
  `unauthorized_signer` verdict even when chain/facilitator verification would
  otherwise succeed; tenants with no signer registry are unaffected.

**Challenge-side gap is now closed.** `X402ChallengeMiddleware` implements the missing HTTP 402 gating layer (`services/api/value/x402/challenge_middleware.py`). Deployment is controlled by `commerce_enable_challenge_middleware` setting.

Direct on-chain RPC verification is implemented for EVM (Base) and Solana chains via `_verify_evm()` and `_verify_solana()` in `verification.py`. These run when facilitator delegation is unavailable, active in all non-local environments. As of the credential-only x402 closure, RPC is resolved **per-tenant** from the credential authority (atomic `{url, api_key, auth_mode}`; providers `rpc_evm_base` / `rpc_svm_mainnet` / …) rather than a deployment-global URL; a deployed environment with no configured pair returns the `verification_unavailable` verdict (fail-closed). The tenant-supplied RPC URL is an SSRF surface (a tenant admin controls it and the verifier POSTs to it), so `rpc_resolver._validate_rpc_url()` runs every resolved URL through the shared outbound-destination check (`shared.security.ssrf.resolve_public_addresses`: every resolved address must be globally routable after unwrapping IPv4-mapped, NAT64, 6to4 and Teredo forms, which excludes loopback, RFC1918, link-local metadata, ULA and carrier-grade NAT) plus HTTPS-outside-local enforcement, failing closed on a non-public address before any request is made (the check runs off the event loop; an RPC host that does not resolve is counted as `x402_rpc_resolutions{source=unresolved}`, a refused one as `source=ssrf_blocked`). The verifier's JSON-RPC calls then go through `send_public_request`, which re-resolves, connects only to a validated address with the original `Host`/SNI and follows no redirects, so a DNS answer that changes between validation and connect cannot reach an internal address. An RPC host that does not resolve yields `verification_unavailable: … could not be resolved` rather than the non-public refusal, so a resolver blip is retried like any other unavailability. Verification additionally binds the payer and enforces finality (confirmation depth / `finalized` commitment) and strict asset decimals, and — for a batched/multicall receipt — scans **every** candidate transfer to the recipient before rejecting, so a valid transfer among several is not missed. Verdicts are classified terminal vs retryable: `not_finalized` / `verification_unavailable` are **retryable** and are never written to the payment-identifier idempotency store, so a not-yet-final payment re-checks the chain on the next call instead of being stranded behind a cached failure. External-facilitator transport failures (HTTP 5xx / 429 / timeout / unreachable) are likewise classified `verification_unavailable` (retryable), not a terminal failure, so a facilitator outage doesn't strand a valid payment. Receipt ids are deterministic per (tenant, authorization), so a retry UPSERTS the same receipt row rather than colliding on the `commerce_receipts (tenant_id, authorization_id)` unique index. Arbitrary EVM-compatible chains beyond Base are not yet supported; adding a new chain requires a `_ASSET_CONTRACT` entry and an RPC provider mapping.

## 2026-10-23 — Execution-bound approval history

Execution-bound x402 approvals now carry an exact server-created execution ID
and action. The decision service stores typed decision history in the
tenant-scoped `commerce_approval_decisions` repository, keeps the latest
decision ID on the current approval, and records the authenticated tenant user
for bound decisions. The agent execution endpoint checks the exact agent,
action, resource, amount, current approval status, and latest decision before it
records a linked run. This is evidence of AETHER's approval record and local
policy decision; it does not execute a payment or prove that an external action
completed. Non-x402 approval authorities and historical executions are not yet
joined by this path.
