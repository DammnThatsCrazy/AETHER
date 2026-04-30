# Aether Agentic Commerce — Control Plane

**Status:** Day-1 GA (feature-flagged via `COMMERCE_CONTROL_PLANE_ENABLED=true`)
**Layer:** L3b+ (extends existing x402 capture L3b)
**Surface:** Backend (`services/x402/`), Kyber (`features/approvals`, `components/commerce`)

---

## 1. What this ships

The Agentic Commerce control plane upgrades Aether's existing x402 capture subsystem into a **graph-native commerce control plane** that:

- Issues x402 v2 payment challenges for protected resources.
- Runs every spend through **mandatory approval** (Day-1 GA default).
- Verifies payments through facilitator-aware + local verification.
- Tracks settlement through a finite state machine.
- Mints time-bound entitlements and grants access.
- Persists the full lifecycle in Neptune via deterministic graph mutations.
- Exposes Kyber operator actions (approve/reject/escalate/revoke, inspect, replay).
- Emits 28+ typed events for lake / analytics / audit consumers.

## 2. Full lifecycle

```
preflight → challenge → policy → approval → authorize → verify → settle → entitle → grant → fulfill
```

Every stage persists to the in-memory commerce store, emits a typed event, writes
one or more graph vertices/edges, and is traceable via `GET /v1/x402/explain/{challenge_id}`.

## 3. Day-1 GA scope

- All Aether-native protected resource classes: `api`, `agent_tool`, `priced_endpoint`, `service_plan`, `internal_capability`.
- Mandatory approval on every spend class.
- USDC on Base (`eip155:8453`) + USDC on Solana (`solana:mainnet`).
- Local facilitator + Circle v2 facilitator.
- Full Kyber Review tab for approval queue.
- Full explainability via lifecycle trace endpoint.

## 4. Architecture

```
                              ┌──────────────────────────┐
  Kyber Review/Command/Noesis → │  /v1/approvals/*         │ ──┐
                              │  /v1/x402/challenge      │   │
                              │  /v1/x402/verify         │   │
                              │  /v1/x402/access/grant   │   │
  Agent SDK preflight       → │  /v1/x402/access/preflight│  │
                              └─────────┬────────────────┘   │
                                        │                    │
                              ┌─────────▼────────────────┐   │
                              │  X402ControlPlane         │   │
                              │  ┌──────────────────────┐ │   │
                              │  │ ResourceRegistry     │ │   │
                              │  │ PolicyEngine         │ │   │
                              │  │ ApprovalService  ★   │ │   │
                              │  │ FacilitatorRegistry  │ │   │
                              │  │ VerificationEngine   │ │   │
                              │  │ SettlementTracker    │ │   │
                              │  │ EntitlementService   │ │   │
                              │  │ IdempotencyStore     │ │   │
                              │  └──────────────────────┘ │   │
                              └───────┬─────────┬────────┘    │
                                      │         │             │
                              ┌───────▼───┐ ┌───▼──────┐  ┌───▼────┐
                              │ Kafka/Events│ │ Neptune  │  │ Audit  │
                              │ (28 topics) │ │ (18 V +  │  │ Engine │
                              │             │ │  22 E)   │  │        │
                              └─────────────┘ └──────────┘  └────────┘

★ = mandatory for every spend class at Day-1 GA
```

## 5. Key modules

| Module | Purpose |
|---|---|
| `services/x402/commerce_models.py` | Canonical Pydantic domain models (shared) |
| `services/x402/commerce_store.py` | Tenant-isolated in-memory store |
| `services/x402/control_plane.py` | Lifecycle orchestrator (`X402ControlPlane`) |
| `services/x402/resources.py` | `ProtectedResourceRegistry` + Day-1 seeds |
| `services/x402/facilitators.py` | Facilitator + asset registries (USDC Base/Solana) |
| `services/x402/policies.py` | `PolicyEngine` — enforces mandatory approval |
| `services/x402/approvals.py` | `ApprovalService` — full workflow FSM |
| `services/x402/verification.py` | Facilitator + local payment verification |
| `services/x402/settlement.py` | Settlement FSM (pending→verifying→settled/failed) |
| `services/x402/entitlements.py` | Entitlement mint/lookup/reuse/revoke |
| `services/x402/pricing.py` | Price resolution with plan discounts |
| `services/x402/idempotency.py` | Payment-Identifier dedupe with TTL |
| `services/x402/economic_mutations.py` | Deterministic graph writers |
| `services/x402/commerce_routes.py` | FastAPI routes (control plane, approvals, entitlements, diagnostics) |

## 6. Graph schema

18 new vertex types + 22 new edge types (see `shared/graph/graph.py`).

**Vertices:** `PaymentRequirement`, `PaymentAuthorization`, `PaymentReceipt`, `Settlement`, `Entitlement`, `AccessGrant`, `Facilitator`, `PricePolicy`, `BudgetPolicy`, `Treasury`, `StablecoinAsset`, `ServicePlan`, `PaymentRoute`, `Fulfillment`, `PolicyDecision`, `ApprovalRequest`, `ApprovalDecision`, `ProtectedResource`.

**Edges:** `REQUIRES_PAYMENT`, `OFFERS_PAYMENT_OPTION`, `AUTHORIZED_BY`, `VERIFIED_BY`, `SETTLED_BY`, `GRANTS_ACCESS_TO`, `FULFILLED_BY`, `PRICES_IN`, `ACCEPTS_ASSET`, `PREFERS_NETWORK`, `CONSTRAINED_BY`, `SUBSCRIBES_TO`, `REUSES_ENTITLEMENT`, `RETRIED_AS`, `ESCALATES_PAYMENT_TO`, `GUARDED_BY_POLICY`, `ROUTES_VIA`, `APPROVED_BY`, `REJECTED_BY`, `REQUESTS_APPROVAL_FROM`, `GOVERNED_BY_POLICY`, `FUNDED_FROM_TREASURY`.

## 7. Event taxonomy

All commerce events published under `aether.commerce.*` topic namespace on the existing Kafka event bus. See `shared/events/events.py` for the 28 topic constants. Every event carries `tenant_id` for multi-tenant isolation.

## 8. Feature flags

| Flag | Default | Purpose |
|---|---|---|
| `COMMERCE_CONTROL_PLANE_ENABLED` | `true` | Master flag |
| `COMMERCE_APPROVAL_REQUIRED_ALL` | `true` | Mandatory approval (locked at GA) |
| `COMMERCE_V2_PROTOCOL` | `true` | x402 v2 for new challenges |
| `IG_X402_LAYER` | `true` | Underlying x402 L3b |

## 9. SDK / API entry points

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/x402/access/preflight` | POST | SDK check: can agent access resource? |
| `/v1/x402/challenge` | POST | Issue payment requirement |
| `/v1/x402/approval/request` | POST | Request approval for a challenge |
| `/v1/x402/authorize` | POST | Create payment authorization |
| `/v1/x402/verify` | POST | Verify tx + settle + mint entitlement |
| `/v1/x402/access/grant` | POST | Grant access + record fulfillment |
| `/v1/x402/explain/{id}` | GET | Full lifecycle trace |
| `/v1/approvals` | GET | Approval queue |
| `/v1/approvals/{id}/decide` | POST | Operator approve/reject/escalate |
| `/v1/approvals/{id}/revoke` | POST | Revoke prior approval |
| `/v1/approvals/{id}/evidence` | GET | Evidence bundle |
| `/v1/approvals/{id}/replay` | POST | Deterministic replay (Lab) |
| `/v1/entitlements` | GET | List active entitlements |
| `/v1/entitlements/{id}/revoke` | POST | Revoke entitlement |
| `/v1/diagnostics/commerce/health` | GET | Subsystem health |
| `/v1/diagnostics/commerce/stuck-approvals` | GET | Past-SLA approvals |

## 10. Kyber integration

- **Review page:** "Commerce Approvals" tab exposing `ApprovalQueue` component with approve/reject/escalate/revoke actions (gated on `canApprove`).
- **All pages:** `LifecycleTraceView` component for evidence inspection.
- **Adapters:** `lib/api/commerce.ts` (`commerceApi`, `approvalsApi`, `entitlementsApi`, `commerceDiagnosticsApi`).
- **Schemas:** `lib/schemas/commerce.ts` (all responses Zod-validated).
- **Fixtures:** `fixtures/commerce.ts` (deterministic for mock/Lab mode).
- **Hooks:** `features/approvals`, `features/commerce`, `features/entitlements`.

All Kyber actions hit real backend APIs and emit real events. In mock mode (`VITE_KYBER_ENV=local-mocked`) fixtures are used deterministically.

## 11. Operator runbook (stuck approval)

1. Open Kyber Review → Commerce Approvals tab.
2. Filter by status=`pending` or `assigned`.
3. Click approval row → see evidence bundle, policy decision, requester history.
4. Either approve with reason, reject with reason, or escalate.
5. For past-SLA items, `GET /v1/diagnostics/commerce/stuck-approvals` marks them `expired`.

## 12. Support debug path

| Question | Answer via |
|---|---|
| Why was access denied? | `GET /v1/x402/explain/{challenge_id}` → `policy_decision.denial_reason` |
| Why did approval fire? | `policy_decision.active_rules` includes `mandatory_approval_all_spend_classes` |
| Who approved/rejected? | `approval.decided_by` + audit log |
| Which facilitator verified? | `authorization.facilitator_id` |
| What graph state was written? | `trace.graph_writes` |
| Was this a duplicate payment? | Idempotency store returns cached result by `payment_identifier` |

## 13. Testing

- Backend: `tests/commerce/test_lifecycle.py` (11 integration tests) + `tests/commerce/test_units.py` (10 unit tests) — **21 passing**.
- Kyber: `src/test/unit/commerce-schemas.test.ts` (16 schema tests) + `src/test/component/commerce.test.tsx` (11 component tests) — **27 passing**.
- Full suites: backend (21), Kyber (79 total including 52 prior).

Run:
```bash
# Backend
cd "Backend Architecture/aether-backend" && python -m pytest tests/commerce/ -v --asyncio-mode=auto

# Kyber
cd apps/kyber && npx vitest run
```

## 14. What's deferred (out of Day-1)

- External third-party paid resource providers (architecture-ready, not shipped).
- On-chain tx verification against real Base/Solana RPCs (stubbed in verification engine; verification succeeds on well-formed tx_hash in local mode).
- Postgres-backed persistent repositories (in-memory store at Day-1; `repositories/repos.py` pattern is extension point).
- Marketplace / discovery features.
