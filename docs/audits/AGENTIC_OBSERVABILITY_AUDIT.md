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
last_synced_commit: b8b0072
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
| `Agent Layer/workers/discovery/` | Web crawling, chain monitoring, social listening. All observational. |
| `Agent Layer/workers/enrichment/` | Entity resolution, profile enrichment, semantic tagging. Data transformation only. |
| `packages/shared/trading-profile.ts` | Aggregated trading/financial profile data model. Observational. |
| `docs/source-of-truth/REWARD_NO_CUSTODY_MODEL.md` | Explicit non-execution policy. Correctly defines AETHER as non-custodial. |

## Bucket 2 — Ambiguous: could imply AETHER executes

| File | Issue | Resolution |
|---|---|---|
| `docs/AGENTIC_COMMERCE_BUILD_SPEC.md` | Phrases like "AETHER settles" or "control plane settles payment" imply execution | Reframe as "externally observed settlement" and "AETHER records settlement" |
| `docs/source-of-truth/EVENT_REGISTRY.md` | Events `x402_payment_submitted`, `x402_payment_settled` could imply AETHER submits/settles | **Partially resolved:** canonical x402 observation events now added in `packages/shared/contracts/event-registry.json` (`x402_payment_required_observed`, `x402_payment_initiated_observed`, `x402_payment_verified_observed`, `x402_payment_failed_observed`, `x402_resource_unlocked_observed`, `x402_settlement_confirmed_observed`). Legacy ambiguous names remain in non-generated section and should be deprecated in a follow-up PR. |
| `packages/shared/events.ts` | Same events in TypeScript union | **Partially resolved:** observation-style events added to the generated section. `x402_signature_observed`, `x402_settlement_observed` present. Legacy `x402_payment_submitted`, `x402_payment_settled` remain in non-generated section. |
| `services/x402/settlement.py` | `SettlementState.SETTLED` transition could be misread as fund settlement | Comment clarification that this is state tracking only |

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
