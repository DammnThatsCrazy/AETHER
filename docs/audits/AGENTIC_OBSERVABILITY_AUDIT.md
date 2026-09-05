---
title: Agentic Observability Audit
slug: audits/agentic-observability-audit
section: architecture
visibility: I
audience: [dev-senior, architect, ai]
status: experimental
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/x402/
  - Backend Architecture/aether-backend/services/agent/
  - packages/shared/events.ts
  - packages/shared/agentic-observability.ts
last_synced_commit: "c587eb8b"
---

# Agentic Observability Audit

> AETHER may observe economic, protocol, trading, communication, and agentic activity.
> AETHER must not execute, originate, sign, custody, settle, or facilitate those actions
> unless a future explicit product scope, legal review, compliance review, and feature flag
> enable it. For now, all `execution_by_aether` fields must be `false`.

## Bucket 1 — Correctly observation-only

| File | Notes |
|---|---|
| `services/x402/control_plane.py` | Orchestrates workflow state (issues challenges, routes to approval, records settlement). Does NOT execute transfers. Naming "control plane" is appropriate: it controls AETHER's internal state machine, not external execution. |
| `services/x402/settlement.py` | FSM state tracker only. Records `pending→verifying→settled` transitions. No funds moved. |
| `services/x402/verification.py` | RPC *reads* only (`eth_getTransactionReceipt`, `getTransaction`). Does NOT submit transactions. |
| `services/x402/approvals.py` | Approval workflow FSM. Routes and records human operator decisions. No autonomous execution. |
| `services/x402/entitlements.py` | Mints time-bound access tokens after external settlement confirmed. Governance artifact only. |
| `services/x402/policies.py` | Policy engine: evaluates allow/deny/require_approval. Emits decisions; does not enforce them autonomously. |
| `services/x402/interceptor.py` | Header parsing only. Observational. |
| `services/x402/economic_graph.py` | Graph mutations for lifecycle stages. Observational. |
| `services/agent/economic.py` | Agent economic views: budget aggregation. Read-only. |
| `services/agent/lifecycle_mapper.py` | Routes agent events to repositories and graph. Observational. |
| `services/agent/worker_bridge.py` (2026-07-10) | Publishes internal objective-step envelopes to AETHER's own Agent Layer Celery broker by task name. Internal work dispatch only — no external execution, no payments, no trades. Hosted modes fail closed when the broker is unreachable. |
| `services/agent/worker_routes.py` (2026-07-10) | Worker status callbacks (`agent:run_update` service credential). Records run state; executes nothing. |
| `services/agent/mutation_commit.py` (2026-07-10) | Commits staged graph mutations ONLY after explicit human approval of a review batch; GraphWriteValidator + CIS quarantine gate every write. Mutates AETHER's internal graph, never external systems. |
| `services/agent/briefings.py`, `services/agent/ops_alerts.py` (2026-07-10) | Durable operator briefings and compressed ops alerts generated from internal runtime state. Read/aggregate only. |
| `Agent Layer/workers/discovery/` | Web crawling, chain monitoring, social listening. All observational. |
| `Agent Layer/workers/enrichment/` | Entity resolution, profile enrichment, semantic tagging. Data transformation only. |
| `packages/shared/trading-profile.ts` | Aggregated trading/financial profile data model. Observational. |
| `docs/source-of-truth/REWARD_NO_CUSTODY_MODEL.md` | Explicit non-execution policy. Correctly defines AETHER as non-custodial. |

## Bucket 2 — Ambiguous: could imply AETHER executes

| File | Issue | Resolution |
|---|---|---|
| `docs/AGENTIC_COMMERCE_BUILD_SPEC.md` | Phrases like "AETHER settles" or "control plane settles payment" imply execution | Reframe as "externally observed settlement" and "AETHER records settlement" |
| `docs/source-of-truth/EVENT_REGISTRY.md` | Events `x402_payment_submitted`, `x402_payment_settled` could imply AETHER submits/settles | **Partially resolved:** canonical x402 observation events now added in `packages/shared/contracts/event-registry.json` (`x402_payment_required_observed`, `x402_payment_initiated_observed`, `x402_payment_verified_observed`, `x402_payment_failed_observed`, `x402_resource_unlocked_observed`, `x402_settlement_confirmed_observed`). Legacy ambiguous names remain in non-generated section and should be deprecated in a follow-up PR. |
| `packages/shared/events.ts` | Same events in TypeScript union | **Partially resolved:** observation-style events added to the generated section. `x402_signature_observed`, `x402_settlement_observed` present. Legacy `x402_payment_submitted`, `x402_payment_settled` remain in non-generated section. **2026-07-08 update:** 5 sensitive agent trading events (`agent_trade_order_observed`, `agent_trade_fill_observed`, `agent_position_observed`, `agent_portfolio_snapshot_observed`, `agent_performance_snapshot_observed`) now require `financial_activity` consent purpose in `EVENT_CONSENT_PURPOSE`. Their `EVENT_FAMILY` remains `'agent'`. This gates sensitive financial data behind explicit user consent. **2026-07-08 update (derivatives):** 11 derivatives SDK lifecycle events (`trading_account_connected`, `trading_account_disconnected`, `trading_account_authorized`, `trading_account_deauthorized`, `trading_agent_enabled`, `trading_agent_disabled`, `trade_intent_created`, `trade_approval_requested`, `trade_approval_resolved`, `risk_policy_updated`, `human_trade_override_recorded`) added to the generated section with `financial_activity` consent and `financial_7y` retention. All are observation-only; `execution_by_aether` remains false. Web, Android, and iOS SDK event dispatch tables updated. **2026-07-09 update (AI economics):** `ai_invocation_observed` added to the generated section (family `agent`, consent purpose `agent`, retention `standard_90d`) — an observation-only AI execution telemetry event carrying identity/usage/cost/latency/quality metadata and never raw prompt or completion content; `execution_by_aether` semantics are unaffected. Web, Android, and iOS consent maps updated in the same commit. **2026-07-09 update (deployment telemetry):** `AgenticObservationRecord` gains an optional additive `deployment_id`; `graph_mutations.py` gains a flag-gated aggregate deployment projection reusing `EXTERNAL_AGENTIC_ACCOUNT` vertex + `AGENT_LINKED_TO_EXTERNAL_ACCOUNT` edge with `kind="agent_deployment"` (one vertex/edge per deployment, never per event). Observation-only; `execution_by_aether` unchanged. |
| `services/x402/settlement.py` | `SettlementState.SETTLED` transition could be misread as fund settlement | Resolved beyond comment level: outside local, `_advance` parks settlements in `PENDING` — `SETTLED` is asserted only by reconciliation or explicit operator action, so the recorded state can no longer overstate observed settlement |

## Bucket 3 — Incorrect: AETHER appears to originate/execute

No files in this bucket. The existing x402 and agent infrastructure is correctly observation-only.

## Bucket 4 — Missing: needed for observability

| Gap | What needs building |
|---|---|
| Robinhood-style external agentic account observability | `services/external_account_observability/` — observe account linkage, budgets, permissions, disconnect events |
| Robinhood-style trading observation | `services/external_account_observability/brokerage_models.py` — observe trade intents, orders, fills, rejections, positions, portfolios, performance |
| AgentMail-style inbox observation | `services/agent_comm_observability/inbox_models.py` — observe inbox creation, email addresses, threads |
| AgentMail-style message/attachment observation | `services/agent_comm_observability/message_models.py` — observe messages, attachments, extractions |
| AgentMail-style entity extraction observation | `services/agent_comm_observability/extraction_models.py` — OTP, invoice, receipt, calendar intent, support routing |
| x402 protocol observation (from observer perspective) | `services/protocol_observability/` — observe challenges, requirements, signatures, verifications, settlements, resource access as seen by an external observer |
| MCP connection observation | `services/agentic_observability/` — observe MCP connections, tool invocations, agent activity |
| Agent risk signals | `services/agentic_observability/risk_signals.py` — compute and record risk signals from observed activity |
| Canonical observation envelope | `packages/shared/agentic-observability.ts` — `AgenticObservationEvent` TypeScript type |

## Bucket 5 — Kyber visibility gap

| Gap |
|---|
| No Kyber module for agentic activity (MCP connections, tool invocations, external accounts) |
| No Kyber module for x402 lifecycle from observer perspective (challenges, signatures, resource access) |
| No Kyber module for agent inbox/message/attachment activity |
| No Kyber module for external brokerage account observations |
| No Kyber module for agent risk signals and drift detection |
| Missing: `GET /v1/admin/kyber/agentic-observability/*` routes |

## Bucket 6 — Profile360/graph gap

| Gap |
|---|
| `docs/PROFILE-360-AGGREGATION.md` has no Agent entity section |
| No Profile360 tabs for: MCP connections, external accounts, inbox activity, x402 interactions, trade intent observations, risk signals |
| Graph schema (`shared/graph/graph.py`) missing 26 observation vertex types |
| Graph schema missing 38 observation edge types |

## Bucket 7 — Source-of-truth drift

| File | Drift |
|---|---|
| `docs/source-of-truth/EVENT_REGISTRY.md` | Missing 47 new observability events across 4 families |
| `docs/source-of-truth/ENTITY_MODEL.md` | Missing 44 new entity types across 4 groups |
| `docs/source-of-truth/SDK_SCOPE.md` | No explicit no-execution rule |
| `docs/BACKEND-API.md` | Missing 30+ observability routes, 7 Kyber admin routes |
| `docs/ECONOMIC-OBSERVABILITY.md` | Framing does not distinguish "externally observed" from "AETHER-originated" |
| `docs/PROFILE-360-AGGREGATION.md` | No Agent entity Profile360 sections |

## PR 1 current-state audit and gap matrix (2026-07-03)

| Capability | Current implementation | Current source files | Status | Required action | Target PR | Acceptance test |
|---|---|---|---|---|---|---|
| Router activation | Agentic, protocol, communication, and external-account routers are mounted from `main.py` behind `AGENTIC_*` feature flags. | `Backend Architecture/aether-backend/main.py`, `Backend Architecture/aether-backend/config/settings.py` | partial | Add capabilities endpoint exposure and deeper per-route disabled-state tests. | PR 1 follow-up | Router mounting and feature-flag tests. |
| Tenant authority | Routes now reject request-body tenant mismatches and use authenticated request tenant for persisted rows. | `services/agentic_observability/foundation.py`, observability route modules | partial | Extend the same helper through x402 routes and legacy repositories. | PR 1/2 | Missing/mismatched/cross-tenant tests. |
| Graph tenant naming | Graph-boundary helper adds canonical `tenantId` while preserving legacy `tenant_id` for current graph readers. | `services/agentic_observability/foundation.py` | partial | Complete graph-contract migration to one reader-visible canonical property. | PR 5 | Graph contract parity and cross-tenant graph tests. |
| Mutation counts | Agentic routes report built and persisted counts; compatibility `graph_mutations_queued` now equals persisted count. | `services/agentic_observability/routes.py`, `schemas.py` | partial | Move all graph writes to durable outbox and update protocol/comm/external responses with the richer schema. | PR 2 | Truthful mutation count tests. |
| Silent graph failures | Shared helper logs structured graph projection failures and returns `failed` status without rejecting accepted observations. | `services/agentic_observability/foundation.py` | partial | Store failures durably in outbox/dead-letter tables. | PR 2 | Worker retry/dead-letter tests. |
| Event name validation | Generic agent event endpoint rejects names not present in canonical generated registry. | `services/agentic_observability/foundation.py`, `services/ingestion/generated_registry.py` | partial | Add generated TS/Python/OpenAPI parity checks for all observability event families. | PR 1/3 | Unknown-event and parity tests. |
| No-execution invariant | Existing `Literal[False]` checks are backed by a shared route validator with clearer error text. | `services/agentic_observability/foundation.py` | partial | Extend import-boundary/static dependency checks. | PR 8 | Negative route and import-boundary tests. |
| Kyber placeholders | Agentic, inbox, and external-account Kyber endpoints return repository-backed counts/lists instead of placeholder messages or hardcoded empty arrays. | observability route modules | partial | Build full Kyber lineage, replay, reconciliation, and health surfaces. | PR 7 | Non-placeholder route tests. |
| Canonical ingestion | Observability-specific JSONB repositories still accept production writes. | `repositories/agentic_observability_repos.py` | scaffold | Route through Bronze → Silver → canonical_activity → outbox. | PR 2 | Pipeline integration test. |
| Product surfaces | Profile 360, Journey v2, Cluster360, campaign, Noesis, and frontend propagation remain incomplete. | profile/journey/cluster/campaign/noesis/frontend services | missing | Implement propagation and evidence labeling. | PR 6/7 | End-to-end product scenario. |

