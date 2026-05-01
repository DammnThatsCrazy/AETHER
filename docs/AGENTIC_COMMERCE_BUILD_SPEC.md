# Aether Agentic Commerce — Day-1 Build Specification

**Document:** Production build spec for extending Aether's x402/commerce/graph foundation into a fully productized Aether-native Agentic Commerce control plane.
**Scope:** Extension of existing monorepo. Not a rewrite. Not a refactor.
**Day-1 GA anchor:** All Aether-native protected resource classes, mandatory approval on all spend classes, USDC on Base + Solana.
**External providers:** Designed-in, shipped second-wave.

---

## 1. Executive Summary

Aether already has a capture-side x402 subsystem (L3b) and a commerce layer (L3a) that observe and record payments into a graph. This spec upgrades both into a **graph-native commerce control plane** that issues challenges, governs spend via mandatory approvals, verifies and settles payments, mints entitlements, and grants access — all surfaced through Kyber as the operator command surface.

**What changes:**
- `services/x402` becomes a full control plane (challenge → verify → settle → entitle → grant) on top of existing capture code.
- `services/commerce` gains economic analytics, policy evaluation, and treasury/budget modeling.
- `shared/graph` adds 18 new vertex types and 22 new edge types formalizing the full commerce lifecycle.
- A new `services/x402/approvals.py` implements mandatory operator approval for every spend class.
- Kyber's 8 existing pages each gain real, audited, RBAC-gated economic actions wired to new `lib/api/commerce.ts`, `approvals.ts`, `entitlements.ts`, `resources.ts` adapters with Zod schemas.
- The lake gains Silver/Gold tables for the full commerce lifecycle, deterministically rebuildable into graph state.
- Stablecoin intelligence covers USDC/Base and USDC/Solana at GA with an extensible asset/network/facilitator registry.

**What does NOT change:**
- Neptune/GraphClient is preserved.
- Kafka topics are extended, not replaced.
- Kyber's architecture (lib/api adapters, Zod, feature-hooks, PermissionGate, mocked/live modes, Lab replay) is preserved as-is.
- Existing capture endpoints remain for backward compatibility with v1 x402 ingestion.
- Existing commerce `PaymentRecord` / `AgentHireRecord` models remain as legacy entry points; new flows use canonical internal schemas.

**Day-1 GA coverage:**
- Unified Protected Resource Registry covering all Aether APIs, agent tools, priced endpoints, and service plans.
- x402 v2-native challenge issuance with v1-compatible ingest.
- Mandatory approval on every spend class, configurable but defaulted-on.
- USDC on Base + Solana with facilitator-aware verification and local verification fallback.
- Payment-Identifier idempotency and SIWX-backed entitlement reuse.
- Full lifecycle persistence, Kyber operator actions on all 8 pages, compliance audit coverage, diagnostics/replay/reconciliation tooling.

**Out of Day-1 scope (architected, not shipped):**
- External third-party paid resource providers (second wave).
- Marketplace/discovery features.
- Auto-approved spend classes (mandatory approval everywhere at GA).
- Non-USDC stablecoins, non-Base/Solana rails (asset registry extensible).


---

## 2. Architecture Deltas From Current Aether

### 2.1 Existing (preserved)

| System | Current state | Preserved role |
|---|---|---|
| `services/x402/interceptor.py` | Parses 3 HTTP headers, builds `CapturedX402Transaction` | Legacy v1 ingest path; delegates to control plane |
| `services/x402/economic_graph.py` | In-memory subgraph + Neptune snapshots (`PAYS`, `CONSUMES`) | Continues as analytics projection; writes extended by control plane |
| `services/x402/routes.py` | `/v1/x402/capture`, `/graph`, `/agent/{id}` | Kept; augmented with new control-plane routes |
| `services/commerce/models.py` | `PaymentRecord`, `AgentHireRecord` | Kept as downstream analytics records, fed by control plane |
| `shared/graph/graph.py` | VertexType/EdgeType enums, GraphClient, Gremlin queries | Extended with 18 vertex types + 22 edge types |
| `shared/events/events.py` | `Topic` enum, `EventProducer` | Extended with 24 new commerce lifecycle topics |
| `middleware/middleware.py` | Auth + rate-limit + extraction defense | Gains optional `challenge_middleware` hook for protected resources |
| Kyber `lib/api`, `lib/schemas`, feature hooks, PermissionGate | Centralized adapter pattern with Zod validation | Reused verbatim; new adapters added under same patterns |

### 2.2 New (additive)

| Component | Path | Purpose |
|---|---|---|
| Commerce Control Plane | `services/x402/control_plane.py` | Orchestrates challenge → approval → verify → settle → entitle → grant |
| Challenge Middleware | `services/x402/challenge_middleware.py` | FastAPI middleware/hook that returns HTTP 402 with PAYMENT-REQUIRED for protected resources |
| Verification Engine | `services/x402/verification.py` | Facilitator-aware + local verification, chain/asset-specific verifiers |
| Settlement Tracker | `services/x402/settlement.py` | Multi-state settlement FSM (pending/verifying/settled/failed/disputed) |
| Entitlement Service | `services/x402/entitlements.py` | Access grant issuance, reuse, expiry, revocation, SIWX binding |
| Policy Engine | `services/x402/policies.py` | Price/budget/treasury/asset/network policy evaluation |
| Approval Service | `services/x402/approvals.py` | Mandatory approval workflow (request/queue/assign/decide/expire/revoke) |
| Facilitator Registry | `services/x402/facilitators.py` | Approved facilitator list, routing, health tracking |
| Pricing Engine | `services/x402/pricing.py` | Resource→price resolution with tenant overrides |
| Idempotency Store | `services/x402/idempotency.py` | Payment-Identifier dedupe, Redis-backed |
| Protected Resource Registry | `services/x402/resources.py` | Unified registry of all Aether-native protected resources |
| Economic Analytics | `services/commerce/economic_analytics.py` | Service revenue, cluster spend, facilitator performance, reuse metrics |
| Graph Schema Extensions | `shared/graph/economic_schema.py` | New VertexType/EdgeType constants for commerce lifecycle |
| Graph Mutations | `shared/graph/economic_mutations.py` | Deterministic builders: challenge→graph, approval→graph, settlement→graph |
| Event Topics | `shared/events/economic_topics.py` | 24 commerce lifecycle topics |
| Event Schemas | `shared/events/economic_schemas.py` | Pydantic schemas for every commerce event payload |

### 2.3 Conceptual shift

| Before | After |
|---|---|
| x402 = **observer** that captures headers | x402 = **control plane** that issues challenges + captures legacy headers |
| Graph = **projection** of past payments | Graph = **source of truth** for lifecycle state (challenge/approval/grant/settle) |
| Kyber = **dashboard** | Kyber = **operator command surface** with audited actions |
| Commerce = **record-keeping** | Commerce = **governed workflow** with mandatory approvals |
| Approval = N/A | Approval = **first-class domain** across all layers |


---

## 3. Monorepo Module-by-Module Change List

### 3.1 Backend — `Backend Architecture/aether-backend/`

**`services/x402/` (extend)**
- `models.py` — ADD: `PaymentChallenge`, `PaymentAuthorization`, `SettlementRecord`, `Entitlement`, `AccessGrant`, `ApprovalRequest`, `ApprovalDecision`, `PolicyDecision`, `PricePolicy`, `BudgetPolicy`, `AcceptedAsset`, `AcceptedNetwork`, `FacilitatorRecord`, `ProtectedResource`, `ServicePlan`, `FulfillmentRecord`, `PaymentRoute`.
- `control_plane.py` — NEW. Stateful orchestrator. `X402ControlPlane.handle_request()`, `.issue_challenge()`, `.request_approval()`, `.apply_decision()`, `.verify_payment()`, `.settle()`, `.mint_entitlement()`, `.grant_access()`, `.record_fulfillment()`.
- `challenge_middleware.py` — NEW. `ChallengeMiddleware` FastAPI middleware. Consults `resources.py` registry, returns 402 with PAYMENT-REQUIRED header, honors `X-Payment-Identifier` for idempotency, honors SIWX for entitlement reuse.
- `verification.py` — NEW. `VerificationEngine` with `FacilitatorVerifier` and `LocalVerifier` strategies. Per-chain verifiers (`BaseUSDCVerifier`, `SolanaUSDCVerifier`). Validates tx_hash, amount, recipient, chain.
- `settlement.py` — NEW. `SettlementTracker` FSM: `pending → verifying → settled | failed | disputed`. Retries with backoff. Reconciliation hooks.
- `entitlements.py` — NEW. `EntitlementService.mint()`, `.lookup()`, `.reuse()`, `.revoke()`, `.expire()`. SIWX binding via `SIWXBinding` model.
- `policies.py` — NEW. `PolicyEngine.evaluate()` returns `PolicyDecision` (allow/deny/require_approval/reduce_scope). Combines price/budget/treasury/asset/network policies.
- `approvals.py` — NEW. `ApprovalService` with queue, assignment, decision, escalation, expiry, revoke, replay. Mandatory for all spend classes at GA.
- `facilitators.py` — NEW. `FacilitatorRegistry` with approved facilitators, health checks, routing preference.
- `pricing.py` — NEW. `PricingEngine.resolve_price(resource_id, tenant_id, context)` with tenant overrides and plan discounts.
- `idempotency.py` — NEW. `IdempotencyStore` Redis-backed, keyed by Payment-Identifier + tenant.
- `resources.py` — NEW. `ProtectedResourceRegistry` with registration, classification, lookup. Seeded with all Aether-native protected resources.
- `routes.py` — EXTEND: add `POST /v1/x402/challenge`, `POST /v1/x402/verify`, `POST /v1/x402/settle`, `GET /v1/x402/entitlements/{id}`, `POST /v1/x402/access/preflight`, `GET /v1/x402/resources`, `POST /v1/x402/resources`, `GET /v1/x402/facilitators`, `GET /v1/x402/policies`, `POST /v1/x402/policies/simulate`, explainability endpoints.
- `interceptor.py` — KEEP. Legacy v1 ingest delegates to `control_plane.handle_legacy_capture()`.
- `economic_graph.py` — KEEP. Now writes augmented edges via `economic_mutations.py`.

**`services/x402/approvals_routes.py`** (NEW)
- `GET /v1/x402/approvals` (queue), `POST /v1/x402/approvals/{id}/assign`, `.../decide`, `.../escalate`, `.../revoke`, `.../replay`, `.../evidence`, `.../preview`.

**`services/commerce/` (extend)**
- `models.py` — KEEP. Add `ServiceRevenueRecord`, `ClusterSpendSnapshot`, `TreasuryBalance`.
- `routes.py` — EXTEND: `/v1/commerce/revenue/{service_id}`, `/v1/commerce/cluster/{cluster_id}/spend`, `/v1/commerce/treasury`, `/v1/commerce/facilitators/performance`.
- `economic_analytics.py` — NEW. Aggregates from Gold lake + graph queries.

**`services/agent/` (extend)**
- Add `economic.py` — per-agent budget, treasury, delegation policy views; integrates with approval service.

**`services/intelligence/` (extend)**
- Add graph query helpers for economic path tracing: `trace_payment_lifecycle(challenge_id)`.

**`services/analytics/` (extend)**
- Add commerce KPI aggregators: spend rate, approval latency, settlement degradation, reuse rate.

**`services/diagnostics/` (extend)**
- Add diagnostics for: verification failures, settlement timeouts, approval expirations, duplicate payments, reconciliation drift.

**`services/identity/` (extend)**
- Add SIWX session binding for entitlement reuse.

**`shared/graph/` (extend)**
- `graph.py` — EXTEND `VertexType` with 18 new constants, `EdgeType` with 22 new constants.
- `economic_schema.py` — NEW. Documents owner/tenant/provenance/DSR/visualization per vertex/edge.
- `economic_mutations.py` — NEW. Deterministic graph builders for each lifecycle stage.

**`shared/events/` (extend)**
- `events.py` — EXTEND `Topic` enum.
- `economic_topics.py` — NEW. 24 topic constants.
- `economic_schemas.py` — NEW. Pydantic event payload schemas.

**`shared/auth/` (extend)**
- `auth.py` — ADD scopes: `commerce:challenge`, `commerce:verify`, `commerce:settle`, `commerce:approve`, `commerce:admin`, `commerce:review`, `commerce:policy`, `approvals:read`, `approvals:write`, `entitlements:read`, `entitlements:write`, `resources:admin`. Add Kyber roles: `viewer`, `operator`, `approver`, `admin`.

**`repositories/` (extend)**
- `challenges_repo.py`, `approvals_repo.py`, `entitlements_repo.py`, `settlements_repo.py`, `resources_repo.py`, `policies_repo.py`, `facilitators_repo.py`. All Postgres-backed with tenant isolation.

**`config/` (extend)**
- `settings.py` — ADD: `commerce_approval_required_all`, `commerce_default_facilitator`, `commerce_base_rpc`, `commerce_solana_rpc`, `commerce_enable_v2`, `commerce_feature_flag`.

**`middleware/middleware.py` (extend)**
- Wire `ChallengeMiddleware` as optional hook before route dispatch for registered protected resources.

### 3.2 Kyber — `apps/kyber/`

**New feature modules (`src/features/`)**
- `commerce/` — hooks for revenue, treasury, spend timeline.
- `approvals/` — queue, decision, evidence, replay hooks.
- `entitlements/` — issuance, reuse, revoke hooks.
- `settlement/` — settlement state, retry, reconciliation hooks.
- `policies/` — policy read, simulate, edit hooks.
- `facilitators/` — registry, health, routing hooks.
- `resources/` — protected resource registry hooks.

**New adapters (`src/lib/api/`)**
- `commerce.ts`, `approvals.ts`, `entitlements.ts`, `resources.ts`, `settlement.ts`, `policies.ts`, `facilitators.ts`.

**New schemas (`src/lib/schemas/`)**
- `commerce.ts`, `approvals.ts`, `entitlements.ts`, `resources.ts`, `settlement.ts`, `policies.ts`, `facilitators.ts`. Full Zod coverage.

**New components (`src/components/`)**
- `commerce/` — SpendTimeline, RevenueCard, TreasuryPanel, RailBreakdown, FeeEliminationGauge.
- `approvals/` — ApprovalQueue, ApprovalCard, DecisionForm, EvidencePanel, EscalationRouter, GraphImpactPreview.
- `entitlements/` — EntitlementList, EntitlementDetail, ReuseHistory, RevokeDialog.
- `economics/` — ClusterEconomicsView, FacilitatorPerformance, SettlementStatusStrip.

**Fixtures (`src/fixtures/`)**
- `commerce.ts`, `approvals.ts`, `entitlements.ts`, `resources.ts`, `settlement.ts` — deterministic scenarios for Lab replay and tests.

**Page extensions (`src/pages/`)**
- No new top-level pages. Existing 8 pages (Mission, Live, Noesis, Entities, Command, Diagnostics, Review, Lab) each gain commerce-aware panels per §8.

### 3.3 Docs — `docs/`

- `docs/COMMERCE-CONTROL-PLANE.md` — architecture
- `docs/APPROVAL-MODEL.md` — operator workflows
- `docs/PROTECTED-RESOURCES.md` — registration guide
- `docs/STABLECOIN-RAILS.md` — asset/network/facilitator matrix
- `docs/Kyber-OPERATOR-GUIDE.md` — operator handbook
- `docs/SUPPORT-DEBUG-GUIDE.md` — incident playbook
- `docs/INTELLIGENCE-GRAPH.md` — amend with L3b control-plane additions


---

## 4. Graph Schema Specification

All additions live in `shared/graph/graph.py` (enum extensions) and are documented in `shared/graph/economic_schema.py`.

### 4.1 New Vertex Types

| Vertex | Owner | Tenant | Provenance | Audit | DSR | Source of truth |
|---|---|---|---|---|---|---|
| `PAYMENT_REQUIREMENT` | control_plane | prefixed | challenge issued | required | pseudonymize on user DSR | control_plane.issue_challenge |
| `PAYMENT_AUTHORIZATION` | control_plane | prefixed | approval decision | required | pseudonymize | approvals.apply_decision |
| `PAYMENT_RECEIPT` | verification | prefixed | verify step | required | retain (financial record) | verification.verify |
| `SETTLEMENT` | settlement | prefixed | FSM transition | required | retain | settlement FSM |
| `ENTITLEMENT` | entitlements | prefixed | mint/reuse | required | pseudonymize | entitlements.mint |
| `ACCESS_GRANT` | control_plane | prefixed | grant step | required | pseudonymize | control_plane.grant_access |
| `FACILITATOR` | facilitators | global + tenant allow | admin registration | required | N/A | facilitators registry |
| `PRICE_POLICY` | pricing | per-tenant | admin/policy UI | required | N/A | policies repo |
| `BUDGET_POLICY` | policies | per-tenant | admin/policy UI | required | N/A | policies repo |
| `TREASURY` | commerce | per-tenant | treasury config | required | N/A | treasury repo |
| `STABLECOIN_ASSET` | facilitators | global | seed + admin | required | N/A | asset registry |
| `SERVICE_PLAN` | commerce | per-tenant | admin | required | N/A | plans repo |
| `PAYMENT_ROUTE` | facilitators | per-tenant | routing decision | required | N/A | route selection |
| `FULFILLMENT` | control_plane | prefixed | fulfillment record | required | pseudonymize | control_plane.record_fulfillment |
| `POLICY_DECISION` | policies | prefixed | evaluation | required | retain | PolicyEngine.evaluate |
| `APPROVAL_REQUEST` | approvals | prefixed | requester | required | pseudonymize | approvals.request |
| `APPROVAL_DECISION` | approvals | prefixed | approver | required | pseudonymize | approvals.decide |
| `ECONOMIC_CLUSTER` | analytics | per-tenant | clustering job | optional | pseudonymize | analytics projection |

All tenant-prefixed vertices use `{tenant_id}:{vertex_id}` keys (consistent with existing `X402EconomicGraph` pattern).

### 4.2 New Edge Types

| Edge | From → To | Properties | Creation path |
|---|---|---|---|
| `REQUIRES_PAYMENT` | ProtectedResource → PAYMENT_REQUIREMENT | amount_usd, chain, asset | challenge issuance |
| `OFFERS_PAYMENT_OPTION` | PAYMENT_REQUIREMENT → STABLECOIN_ASSET | preferred, priority | price policy |
| `AUTHORIZED_BY` | PAYMENT_REQUIREMENT → PAYMENT_AUTHORIZATION | decided_at | approval decision |
| `VERIFIED_BY` | PAYMENT_AUTHORIZATION → FACILITATOR | tx_hash, verified_at | verification |
| `SETTLED_BY` | PAYMENT_RECEIPT → SETTLEMENT | state, retries | settlement FSM |
| `GRANTS_ACCESS_TO` | ENTITLEMENT → ProtectedResource | scope, expires_at | entitlement mint |
| `FULFILLED_BY` | ACCESS_GRANT → FULFILLMENT | latency_ms, status | fulfillment record |
| `FUNDED_BY` | PAYMENT_AUTHORIZATION → TREASURY | amount | treasury deduction |
| `PRICES_IN` | SERVICE_PLAN → STABLECOIN_ASSET | unit_price | plan config |
| `ACCEPTS_ASSET` | ProtectedResource → STABLECOIN_ASSET | priority | resource policy |
| `PREFERS_NETWORK` | TREASURY → Chain | priority | treasury config |
| `CONSTRAINED_BY` | AGENT/USER → BUDGET_POLICY | role | policy binding |
| `SUBSCRIBES_TO` | USER/AGENT → SERVICE_PLAN | started_at, expires_at | subscription |
| `REUSES_ENTITLEMENT` | AGENT → ENTITLEMENT | count, last_used | SIWX reuse |
| `RETRIED_AS` | SETTLEMENT → SETTLEMENT | reason, attempt | retry |
| `ESCALATES_PAYMENT_TO` | APPROVAL_REQUEST → USER | reason | escalation |
| `GUARDED_BY_POLICY` | ProtectedResource → PRICE_POLICY/BUDGET_POLICY | active | policy binding |
| `ROUTES_VIA` | PAYMENT_AUTHORIZATION → PAYMENT_ROUTE | facilitator_id | route selection |
| `APPROVED_BY` | APPROVAL_DECISION → USER | role | approver |
| `REJECTED_BY` | APPROVAL_DECISION → USER | reason | rejecter |
| `REQUESTS_APPROVAL_FROM` | APPROVAL_REQUEST → USER | priority | queue assignment |
| `GOVERNED_BY` | TENANT/AGENT → POLICY_DECISION | context | policy eval |

Existing edges (`PAYS`, `CONSUMES`, `HIRED`, `DELEGATES`, `LAUNCHED_BY`, etc.) retained and continue to be written by `economic_graph.snapshot_to_graph()` alongside new edges.

### 4.3 Graph query purposes

| Query | Reader | Purpose |
|---|---|---|
| `trace_payment_lifecycle(challenge_id)` | Kyber Noesis, Review | full lifecycle trace for one payment |
| `agent_entitlements(agent_id)` | Kyber Entities, SDK preflight | active entitlements per agent |
| `service_revenue(service_id, window)` | Kyber Entities, Mission | revenue rollup |
| `cluster_spend(cluster_id)` | Kyber Entities, Diagnostics | cluster anomaly detection |
| `policy_chain(resource_id)` | Kyber Entities, explainability | which policies fire |
| `facilitator_performance(facilitator_id)` | Kyber Command, Diagnostics | facilitator reliability |
| `approval_backlog(tenant_id)` | Kyber Command, Mission | queue size + latency |

### 4.4 Kyber visualization mapping

| Graph object | Kyber rendering |
|---|---|
| PAYMENT_REQUIREMENT | Noesis node, Review detail card, Mission recommendation |
| APPROVAL_REQUEST | Noesis node, Review queue item, Command backlog |
| ENTITLEMENT | Entities timeline, Noesis node, Entity 360 |
| SETTLEMENT | Diagnostics strip, Noesis edge, Entity history |
| POLICY_DECISION | Explainability drawer across Review/Diagnostics/Entities |
| FACILITATOR | Command subsystem card, Diagnostics health |
| TREASURY | Entities (tenant view), Mission treasury panel |


---

## 5. API Specification

All routes require `request.state.tenant` (JWT or API key) and explicit `require_permission()` checks. All responses use existing `APIResponse` envelope. All inputs validated via Pydantic.

### 5.1 Control Plane (`services/x402/routes.py`)

| Method | Path | Scope | Purpose |
|---|---|---|---|
| POST | `/v1/x402/challenge` | `commerce:challenge` | Issue PAYMENT-REQUIRED for a protected resource + context |
| POST | `/v1/x402/verify` | `commerce:verify` | Submit PaymentProof for verification |
| POST | `/v1/x402/settle` | `commerce:settle` | Trigger/query settlement for a receipt |
| GET | `/v1/x402/receipts/{capture_id}` | `x402:read` | Retrieve receipt |
| GET | `/v1/x402/settlements/{id}` | `x402:read` | Retrieve settlement state |
| POST | `/v1/x402/access/preflight` | `x402:read` | SDK: can agent X access resource Y? |
| GET | `/v1/x402/entitlements/{id}` | `entitlements:read` | Entitlement detail |
| GET | `/v1/x402/entitlements?agent_id=` | `entitlements:read` | Agent's active entitlements |
| POST | `/v1/x402/entitlements/{id}/revoke` | `entitlements:write` | Revoke entitlement |
| GET | `/v1/x402/explain/{challenge_id}` | `x402:read` | Explainability for a payment lifecycle |

### 5.2 Protected Resources

| Method | Path | Scope | Purpose |
|---|---|---|---|
| GET | `/v1/x402/resources` | `resources:admin` or `x402:read` | List all protected resources |
| POST | `/v1/x402/resources` | `resources:admin` | Register new protected resource |
| PATCH | `/v1/x402/resources/{id}` | `resources:admin` | Update classification/price |
| GET | `/v1/x402/resources/{id}` | `x402:read` | Resource metadata + pricing + accepted assets |
| GET | `/v1/x402/resources/{id}/policy` | `x402:read` | Active policy chain |

### 5.3 Policies

| Method | Path | Scope | Purpose |
|---|---|---|---|
| GET | `/v1/x402/policies` | `commerce:policy` | List policies |
| POST | `/v1/x402/policies` | `commerce:policy` | Create policy |
| PATCH | `/v1/x402/policies/{id}` | `commerce:policy` | Update policy |
| POST | `/v1/x402/policies/simulate` | `commerce:policy` | Dry-run policy against context |
| GET | `/v1/x402/policies/decisions/{id}` | `x402:read` | Decision rationale |

### 5.4 Facilitators & Assets

| Method | Path | Scope | Purpose |
|---|---|---|---|
| GET | `/v1/x402/facilitators` | `x402:read` | List approved facilitators |
| POST | `/v1/x402/facilitators` | `commerce:admin` | Register facilitator |
| GET | `/v1/x402/facilitators/{id}/health` | `x402:read` | Health + performance metrics |
| GET | `/v1/x402/assets` | `x402:read` | Approved stablecoin assets + networks |
| POST | `/v1/x402/assets` | `commerce:admin` | Register asset |

### 5.5 Approvals (`services/x402/approvals_routes.py`)

| Method | Path | Scope | Purpose |
|---|---|---|---|
| GET | `/v1/approvals` | `approvals:read` | Queue with filters (status, priority, assignee) |
| GET | `/v1/approvals/{id}` | `approvals:read` | Approval detail + evidence |
| POST | `/v1/approvals/{id}/assign` | `approvals:write` | Assign approver |
| POST | `/v1/approvals/{id}/decide` | `approvals:write` + `commerce:approve` | approve/reject/escalate/hold |
| POST | `/v1/approvals/{id}/escalate` | `approvals:write` | Escalate to higher authority |
| POST | `/v1/approvals/{id}/revoke` | `approvals:write` | Revoke prior approval |
| POST | `/v1/approvals/{id}/replay` | `approvals:read` | Deterministic replay in Lab |
| GET | `/v1/approvals/{id}/evidence` | `approvals:read` | Full evidence bundle |
| GET | `/v1/approvals/{id}/preview` | `approvals:read` | Graph impact preview |

### 5.6 Commerce Analytics (`services/commerce/routes.py` extend)

| Method | Path | Scope | Purpose |
|---|---|---|---|
| GET | `/v1/commerce/revenue/{service_id}` | `commerce:read` | Service revenue over window |
| GET | `/v1/commerce/agents/{id}/economics` | `commerce:read` | Agent economic profile |
| GET | `/v1/commerce/cluster/{id}/spend` | `commerce:read` | Cluster spend analytics |
| GET | `/v1/commerce/treasury` | `commerce:admin` | Treasury balance + runway |
| GET | `/v1/commerce/facilitators/performance` | `commerce:read` | Performance matrix |

### 5.7 Admin

| Method | Path | Scope | Purpose |
|---|---|---|---|
| GET | `/v1/admin/tenants/{id}/commerce` | `commerce:admin` | Tenant commerce settings |
| PATCH | `/v1/admin/tenants/{id}/commerce` | `commerce:admin` | Update settings (approval posture, budgets, etc.) |
| GET | `/v1/admin/tenants/{id}/commerce/diagnostics` | `commerce:admin` | Reconciliation drift, stuck approvals |

### 5.8 SDK APIs (public)

| Method | Path | Scope | Purpose |
|---|---|---|---|
| POST | `/v1/sdk/x402/preflight` | `x402:read` | Resource availability + price quote |
| GET | `/v1/sdk/x402/entitlement/status` | `entitlements:read` | Active entitlement lookup |
| GET | `/v1/sdk/x402/receipts/{id}` | `x402:read` | Receipt retrieval |
| GET | `/v1/sdk/x402/stream` | `x402:read` | SSE/WebSocket for commerce events |

### 5.9 Error contracts

Typed errors (all using existing error patterns):
- `ChallengeRequiredError` (402)
- `ApprovalPendingError` (202 Accepted with approval_id)
- `ApprovalDeniedError` (403)
- `PolicyDeniedError` (403 with decision_id)
- `SettlementPendingError` (202)
- `SettlementFailedError` (402 retry-after)
- `UnsupportedAssetError` (400)
- `UnsupportedNetworkError` (400)
- `DuplicatePaymentError` (409 with existing capture_id)
- `EntitlementExpiredError` (401)
- `FacilitatorUnavailableError` (503)

Every route has: request schema, response schema, example payloads, integration tests, OpenAPI docs.


---

## 6. Event and Lake Specification

### 6.1 New Event Topics (`shared/events/economic_topics.py`)

All follow existing `aether.<domain>.<entity>.<action>` convention.

| Topic | Producer | Consumers |
|---|---|---|
| `aether.commerce.challenge.issued` | control_plane | lake, graph_mutations, analytics, Kyber stream |
| `aether.commerce.requirement.generated` | control_plane | lake |
| `aether.commerce.approval.requested` | approvals | lake, Kyber Command/Mission |
| `aether.commerce.approval.assigned` | approvals | lake, Kyber |
| `aether.commerce.approval.approved` | approvals | control_plane, lake, audit |
| `aether.commerce.approval.rejected` | approvals | control_plane, lake, audit |
| `aether.commerce.approval.escalated` | approvals | lake, Kyber |
| `aether.commerce.approval.expired` | approvals | lake, diagnostics |
| `aether.commerce.approval.revoked` | approvals | control_plane, lake, audit |
| `aether.commerce.payment.submitted` | control_plane | verification |
| `aether.commerce.verification.started` | verification | lake |
| `aether.commerce.verification.succeeded` | verification | settlement, lake |
| `aether.commerce.verification.failed` | verification | diagnostics, lake |
| `aether.commerce.settlement.started` | settlement | lake |
| `aether.commerce.settlement.pending` | settlement | lake, Kyber |
| `aether.commerce.settlement.completed` | settlement | entitlements, lake |
| `aether.commerce.settlement.failed` | settlement | diagnostics, lake |
| `aether.commerce.entitlement.granted` | entitlements | control_plane, lake |
| `aether.commerce.entitlement.reused` | entitlements | analytics, lake |
| `aether.commerce.entitlement.revoked` | entitlements | lake, audit |
| `aether.commerce.entitlement.expired` | entitlements | lake |
| `aether.commerce.access.granted` | control_plane | lake, fulfillment |
| `aether.commerce.access.denied` | control_plane | diagnostics, lake, audit |
| `aether.commerce.policy.denied` | policies | diagnostics, audit |
| `aether.commerce.facilitator.route_selected` | facilitators | lake |
| `aether.commerce.kyber.action_logged` | kyber_api | audit, lake |
| `aether.commerce.operator.action_logged` | any | audit, lake |
| `aether.commerce.replay.executed` | lab/approvals | audit |
| `aether.commerce.reconciliation.task_created` | settlement/diagnostics | Kyber Diagnostics |
| `aether.commerce.reconciliation.task_resolved` | diagnostics | lake, audit |

### 6.2 Event Schemas (`shared/events/economic_schemas.py`)

Every topic has a typed Pydantic payload with: `tenant_id`, `correlation_id`, `challenge_id` (if applicable), `actor_id`, `actor_type`, and domain-specific fields. Versioned (`schema_version`). Serialized via existing `Event.serialize()`.

### 6.3 Lake Tiers

**Bronze (raw)** — S3 partitioned by `tenant_id/date/topic/`:
- `commerce_events_raw/` — every event as JSONL

**Silver (normalized)** — Parquet, partitioned by tenant + day:
- `commerce_challenges/` — one row per challenge
- `commerce_approvals/` — one row per approval request (+ decision columns)
- `commerce_verifications/` — one row per verification attempt
- `commerce_settlements/` — one row per settlement FSM transition
- `commerce_entitlements/` — one row per grant/reuse/revoke/expire
- `commerce_access_grants/` — one row per grant
- `commerce_fulfillments/` — one row per fulfillment
- `commerce_policy_decisions/` — one row per evaluation

**Gold (aggregates)** — ClickHouse/Iceberg:
- `gold_spend_rate_1h` — spend per tenant per service per hour
- `gold_approval_latency` — percentiles per queue per day
- `gold_approval_volume` — counts per status per tenant per day
- `gold_service_revenue` — revenue per service per window
- `gold_settlement_health` — success/fail/pending rates per facilitator per chain
- `gold_facilitator_performance` — latency, verify rate, settle rate
- `gold_entitlement_reuse` — reuse count per entitlement per day
- `gold_duplicate_payment_risk` — dedup hits per tenant
- `gold_stablecoin_rail_usage` — volume per asset per network per day
- `gold_cluster_economic_anomalies` — cluster spend z-scores
- `gold_policy_denial_reasons` — top denial reasons per tenant

### 6.4 Rebuildability

Graph state in Neptune for commerce vertices/edges MUST be deterministically rebuildable from Silver tables. `shared/graph/economic_mutations.py` exposes:
- `rebuild_from_silver(tenant_id, since)` — replays commerce Silver records into graph mutations
- `verify_graph_consistency(tenant_id)` — compares Silver aggregates to graph traversal counts
- `reconciliation_drift(tenant_id)` — returns drift per vertex/edge type

This is exercised by the nightly reconciliation job and exposed via Diagnostics API.


---

## 7. Approval Model Specification

### 7.1 Mandatory approval at GA

At launch, **every spend-bearing access path** passes through `ApprovalService`. The config flag `commerce_approval_required_all=true` is the Day-1 default and cannot be set to false by self-service. Per-tenant opt-down requires explicit admin action with audit record.

### 7.2 States & transitions

```
pending → assigned → (approved | rejected | escalated | expired | revoked)
escalated → assigned (reassignment) | approved | rejected | expired
approved → revoked
```

All transitions persist to `approvals` Postgres table + emit event + write graph edge + write audit record.

### 7.3 ApprovalRequest model

```
ApprovalRequest {
  id, tenant_id, challenge_id, resource_id, requester_id (agent/user),
  amount_usd, asset, network, facilitator_id, priority (low|normal|high|critical),
  reason, context (dict), policy_decision_id, created_at, expires_at,
  status, assigned_to, decided_at, decided_by, decision_reason,
  escalation_chain[], evidence_bundle_url, replay_hash
}
```

### 7.4 Queue & assignment

- Queue backed by Postgres with Redis index for fast filter/sort.
- Default assignment: round-robin within approver pool, with capacity limits.
- Manual assignment from Kyber Command/Review.
- SLA: `normal` expires in 1h, `high` in 15m, `critical` in 5m. Configurable per tenant.

### 7.5 Decision inputs

Approver sees in Kyber Review:
- Challenge detail + resource detail
- Policy decision chain with rationale
- Budget/treasury impact preview
- Requester economic history (spend rate, denial rate)
- Duplicate-payment risk flag
- Facilitator health
- Graph impact preview (which edges/vertices will be written)
- Evidence bundle (related receipts, prior approvals, linked entitlements)

### 7.6 Override

`decide(action=override, reason=required)` allows admin-level bypass of a policy-denied request. Override is:
- Requires `commerce:admin` scope
- Always audited with reason
- Always emits `approval.approved` event with `override=true` flag
- Flagged in Kyber Review with distinct visual treatment

### 7.7 Replay

`POST /v1/approvals/{id}/replay` executes the approval in deterministic mock mode in Lab:
- Re-evaluates policies with original context
- Shows decision tree
- Does not mutate graph or emit production events
- Writes to `commerce_replay_log` table

### 7.8 Revoke

Approved requests can be revoked before settlement. Revoke:
- Cancels pending settlement attempts
- Marks entitlement (if minted) as revoked
- Emits `approval.revoked` + `entitlement.revoked` events
- Audits

### 7.9 Enforcement points

| Point | Enforcement |
|---|---|
| `ChallengeMiddleware` | Issues challenge but does not grant access until approval present |
| `control_plane.apply_decision` | Rejects if approval missing/expired/revoked |
| `entitlements.mint` | Requires valid approval_id in input |
| `graph writes` | `GRANTS_ACCESS_TO` edge never written without approval reference |


---

## 8. Kyber Integration Specification by Page

All pages follow: feature module → data hook → adapter → Zod schema → PermissionGate → action handler → real API → real event → audit. Degrades read-only if permission insufficient. Production default is observer posture.

### 8.1 Mission

| Panel | Feature module | Adapter | Permission | Actions |
|---|---|---|---|---|
| Recommended Actions | `features/commerce` | `lib/api/commerce.ts` | `commerce:read` / `approvals:write` | Acknowledge, assign, open approval queue, jump to Review |
| Approval Backlog Summary | `features/approvals` | `lib/api/approvals.ts` | `approvals:read` | Open queue, approve/reject/escalate if authorized |
| Treasury Runway | `features/commerce` | `lib/api/commerce.ts` | `commerce:read` | Open Treasury detail in Entities |
| Incidents | existing | existing | existing | Trigger safe incident actions (already supported) + commerce incident surfacing |

Empty/error/loading: skeleton cards; error states show retry + link to Diagnostics.

### 8.2 Live

| Panel | Feature module | Adapter | Permission | Actions |
|---|---|---|---|---|
| Event Stream (commerce) | existing + `features/commerce` | existing + commerce SSE | `commerce:read` | Acknowledge, route, escalate, inline approve/reject if authorized |
| Inline payment/approval | `features/approvals` | `lib/api/approvals.ts` | `approvals:write` | Approve/reject directly from stream row |
| Pivot | existing | existing | N/A | Jump to Review/Diagnostics/Entity detail |

### 8.3 Noesis (Graph Operator UI)

| Panel | Feature module | Adapter | Permission | Actions |
|---|---|---|---|---|
| Graph Canvas | existing + commerce nodes | `lib/api/commerce.ts` + existing graph api | `commerce:read` | Inspect, trace payment lifecycle |
| Object Actions | `features/approvals`, `features/entitlements` | adapters | `approvals:write`, `entitlements:write` | Apply hold, revoke entitlement, open explainability |
| Economic Path Trace | `features/commerce` | `lib/api/commerce.ts` | `commerce:read` | Trace challenge → grant across graph |
| Diff/Compare | existing | existing | `commerce:read` | Compare state transitions side-by-side |

### 8.4 Entities

| Panel | Feature module | Adapter | Permission | Actions |
|---|---|---|---|---|
| Entity Economic Profile | `features/commerce` | `lib/api/commerce.ts` | `commerce:read` | View spend, revenue, entitlements |
| Policy Posture Editor | `features/policies` | `lib/api/policies.ts` | `commerce:policy` | Update budget/asset/network constraints |
| Entitlement Management | `features/entitlements` | `lib/api/entitlements.ts` | `entitlements:write` | Refresh, revoke entitlements |
| Treasury Config | `features/commerce` | `lib/api/commerce.ts` | `commerce:admin` | Apply treasury preferences |
| Approval/Settlement History | `features/approvals`, `features/settlement` | adapters | `approvals:read`, `x402:read` | Inspect history |

### 8.5 Command

| Panel | Feature module | Adapter | Permission | Actions |
|---|---|---|---|---|
| Commerce Subsystem | `features/commerce` | `lib/api/commerce.ts` | `commerce:read` | View facilitator health, queue depth, assign ownership |
| Approval Backlog | `features/approvals` | `lib/api/approvals.ts` | `approvals:read` | Reroute queue, escalate SLAs |
| Incident routing | existing | existing | existing | Acknowledge/escalate commerce incidents |

### 8.6 Diagnostics

| Panel | Feature module | Adapter | Permission | Actions |
|---|---|---|---|---|
| Verification Failures | `features/commerce` | `lib/api/commerce.ts` | `commerce:read` | Open detail, trigger recheck |
| Settlement Drift | `features/settlement` | `lib/api/settlement.ts` | `commerce:read` | Open reconciliation task |
| Approval Expirations | `features/approvals` | `lib/api/approvals.ts` | `approvals:read` | Reassign, extend SLA |
| Reconciliation Tasks | `features/settlement` | `lib/api/settlement.ts` | `commerce:admin` | Resolve/suppress |
| Safe Replay/Recheck | `features/commerce` | `lib/api/commerce.ts` | `commerce:read` | Trigger safe replay |

### 8.7 Review

| Panel | Feature module | Adapter | Permission | Actions |
|---|---|---|---|---|
| Approval Queue | `features/approvals` | `lib/api/approvals.ts` | `approvals:read` | Filter, assign |
| Decision Form | `features/approvals` | `lib/api/approvals.ts` | `commerce:approve` | Approve, reject, escalate, annotate, require follow-up |
| Evidence Panel | `features/approvals` | `lib/api/approvals.ts` | `approvals:read` | Review evidence bundle |
| Graph Impact Preview | `features/approvals` | `lib/api/approvals.ts` | `approvals:read` | Preview graph writes before decision |
| Compare Evidence | `features/approvals` | `lib/api/approvals.ts` | `approvals:read` | Side-by-side with similar cases |

### 8.8 Lab

| Panel | Feature module | Adapter | Permission | Actions |
|---|---|---|---|---|
| Commerce Flow Replay | `features/commerce` | `lib/api/commerce.ts` | `commerce:read` | Deterministic replay of full lifecycle |
| Approval Scenario Replay | `features/approvals` | `lib/api/approvals.ts` | `approvals:read` | Replay with mutated policies |
| Settlement Scenario | `features/settlement` | `lib/api/settlement.ts` | `commerce:read` | Simulate pending/failed/disputed |
| Evidence Export | `features/approvals` | `lib/api/approvals.ts` | `approvals:read` | Export bundle for audit |
| Parity Check | existing | all adapters | `commerce:read` | Mock vs live parity tests |

### 8.9 Kyber technical integration rules (applied to all)

- Every adapter call passes through Zod validation at response boundary.
- Every mutation passes through PermissionGate.
- Every action emits `aether.commerce.kyber.action_logged` event with: `page`, `action`, `actor_id`, `tenant_id`, `target_id`, `result`.
- Mock mode: uses fixtures in `src/fixtures/commerce.ts` etc., no network.
- Staging: hits staging backend, real data, non-production events.
- Production: defaults to observer posture; action permissions must be explicitly granted via RBAC.
- Lab replay is deterministic: fixtures + replay seeds stored in `src/fixtures/commerce-replay/`.
- Every action-capable panel has e2e Playwright test covering auth/gated/loading/empty/error/success paths.


---

## 9. Stablecoin Support Specification

### 9.1 Day-1 assets

| Asset | Chain | Network | CAIP-2 | Contract/Mint | Decimals | Facilitator compat |
|---|---|---|---|---|---|---|
| USDC | Base | mainnet | `eip155:8453` | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` | 6 | Aether-local, Circle, facilitator-v2 |
| USDC | Solana | mainnet | `solana:mainnet` | `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v` | 6 | Aether-local, Circle, facilitator-v2 |

### 9.2 Asset metadata (`STABLECOIN_ASSET` vertex)

```
{
  symbol, chain, network, caip2, issuer, contract_address, decimals,
  settlement_scheme (on-chain|facilitator|hybrid),
  facilitator_ids[], tenant_allow_state, treasury_preference_score,
  normalization_rules, risk_metadata, resource_compatibility[],
  created_at, active
}
```

### 9.3 Extensibility

- Adding a new asset = inserting a `STABLECOIN_ASSET` vertex + config. No code change.
- Adding a new network = adding chain metadata + verifier plugin in `verification.py`.
- Adding a new facilitator = `POST /v1/x402/facilitators` with endpoint, capabilities, approved asset list.
- Per-tenant asset allow/deny via `ACCEPTS_ASSET` edges with `tenant_id` property.

### 9.4 Verification by chain

- **Base (USDC):** `BaseUSDCVerifier` validates tx_hash on Base RPC, checks ERC-20 Transfer event, confirms recipient/amount/confirmations.
- **Solana (USDC):** `SolanaUSDCVerifier` validates signature on Solana RPC, checks SPL Transfer, confirms recipient/amount/slot.

Both support facilitator-delegated verification as primary with local verification as fallback.

### 9.5 Out of scope

- Trading, swapping, or price discovery.
- Non-stablecoin assets.
- Non-Base/non-Solana rails (architected, not shipped).
- External provider asset catalogs (second wave).


---

## 10. Auth / Compliance / Audit Specification

### 10.1 New permission scopes (`shared/auth/auth.py`)

- `commerce:challenge`, `commerce:verify`, `commerce:settle`
- `commerce:approve`, `commerce:review`, `commerce:policy`
- `commerce:admin`, `commerce:read`
- `approvals:read`, `approvals:write`
- `entitlements:read`, `entitlements:write`
- `resources:admin`

### 10.2 Kyber roles

| Role | Scopes |
|---|---|
| viewer | `*:read` only |
| operator | viewer + `approvals:write`, `entitlements:write`, `commerce:settle` |
| approver | operator + `commerce:approve`, `commerce:review` |
| admin | all commerce scopes including `commerce:admin`, `resources:admin`, `commerce:policy` |

### 10.3 Tenant isolation

All commerce vertices use tenant-prefixed keys. All Postgres queries filter by `tenant_id`. All events carry `tenant_id`. Cross-tenant reads denied at repo layer. Admin dashboards require explicit `tenant_scope=` parameter with audit.

### 10.4 DSR / GDPR cascade

Extend `gdpr/data_subject_rights/dsr_engine.py`:

| Object | DSR action |
|---|---|
| PAYMENT_REQUIREMENT | pseudonymize requester_id |
| APPROVAL_REQUEST/DECISION | pseudonymize requester/approver |
| ENTITLEMENT | pseudonymize holder |
| ACCESS_GRANT | pseudonymize holder |
| FULFILLMENT | pseudonymize |
| PAYMENT_RECEIPT / SETTLEMENT | retain (financial record obligation) but pseudonymize PII fields |

Cascade: user DSR → user's agents → agents' entitlements/approvals → pseudonymize across all commerce vertices.

### 10.5 Audit actions (`audit_engine.py`)

Add: `CHALLENGE_ISSUED`, `APPROVAL_REQUESTED`, `APPROVAL_DECIDED`, `APPROVAL_OVERRIDE`, `APPROVAL_REVOKED`, `VERIFICATION_COMPLETED`, `SETTLEMENT_COMPLETED`, `ENTITLEMENT_MINTED`, `ENTITLEMENT_REVOKED`, `ACCESS_GRANTED`, `ACCESS_DENIED`, `POLICY_DENIED`, `RESOURCE_REGISTERED`, `RESOURCE_UPDATED`, `FACILITATOR_REGISTERED`, `TREASURY_UPDATED`, `POLICY_UPDATED`, `KYBER_ACTION`, `COMMERCE_OVERRIDE`.

Every transition persists to audit store with actor, timestamp, tenant, correlation_id, before/after state.

### 10.6 Privacy-aware field masking

Extend `shared/privacy/access_control.py`:
- `tx_hash`: `internal` tier, visible to `operator+`
- `wallet_address`: `confidential`, visible to `compliance+`
- `amount_usd`: `internal`, visible to `operator+`
- `payer_agent_id`: `internal`, masked for `viewer`
- `approval reason`: `confidential`, visible to `approver+`

### 10.7 Replay protection

- `Payment-Identifier` required on all verify submissions, Redis TTL 24h, dedupe returns existing capture.
- SIWX nonces for entitlement reuse.
- Settlement FSM idempotent on tx_hash.

### 10.8 Rate limiting / abuse controls

- Existing tier-based rate limiter extended with commerce-specific buckets: `challenge_rpm`, `verify_rpm`, `approval_rpm`.
- Per-tenant hard caps on pending approvals (default 10k) and open entitlements.
- Suspicious duplicate-payment pattern → circuit breaker halts tenant commerce ops + Diagnostics alert.

### 10.9 Mandatory approval enforcement

Enforced at 4 layers (see §7.9) — any bypass attempt emits `commerce.override` audit and alerts on Command page.


---

## 11. Observability / Support Specification

### 11.1 Metrics (Prometheus, extending existing `metrics` interface)

- `commerce_challenges_issued_total{tenant,resource,asset,network}`
- `commerce_approvals_requested_total{tenant,priority}`
- `commerce_approvals_decided_total{tenant,decision}`
- `commerce_approval_latency_seconds{tenant,priority}` (histogram)
- `commerce_verifications_total{tenant,facilitator,result}`
- `commerce_settlement_duration_seconds{facilitator,chain}` (histogram)
- `commerce_settlement_state{tenant,state}` (gauge)
- `commerce_entitlements_active{tenant}` (gauge)
- `commerce_entitlement_reuse_total{tenant}`
- `commerce_access_granted_total{tenant,resource}`
- `commerce_access_denied_total{tenant,reason}`
- `commerce_policy_denials_total{tenant,policy_type}`
- `commerce_facilitator_health{facilitator}` (gauge)
- `commerce_duplicate_payment_detected_total{tenant}`
- `commerce_graph_mutations_total{vertex_type,edge_type}`
- `commerce_reconciliation_drift{tenant,type}` (gauge)

### 11.2 Structured logs

Every commerce operation logs with: `correlation_id`, `tenant_id`, `challenge_id`, `actor_id`, `resource_id`, `action`, `result`, `duration_ms`. Logs route to existing logger infrastructure.

### 11.3 Trace IDs / request IDs

Extend existing `X-Request-ID` correlation through challenge → approval → verify → settle → entitle → grant → fulfill, all sharing a single `correlation_id`.

### 11.4 Diagnostics endpoints

- `GET /v1/diagnostics/commerce/health` — health of all commerce subsystems
- `GET /v1/diagnostics/commerce/stuck-approvals` — list stuck approvals
- `GET /v1/diagnostics/commerce/settlement-drift` — pending/failed settlements
- `GET /v1/diagnostics/commerce/reconciliation` — graph vs silver drift
- `POST /v1/diagnostics/commerce/replay/{correlation_id}` — safe replay
- `POST /v1/diagnostics/commerce/recheck/{settlement_id}` — force recheck

### 11.5 Circuit breakers

- Facilitator failure rate > 20% over 5m → pause that facilitator, route around it.
- Tenant duplicate-payment spike > 10/min → halt tenant commerce, Diagnostics alert.
- Settlement failure rate > 15% → page Command with incident.

### 11.6 Dashboards (Grafana)

- Approval Queue dashboard
- Settlement Health dashboard
- Facilitator Performance dashboard
- Stablecoin Rail Usage dashboard
- Commerce Revenue dashboard
- Reconciliation Drift dashboard

### 11.7 Alerts

- Approval latency p95 > SLA → warn
- Settlement failure rate > 5% for 10m → critical
- Facilitator health down → critical
- Reconciliation drift > 0 → warn (daily job)
- Mandatory approval bypass attempt → critical

### 11.8 Reconciliation tools

Nightly job: `reconcile_commerce(tenant_id)`:
1. Reads Silver tables
2. Replays into temp graph
3. Diffs against production graph
4. Writes drift records to `commerce_reconciliation_tasks`
5. Surfaces in Kyber Diagnostics

### 11.9 Retry / dead-letter

- Verification retries: 3 attempts with exponential backoff before failure.
- Settlement retries: configurable per facilitator, default 5 attempts over 30m.
- Dead-letter queue for events that fail consumer processing 5x → Diagnostics surface.

### 11.10 Support answer coverage

Every support-required question in §17 has a direct diagnostic path:

| Question | Answer via |
|---|---|
| Why denied? | `GET /v1/x402/explain/{challenge_id}` → decision tree |
| Why approval required? | policy_decision_id on challenge |
| Who approved/rejected? | approval.decided_by, audit record |
| Why retried? | settlement retries[] on receipt |
| Why entitlement reused/expired? | entitlement.reuse_count, .expires_at, audit |
| Why Kyber escalated? | event `approval.escalated` with reason |
| Which policy fired? | policy_decision.active_rules[] |
| Which facilitator/network/asset? | route on authorization |
| Settlement pending/failed? | settlement.state + retries |
| What graph state written? | `GET /v1/x402/explain/{id}` returns graph diff |
| Kyber mock vs live? | event carries `kyber_mode` field |

### 11.11 Runbooks

See §14.


---

## 12. Full Testing Plan

### 12.1 Backend unit tests (`tests/unit/commerce/`)

- `test_x402_v2_challenge_normalization.py`
- `test_x402_v1_legacy_compat.py`
- `test_price_policy_resolution.py`
- `test_budget_treasury_policy.py`
- `test_approval_routing.py`
- `test_approval_expiry.py`
- `test_approval_mandatory_enforcement.py`
- `test_entitlement_evaluation.py`
- `test_entitlement_siwx_reuse.py`
- `test_settlement_fsm.py`
- `test_settlement_retry.py`
- `test_idempotency.py`
- `test_asset_network_compatibility.py`
- `test_facilitator_selection.py`
- `test_facilitator_failover.py`
- `test_auth_scopes.py`
- `test_graph_mutation_builders.py`
- `test_graph_rebuild_determinism.py`
- `test_policy_engine.py`
- `test_policy_simulation.py`

### 12.2 Backend integration tests (`tests/integration/commerce/`)

- `test_end_to_end_happy_path.py` — challenge → approval → pay → verify → settle → entitle → grant → fulfill
- `test_approval_reject_path.py`
- `test_approval_expire_path.py`
- `test_approval_revoke_cascade.py`
- `test_approval_override.py`
- `test_all_aether_native_resources.py` — every registered protected resource class
- `test_duplicate_payment_path.py`
- `test_settlement_pending_path.py`
- `test_settlement_failed_retry.py`
- `test_policy_denied_path.py`
- `test_unsupported_asset.py`
- `test_unsupported_network.py`
- `test_cross_tenant_isolation.py`
- `test_lake_to_graph_rebuild.py`
- `test_entitlement_reuse_flow.py`
- `test_siwx_session_binding.py`
- `test_facilitator_outage_failover.py`
- `test_legacy_v1_capture_still_works.py`

### 12.3 Contract tests (`tests/contract/`)

- API schema contracts (OpenAPI snapshot + breaking-change detection)
- Event schema contracts (version pinning + forward compatibility)
- SDK compatibility (web, react-native, iOS, android)
- Kyber adapter Zod parity
- Permission enforcement per route

### 12.4 Kyber tests (`apps/kyber/src/test/`)

Per page (Mission, Live, Noesis, Entities, Command, Diagnostics, Review, Lab):
- Action-capable panels render with correct permissions
- Inline action states (loading/success/error/denied)
- Mock vs live parity
- Production read-only fallback
- PermissionGate enforcement
- Zod validation rejects malformed responses
- E2E Playwright: auth → navigate → action → verify backend effect → verify audit

Specific flows:
- Review: approve, reject, escalate, annotate
- Diagnostics: resolve, replay, recheck
- Entities: policy edit, entitlement revoke
- Noesis: graph action, hold application
- Mission/Live: inline actions
- Lab: replay determinism, evidence export

### 12.5 End-to-end tests (`tests/e2e/`)

- `e2e_h2a_delegated_purchase.py` — user delegates agent to buy access
- `e2e_a2a_paid_service_invocation.py` — agent pays another agent
- `e2e_mandatory_approval_flow.py` — approval gates every spend class
- `e2e_a2h_escalation.py` — agent escalates to human
- `e2e_team_policy_propagation.py` — admin policy changes cascade
- `e2e_kyber_action_full_trace.py` — Kyber action → backend effect → audit → graph
- `e2e_evidence_trail.py` — evidence consistent across Review/Diagnostics/Entities/Noesis

### 12.6 Regression / perf / failure tests

- Existing graph layers still intact (snapshot tests on legacy endpoints)
- Legacy x402 capture still functions
- ML outputs unchanged
- WebSocket fan-out under load (1k concurrent clients)
- Dependency degradation (Redis/Postgres/facilitator outage)
- Malformed payloads (fuzz testing on challenge/verify/settle endpoints)
- Stale entitlement handling
- Replay/idempotency contention (parallel identical Payment-Identifier)
- Neptune failover

### 12.7 Coverage gates

- Unit: ≥ 85% on new modules
- Integration: 100% of lifecycle paths
- E2E: 100% of locked requirements
- Contract: 100% of new API/event schemas
- Kyber: 100% of action-capable panels

### 12.8 CI enforcement

All tests must pass in CI before merge. Contract tests block breaking changes. Kyber Playwright must pass on mock + staging.


---

## 13. Rollout / Migration Plan

### 13.1 Feature flags

- `COMMERCE_CONTROL_PLANE_ENABLED` (master flag, default off)
- `COMMERCE_CHALLENGE_MIDDLEWARE_ENABLED` (per-tenant)
- `COMMERCE_APPROVAL_REQUIRED_ALL` (default true, locked at GA)
- `COMMERCE_FACILITATOR_VERIFY_ENABLED` (per-facilitator)
- `COMMERCE_LOCAL_VERIFY_FALLBACK` (default true)
- `COMMERCE_V2_PROTOCOL` (default true for new challenges)
- `COMMERCE_KYBER_ACTIONS_ENABLED` (per-role, per-page)
- `IG_X402_LAYER` (existing, kept on)

### 13.2 Phased rollout

**Phase 0 — Code landed, flag off (Week 0)**
- All new modules merged behind flags.
- Existing capture path unaffected.
- Schema migrations applied (new Postgres tables).
- Neptune schema extended (enum additions, no backfill required).

**Phase 1 — Internal tenant, mock facilitators (Week 1)**
- Flag on for internal dev tenant.
- Mock facilitator for local verification.
- Kyber in mock mode.
- Full lifecycle exercised via e2e tests.

**Phase 2 — Internal tenant, real Base/Solana verifiers (Week 2)**
- Real verifiers wired.
- Facilitator registry seeded.
- Kyber staging mode.
- Diagnostics + reconciliation validated.

**Phase 3 — Pilot tenant (Week 3)**
- One friendly pilot tenant onboarded.
- All Aether-native protected resources registered.
- Mandatory approval enforced.
- Kyber operator training.

**Phase 4 — GA (Week 4)**
- Flag enabled for all tenants.
- All protected resources covered.
- Kyber action RBAC deployed.
- Runbooks published.

**Phase 5 — External providers (post-GA)**
- Second-wave scope, architected but deferred.

### 13.3 Migration of existing x402 data

- Existing `CapturedX402Transaction` records are treated as legacy v1 captures.
- Backfill job: for each legacy capture, emit synthetic `PAYMENT_REQUIREMENT` → `PAYMENT_RECEIPT` → `SETTLEMENT` (state=completed) → `ENTITLEMENT` (state=expired) vertices so historical data aligns with new schema. No mandatory approval retroactively synthesized.
- Backfill is idempotent, resumable, tenant-scoped, opt-in per tenant.

### 13.4 Rollback plan

- Disable `COMMERCE_CONTROL_PLANE_ENABLED` → new challenges fail open to existing capture flow.
- Rollback graph mutations: `shared/graph/economic_mutations.py` has inverse mutators for every forward mutator.
- Event consumers are additive; disabling flag stops event production, consumers idle.
- Postgres migrations are additive (new tables only); no destructive changes.

### 13.5 Schema migrations

- `migrations/YYYYMMDD_commerce_tables.sql` — creates all Postgres tables.
- `migrations/YYYYMMDD_commerce_indexes.sql` — indexes on tenant_id, challenge_id, approval status, settlement state.
- `migrations/YYYYMMDD_commerce_seed.sql` — seeds assets (USDC Base/Solana), default policies.

### 13.6 SDK rollout

- Web SDK: `X402PaymentEvent` already exists; add preflight client, entitlement status client.
- New SDK version bump (minor, non-breaking).
- Published after backend GA.


---

## 14. Risks and Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Mandatory approval creates SLA pressure | High | Auto-assignment, tiered SLAs, high-capacity approver pools, Command-page SLA dashboards |
| Facilitator outage halts paid flows | High | Multi-facilitator failover, local verification fallback, circuit breakers |
| Graph write volume spikes | Med | Batch graph mutations, existing 30s snapshot cadence preserved, backpressure |
| Duplicate payments | High | Payment-Identifier idempotency + Redis TTL + SIWX nonces + FSM idempotency |
| Kyber action loops (unintended cascading approvals) | Med | Idempotent action keys, confirm-before-write on graph mutations, replay isolation |
| Reconciliation drift between graph and lake | Med | Nightly job, drift metric, Diagnostics surface, deterministic rebuild |
| Legacy v1 capture drift | Med | Keep legacy path functional; back-compat tests; canonicalize via `control_plane.handle_legacy_capture` |
| RBAC gaps in Kyber | High | PermissionGate on every panel, production default observer, test coverage of denied paths |
| Override abuse | High | Admin-only scope, mandatory reason, audit trail, Command alert |
| Approval backlog stalls | High | SLA alerts, escalation chain, backlog gauges, auto-expiry |
| Cross-tenant leakage | Critical | Tenant-prefixed graph keys, repo-level tenant filters, integration test |
| Base/Solana RPC failures | Med | RPC pool, retries, fallback facilitator |
| Mock/live parity drift | Med | Parity tests in Lab, schema contracts |
| Event consumer lag | Med | DLQ, consumer lag alerts, backpressure |
| Audit log bloat | Low | Retention policy, compression, existing audit infra |
| Documentation drift | Med | Docs-as-code, PR checklist requires doc update, CHANGELOG enforced |
| External provider design debt | Low | Architected in asset/facilitator registry; clearly deferred |


---

## 15. Open Product Decisions Still Requiring Confirmation

1. **Approver pool composition** — Who are the default approvers per tenant? Product ops, tenant admins, or dedicated commerce-approver role? *(Recommendation: tenant admins as Day-1 default with opt-in dedicated pool.)*
2. **Default SLA values** — Confirm 5m/15m/1h for critical/high/normal or adjust per operational capacity.
3. **Treasury model** — Per-tenant single treasury vs per-agent sub-budgets at GA? *(Recommendation: per-tenant treasury + optional per-agent sub-budgets, configurable.)*
4. **Legacy v1 capture sunset** — Keep indefinitely or sunset N months post-GA?
5. **Override visibility** — Should override events surface to tenant admins or only internal ops?
6. **Facilitator cost model** — Do we charge per verification, or absorb? Affects treasury accounting.
7. **Entitlement TTL defaults** — 1h? 1 day? Per-resource configurable? *(Recommendation: per-resource, defaulted to 15m for ephemeral, 24h for subscription.)*
8. **SIWX scope** — Which chains/wallets for SIWX reuse at GA? *(Recommendation: Base + Solana only at GA, matching rail scope.)*
9. **Operator training requirement** — Is live Kyber action access gated on training certification?
10. **Evidence bundle retention** — 90 days? 1 year? Audit requirement dictates.
11. **Cross-tenant analytics** — Allowed for global Aether ops? If yes, what anonymization?
12. **External provider integration priority** — Which external providers first in second wave?

---

## 16. Final Definition of Done

The Agentic Commerce Day-1 build is complete only when **every** item below is true and verified:

**Coverage**
- [ ] Every Aether-native protected resource class is registered in the Protected Resource Registry.
- [ ] Every spend class is behind mandatory approval by default.
- [ ] USDC on Base and USDC on Solana are fully operational through verification and settlement.

**Enforcement**
- [ ] Approval is enforced before final paid access at all 4 enforcement layers (middleware, control_plane, entitlements, graph writes).
- [ ] No access grant exists without a corresponding approved `APPROVAL_REQUEST`.
- [ ] Mandatory approval cannot be self-service disabled.

**Lifecycle persistence**
- [ ] Challenge, approval, verification, settlement, entitlement, access grant, fulfillment all persist to Postgres + Silver lake + graph.
- [ ] Graph state is deterministically rebuildable from Silver tables.
- [ ] Every lifecycle transition emits a typed event with correlation_id.

**Kyber**
- [ ] All 8 Kyber pages expose real, audited commerce actions per §8.
- [ ] Every action hits a real API, emits a real event, writes an audit entry.
- [ ] PermissionGate enforced on every action; production defaults to observer.
- [ ] Mock/staging/live parity validated by Lab tests.
- [ ] No fake "live" controls, no placeholder actions.

**Graph explainability**
- [ ] `GET /v1/x402/explain/{challenge_id}` returns full lifecycle trace.
- [ ] Graph queries answer: why access, why denied, which policy, which facilitator.

**Compliance & audit**
- [ ] Every approval/settlement/entitlement/access/policy transition is audited.
- [ ] DSR cascade covers all commerce vertex types.
- [ ] Tenant isolation verified by integration test.
- [ ] Privacy field masking applied per tier/role.

**Support**
- [ ] Every question in §11.10 has a working diagnostic path.
- [ ] Runbooks published for: stuck approval, failed settlement, facilitator outage, reconciliation drift, override review.
- [ ] Diagnostics endpoints live and tested.

**Admin**
- [ ] Admins can configure tenant commerce settings safely (approval posture, budgets, facilitators, assets, treasury).
- [ ] Config changes audited.

**Docs**
- [ ] `COMMERCE-CONTROL-PLANE.md`, `APPROVAL-MODEL.md`, `PROTECTED-RESOURCES.md`, `STABLECOIN-RAILS.md`, `Kyber-OPERATOR-GUIDE.md`, `SUPPORT-DEBUG-GUIDE.md` all published.
- [ ] `INTELLIGENCE-GRAPH.md` amended with L3b control plane.
- [ ] CHANGELOG updated with migration notes.
- [ ] No documentation drift from code.

**Tests**
- [ ] Unit coverage ≥ 85% on new modules.
- [ ] All integration lifecycle paths tested.
- [ ] All e2e locked-requirement flows tested.
- [ ] Contract tests pin API/event schemas.
- [ ] Kyber Playwright covers all action-capable panels.
- [ ] All tests pass in CI.

**Rollout**
- [ ] All new code behind feature flags.
- [ ] Phased rollout plan executed through Phase 4 GA.
- [ ] Rollback plan validated in staging.
- [ ] Schema migrations are additive and reversible.

**Cleanliness**
- [ ] No stubs in core paths.
- [ ] No TODO-only branches.
- [ ] No placeholder APIs.
- [ ] No graph writes that nothing reads.
- [ ] No pages without real backend effects.
- [ ] No unowned operational paths.
- [ ] No untested critical flows.

When all boxes are checked, Agentic Commerce ships.
