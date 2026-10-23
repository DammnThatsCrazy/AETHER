---
title: Agentic Observability Audit
slug: audits/agentic-observability-audit
section: architecture
visibility: I
audience: [dev-senior, architect]
status: experimental
since_version: 0.1.0
source_files: [services/api/value/x402/, services/api/actions/agent/, services/api/actions/agentic_observability/, services/api/actions/agent_marketplace/, services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py, services/api/alembic/versions/20261011_agent_delegated_to_namespace.py, services/api/alembic/versions/20261022_execution_approval_decisions.py, services/api/alembic/versions/20261022_risk_poisoning_evidence.py, services/api/value/commerce/order_payment_reconciliation.py, services/api/value/economic/economic360_contracts.py, services/api/value/economic/operation_linkage.py, services/api/value/economic/economic360_provider.py, services/api/journeys/communication360/provider.py, services/api/intelligence/fraud_networks/risk360_projection.py, services/api/connectors/integrations/providers/payment_rails/service.py, services/api/connectors/integrations/providers/payment_rails/stripe_onramp.py, services/api/identity/profile/agent.py, services/api/intelligence/risk360/, services/api/ingestion/ingestion/lifecycle_worker.py, services/api/ingestion/silver/projectors/agent_execution_projector.py, services/api/ingestion/silver/projectors/silver_graph_projector.py, services/api/shared/store.py, services/api/workers/runtime/specs.py, packages/sdk/server/src/agent-telemetry.ts, packages/shared/events.ts, packages/shared/contracts/event-registry.json, packages/shared/contracts/intelligence-projection-registry.json, packages/shared/agentic-observability.ts]
source_hashes:
  "packages/sdk/server/src/agent-telemetry.ts": "sha256:95db783d969918011e29a3aeb96e837a559f547aec4c2efcee1679188b360f0b"
  "packages/shared/agentic-observability.ts": "sha256:b7619ae635280e2673b8632192005e24d7f2fdfbd4bbcb8f773b2efb5be6850e"
  "packages/shared/contracts/event-registry.json": "sha256:3d839b394ff0ee3a40679f92a9c38f2e321ab7785663d1a8ef047279d8b757f2"
  "packages/shared/contracts/intelligence-projection-registry.json": "sha256:caf21a7595ec1e7d262e2e365be653dd49c1d661fcddf4e2b028b6fe2ccbf70b"
  "packages/shared/events.ts": "sha256:864fd17d5e7e842b8cc96970b4f79f43879b7564281c3f9b1cdd3c637e92ebdd"
  "services/api/actions/agent/": "sha256:540f85292689337edc329c9b72b7c4f99487226a5e31aab6526c878e7ea36eeb"
  "services/api/actions/agent_marketplace/": "sha256:e5c25ced055d8f59d2d126a15d0e461e760c5dbaa28f19d4d9ed1567bb072568"
  "services/api/actions/agentic_observability/": "sha256:0153a7ccb49d8950fd38207044f932213db7ce191df455e6951b6483d5bf8e00"
  "services/api/alembic/versions/20261011_agent_delegated_to_namespace.py": "sha256:446edfe924829cc75d627af169fb12c975f11f2ab13cf17b735ff14a8fed1c10"
  "services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py": "sha256:ab8553556c2c9d6e0e46fe55899132946dcfef9c432b8aed72d394da8e5a3269"
  "services/api/alembic/versions/20261022_execution_approval_decisions.py": "sha256:6f3c2ff0235a78fd144f0b26bb76a36556c23a1bc5a8285e58588608e9fa7fb6"
  "services/api/alembic/versions/20261022_risk_poisoning_evidence.py": "sha256:d158801954e2c76f088f9a367cabc4e507f1d4b2e456e989b6e95c04a9db6237"
  "services/api/connectors/integrations/providers/payment_rails/service.py": "sha256:ac5c38e755dd2720a76fcca31bf7877d7e2e5d2e5ea19c3a37bc5344e495ecc4"
  "services/api/connectors/integrations/providers/payment_rails/stripe_onramp.py": "sha256:b6617b0dd888b02ede69696d3d4e46906120c5f0fca4bb4f5393145218d6200c"
  "services/api/identity/profile/agent.py": "sha256:f7aa0168d674cfe5241d169f6516478ef24c882e848dc097af98706f0aee576c"
  "services/api/ingestion/ingestion/lifecycle_worker.py": "sha256:7b6d7d2323a5646c0f7a7093e7ae256f943c70af07557080ef5949d09d07e5d8"
  "services/api/ingestion/silver/projectors/agent_execution_projector.py": "sha256:1db7a6ff778ed3ca22ebae87717636c37f6b821b1e37ddc4d85161a5bb3bb4bf"
  "services/api/ingestion/silver/projectors/silver_graph_projector.py": "sha256:3c9fde55d39ff7aa80350bc67c165b6420775c4175faaad8c15d750ab2a61c93"
  "services/api/shared/store.py": "sha256:f35311e40b7ab2c4a8ea90b0e26dd3bd2e4aefc855a0bd7b5efae1a9a6af9f94"
  "services/api/value/commerce/order_payment_reconciliation.py": "sha256:1bfb4e715fa255bd9c12956c71f4c2e48c49c65d84c7f6d2c0ca1e1bf9960ebe"
  "services/api/intelligence/fraud_networks/risk360_projection.py": "sha256:4ad7ac91c78b7f66f66e9abd986a723453a721e4868584fa1e349723d6cd306c"
  "services/api/intelligence/risk360/": "sha256:595590d43ef5d1be824ad90e31c30018c023a431667a8165aaa4b008959220dc"
  "services/api/journeys/communication360/provider.py": "sha256:103203807abc92ff1c262e358335e9697873c24706ab42d81a512af3c0cf1efc"
  "services/api/value/economic/economic360_contracts.py": "sha256:8a3053f8e23ed369850714d8e77525135dd8f4b2085ead3c89273f741923f4f5"
  "services/api/value/economic/economic360_provider.py": "sha256:feefe5903f7faa2fee321e31f11c2e89d344353ad9b0f585325ebd0d349cc57f"
  "services/api/value/economic/operation_linkage.py": "sha256:0f663fa20e86fdeaf99d9f27afebdb603423887458b5bbdd0c3450baecd5b9d4"
  "services/api/value/x402/": "sha256:49f3660ba1468f6481b067fcd46ad230199aee60d7e7316ba57b7c69c368c4a9"
  "services/api/workers/runtime/specs.py": "sha256:b86659249b2f805b3ba81631c57e71ca57be089de07278fedccbe25b576df64b"
---

# Agentic Observability Audit

> AETHER may observe economic, protocol, trading, communication, and agentic activity.
> AETHER must not execute, originate, sign, custody, settle, or facilitate those actions
> unless a future explicit product scope, legal review, compliance review, and feature flag
> enable it. For now, all `execution_by_aether` fields must be `false`.

## Current-state addendum (2026-10-15)

PR #771 closes the external-agent execution-lineage and graph-recovery gaps
within its defined scope. The SDK contract, backend validation, Silver
projector, and graph projector now carry source-asserted deployment/run,
task/action, trigger, tool, policy, delegation, and outcome references. Agent
360 presents run evidence with source and coverage labels; it does not claim
hidden reasoning or independently verify source assertions. Kyber recovery
pages tenant deployment/Silver sources or platform catalog observations
separately from outbox status, checks missing work by deterministic outbox ID,
and writes only through the graph mutation gateway. Scan reports explicitly
identify `best_effort_non_snapshot` consistency and do not certify graph state.

The default-off xAI catalog observer adds minimal public listing metadata as a
separate `platform`-scoped source. It does not fetch bot configuration or join
public listing slugs to canonical Agents. Tenant admins can explicitly bind a
deployment source namespace/reference to a same-tenant canonical Agent; the
binding is separate from automatic identity merge and fails closed when absent
or ambiguous. A source delegation reference resolves to a same-tenant
canonical grant, and when actor/target bindings resolve, backend-owned grant
status, endpoints, effective/revocation window and supported scope are
evaluated at source event time. The result remains separate from execution
occurrence: action/resource/time are source claims, and without a server-owned
receipt occurrence is unverified. Deployment, payment, settlement, and
delegation identifiers plus `delegatedToNamespace` remain source references.
A new bounded read-only graph state check
compares supported tenant links to source evidence and reports partial,
non-snapshot coverage; it neither repairs nor certifies the whole graph.
Associated x.com posts and x.ai news, private bot contents, server-owned
external execution receipts, and comprehensive snapshot-consistent graph
certification remain follow-on work.

For economic outcomes, optional task/outcome payment-intent and settlement-event
references resolve only against exact same-tenant records with server-owned
x402 provenance and a matching deployment registry agent reference. Public SDK
x402 observations remain source claims and cannot replace server-authoritative
payment state. Linked amount, currency and lifecycle state come from the
authoritative record; the correlation does not establish causality, verify the
source action, or prove settlement finality.
The historical gap matrices below retain their original audit date and should
not be read as a current inventory without this addendum and the linked
source-of-truth documents.

## 360 provider addendum (2026-10-23)

The backend mounts `POST /v1/experience360/frames` and
`GET /v1/experience360/catalog` for the exact 18-surface backend contract in
`docs/reference/source-of-truth/AETHER_360_BACKEND_SINGLE_SOURCE_OF_TRUTH.md`.
The supplemental architectural blueprint is supporting context; it does not
expand that backend catalog. All 18 catalog entries now carry source-aligned
contract metadata and required-slot IDs. This source-alignment marker does not
mean that a provider fills every required slot or meets the complete surface
contract. The registry contains 24 technical projections; 9 are marked
`implemented` and 15 `in_flight`, and all 24 register at startup.

Agent360 has tenant-scoped identity, delegation and action-scoped authority
evidence, observed capability reach, and execution/telemetry evidence. Its
bounded capability read counts only exact active invoke grants for the resolved
canonical Agent and tenant; missing, malformed, foreign, or truncated rows keep
coverage partial or unknown. The capability profile reports observed reach
and invoke-grant coverage; it does not decide whether a new action/resource
request is authorized. Its
`policy_boundary` section now carries historical, action-scoped server
decisions when observed while keeping effective policy unknown; it does not
expose a standing policy snapshot. Its `risk_summary` composes canonical
Risk360 evidence with exact slot attribution and does not compute a local risk
score. Its `spawned_agents` slot reads only outgoing `SPAWNED_SUBAGENT` graph
ledger evidence through Relationship360. No observed edge is unknown rather
than empty, and any observed edge remains degraded because the ledger has no
completeness watermark. Account360's `communications` slot can now consume
Communication360 evidence only for an exact tenant-owned entity subject with
matching endpoint identity bindings; account/workspace aliases, membership
fanout, source freshness, and historical consent coverage remain unresolved.
Value360's `confidence` slot now carries Economic360 model confidence only when
the score and model type/version are present. It remains model-reported and
uncalibrated for realized value or ROI, with model-governance calibration
evidence unbound.

Execution360 now derives server-recorded lifecycle elapsed time from valid,
timezone-aware start and end timestamps and carries the lifecycle evidence
into `latency_cost`. This is not provider/tool latency or cost. It still lacks
a general server-owned external effect receipt, canonical plan-step evidence,
complete input/output capture, and detailed failures. Its approval-chain join
covers current x402 decisions only; other approval authorities and historical
run links remain unknown.
Execution360 actor attribution now records the authenticated initiating user
separately from the acting agent. A principal resolves to a canonical Human
only through an exact tenant-scoped active `USER_ID` alias and active surviving
identity subject, with both identity evidence references. Missing, conflicting,
or unavailable identity reads remain unknown, and the link does not establish
action authorization or delegation authority.
Its `risk_events` slot now joins canonical RiskSignals only to exact execution
IDs admitted by tenant server lifecycle records. Signal evidence is recorded
risk context, not proof that the execution caused the signal or a complete risk
assessment; producer coverage and freshness thresholds remain unknown. The
agentic risk-signal compute/store producer described in Bucket 4 is still
missing. Agentic fraud-network detections are separately persisted to Risk360
only after a unique tenant-owned Agent binding is resolved and its valid,
timezone-aware binding timestamp is no later than the detector observation;
missing, conflicting, malformed, or future timestamps cause omission. This
prevents retrospective attribution but does not establish execution causality
or contagion. Its `tool_calls` slot also joins `CALLED_TOOL`
lifecycle edges only to exact tenant execution records with a canonical agent
binding, validates the tenant-owned Tool vertex, and requires timestamp and
edge-idempotency evidence. An observed edge proves only that AETHER recorded a
tool-call lifecycle fact; graph completeness, tool outcome, action authority,
and external effect remain unknown.

The frame runtime joins available provider output to communication, risk,
economic, and outcome projections. Tenant policy runs before provider reads.
Delegation parties resolve only through exact tenant-scoped canonical entity
rows; a missing or duplicate party binding leaves the authority slot unknown
or conflicted. Event-time delegation evidence remains separate from verified
external execution. All 24 technical providers register at app startup (9
`implemented`, 15 `in_flight`), but registration does not prove required-slot
conformance. Unknown, missing, and degraded states are preserved. Complete
episode-to-payment references, complete source evidence, policy and freshness
behavior, and surface-level golden coverage remain follow-on work across the
18 surfaces; none is claimed by the mounted route or catalog.

The 2026-10-23 provider wave adds three bounded joins without closing their
product surfaces. Episode360 `timeline` resolves only observation IDs persisted
on the tenant's episode records to exact, active semantic Silver observation
rows and preserves evidence; broader activity/session inventory, source
namespace typing, policy disposition, and freshness remain unknown.
Campaign360 `signal_sources` resolves only exact canonical event IDs referenced
by campaign touchpoints. It returns limited event metadata with touchpoint and
event evidence; it does not infer campaign membership from labels or event
properties, and the observation/source-fact dimensions, complete event coverage,
and freshness remain unknown. Memory360 `policy_state` renders exact
tenant-and-subject historical allow decisions with timestamped consent-policy
evidence; this records the decision made at memory write time and does not
evaluate current consent or policy. These joins are partial slot capabilities,
not surface completion or authority to execute actions.

A follow-up provider slice adds partial Signals360 `classification` evidence
for one exact tenant SDK event after gateway acceptance and canonical event
registry validation. It does not join tenant source attribution, semantic
classification, policy, or freshness. Workflow360 `agent_steps` now reads only
AgentExecution rows with the exact tenant and `workflow_run_id`, but the
canonical AgentExecution writer does not populate that field, so production
step records are not yet connected; workflow definition and complete step
coverage remain unknown. Episode360 `agent_handoffs` remains unknown because
episode records and observations do not reference a canonical execution or
handoff ID. Event labels and agent metadata do not establish that relationship.

## Bucket 1 — Correctly observation-only

| File | Notes |
|---|---|
| `services/api/value/x402/control_plane.py` | Orchestrates workflow state (issues challenges, routes to approval, records settlement). Does NOT execute transfers. Naming "control plane" is appropriate: it controls AETHER's internal state machine, not external execution. |
| `services/api/value/x402/settlement.py` | FSM state tracker only. Records `pending→verifying→settled` transitions. No funds moved. |
| `services/api/value/x402/verification.py` | RPC *reads* only (`eth_getTransactionReceipt`, `getTransaction`). Does NOT submit transactions. |
| `services/api/value/x402/lifecycle_mapper.py` | Persists source lifecycle references; on submission it stores an authorization ID only when the tenant-scoped authorization record names the same challenge/intent. It does not authorize or execute a transfer. |
| `services/api/value/x402/approvals.py` | Approval workflow FSM. Routes and records human operator decisions. No autonomous execution. |
| `services/api/value/x402/entitlements.py` | Mints time-bound access tokens after external settlement confirmed. Governance artifact only. |
| `services/api/value/x402/policies.py` | Policy engine: evaluates allow/deny/require_approval. Emits decisions; does not enforce them autonomously. |
| `services/api/value/x402/interceptor.py` | Header parsing only. Observational. |
| `services/api/value/x402/economic_graph.py` | Graph mutations for lifecycle stages. Observational. |
| `services/api/actions/agent/economic.py`, `services/api/identity/profile/agent.py` | Agent economic views and Agent 360 expose evidence-only links from tenant-scoped payment intents to exact-match authorization, execution and settlement-event records. Authorization also requires an exact tenant/challenge/agent match to its authoritative PaymentRequirement. Source lifecycle status remains authoritative. |
| `services/api/value/economic/operation_linkage.py`, `services/api/value/commerce/order_payment_reconciliation.py` | Commerce and agent lifecycle links carry source-owned references only. Exact Stripe order/payment evidence can carry a distinct succeeded refund with an explicit `reverses` relation. The commerce ledger can also preserve an authoritative settled outcome and link it with `settled_by` only to explicit provider/payment IDs, including knowledge-time visibility; no current processor adapter emits this evidence. Neither link carries amounts, infers settlement from payment completion, executes a transfer, or changes the original payment's source status. |
| `services/api/ingestion/ingestion/lifecycle_worker.py` | Only closed-registry server-authoritative x402 topics project agent PaymentIntent/SettlementEvent records to existing graph vertices and registered edges; SDK terminal claims remain excluded. |
| `services/api/actions/agent/lifecycle_mapper.py` | Routes agent events to repositories and graph. Observational. |
| `services/api/actions/agent/worker_bridge.py` (2026-07-10) | Publishes internal objective-step envelopes to AETHER's own Agent Layer Celery broker by task name. Internal work dispatch only — no external execution, no payments, no trades. Hosted modes fail closed when the broker is unreachable. |
| `services/api/actions/agent/worker_routes.py` (2026-07-10) | Worker status callbacks (`agent:run_update` service credential). Records run state; executes nothing. |
| `services/api/actions/agent/mutation_commit.py` (2026-07-10) | Commits staged graph mutations ONLY after explicit human approval of a review batch; GraphWriteValidator + CIS quarantine gate every write. Mutates AETHER's internal graph, never external systems. |
| `services/api/actions/agent/briefings.py`, `services/api/actions/agent/ops_alerts.py` (2026-07-10) | Durable operator briefings and compressed ops alerts generated from internal runtime state. Read/aggregate only. |
| `services/agents/workers/discovery/` | Web crawling, chain monitoring, social listening. All observational. |
| `services/agents/workers/enrichment/` | Entity resolution, profile enrichment, semantic tagging. Data transformation only. |
| `packages/shared/trading-profile.ts` | Aggregated trading/financial profile data model. Observational. |
| `docs/reference/source-of-truth/REWARD_NO_CUSTODY_MODEL.md` | Explicit non-execution policy. Correctly defines AETHER as non-custodial. |

## Bucket 2 — Ambiguous: could imply AETHER executes

| File | Issue | Resolution |
|---|---|---|
| `docs/architecture/AGENTIC_COMMERCE_BUILD_SPEC.md` | Phrases like "AETHER settles" or "control plane settles payment" imply execution | Reframe as "externally observed settlement" and "AETHER records settlement" |
| `docs/reference/source-of-truth/EVENT_REGISTRY.md` | Events `x402_payment_submitted`, `x402_payment_settled` could imply AETHER submits/settles | **Partially resolved:** canonical x402 observation events now added in `packages/shared/contracts/event-registry.json` (`x402_payment_required_observed`, `x402_payment_initiated_observed`, `x402_payment_verified_observed`, `x402_payment_failed_observed`, `x402_resource_unlocked_observed`, `x402_settlement_confirmed_observed`). Legacy ambiguous names remain in non-generated section and should be deprecated in a follow-up PR. |
| `packages/shared/events.ts` | Same events in TypeScript union | **Partially resolved:** observation-style events added to the generated section. `x402_signature_observed`, `x402_settlement_observed` present. Legacy `x402_payment_submitted`, `x402_payment_settled` remain in non-generated section. **2026-07-08 update:** 5 sensitive agent trading events (`agent_trade_order_observed`, `agent_trade_fill_observed`, `agent_position_observed`, `agent_portfolio_snapshot_observed`, `agent_performance_snapshot_observed`) now require `financial_activity` consent purpose in `EVENT_CONSENT_PURPOSE`. Their `EVENT_FAMILY` remains `'agent'`. This gates sensitive financial data behind explicit user consent. **2026-07-08 update (derivatives):** 11 derivatives SDK lifecycle events (`trading_account_connected`, `trading_account_disconnected`, `trading_account_authorized`, `trading_account_deauthorized`, `trading_agent_enabled`, `trading_agent_disabled`, `trade_intent_created`, `trade_approval_requested`, `trade_approval_resolved`, `risk_policy_updated`, `human_trade_override_recorded`) added to the generated section with `financial_activity` consent and `financial_7y` retention. All are observation-only; `execution_by_aether` remains false. Web, Android, and iOS SDK event dispatch tables updated. **2026-07-09 update (AI economics):** `ai_invocation_observed` added to the generated section (family `agent`, consent purpose `agent`, retention `standard_90d`) — an observation-only AI execution telemetry event carrying identity/usage/cost/latency/quality metadata and never raw prompt or completion content; `execution_by_aether` semantics are unaffected. Web, Android, and iOS consent maps updated in the same commit. **2026-07-09 update (deployment telemetry):** `AgenticObservationRecord` gains an optional additive `deployment_id`; `graph_mutations.py` gains a flag-gated aggregate deployment projection reusing `EXTERNAL_AGENTIC_ACCOUNT` vertex + `AGENT_LINKED_TO_EXTERNAL_ACCOUNT` edge with `kind="agent_deployment"` (one vertex/edge per deployment, never per event). Observation-only; `execution_by_aether` unchanged. |
| `services/api/value/x402/settlement.py` | `SettlementState.SETTLED` transition could be misread as fund settlement | Resolved beyond comment level: outside local, `_advance` parks settlements in `PENDING` — `SETTLED` is asserted only by reconciliation or explicit operator action, so the recorded state can no longer overstate observed settlement |

## Bucket 3 — Incorrect: AETHER appears to originate/execute

No files in this bucket. The existing x402 and agent infrastructure is correctly observation-only.

## Bucket 4 — Missing: needed for observability

| Gap | What needs building |
|---|---|
| Robinhood-style external agentic account observability | `services/api/connectors/external_account_observability/` — observe account linkage, budgets, permissions, disconnect events |
| Robinhood-style trading observation | `services/api/connectors/external_account_observability/brokerage_models.py` — observe trade intents, orders, fills, rejections, positions, portfolios, performance |
| AgentMail-style inbox observation | `services/api/actions/agent_comm_observability/inbox_models.py` — observe inbox creation, email addresses, threads |
| AgentMail-style message/attachment observation | `services/api/actions/agent_comm_observability/message_models.py` — observe messages, attachments, extractions |
| AgentMail-style entity extraction observation | `services/api/actions/agent_comm_observability/extraction_models.py` — OTP, invoice, receipt, calendar intent, support routing |
| x402 protocol observation (from observer perspective) | `services/api/graph/protocol_observability/` — observe challenges, requirements, signatures, verifications, settlements, resource access as seen by an external observer |
| MCP connection observation | `services/api/actions/agentic_observability/` — observe MCP connections, tool invocations, agent activity |
| Agent risk signals | `services/api/actions/agentic_observability/risk_signals.py` — compute and record risk signals from observed activity |
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

## 2026-10-23 — Canonical evidence and authority joins

The current backend now writes an exact reciprocal link between supported
agent activity/tool/risk compatibility rows and their canonical Bronze event.
Agent360 verifies tenant, agent, evidence table and row ID, Bronze event ID,
schema, type, and timestamp before returning the provenance. It does not infer
links by matching provider names or nearby timestamps. Provider identity and
trust remain unresolved without a Rights `source_id`; freshness remains
unassessed because no source SLA is configured. Historical compatibility rows
without an explicit canonical link therefore remain degraded.

Execution360 now joins AETHER-owned execution rows to typed x402 approval
decisions by exact tenant and execution ID. This captures the latest decision
pointer and retained decision history for supported x402-bound runs. Other
approval systems and older runs remain outside this join. Risk360 can read
typed, tenant-scoped poisoning evidence with lifecycle and restatement history,
but no production detector currently writes those records. These additions
close evidence-path pieces; they do not complete Agent360, Execution360,
Risk360, or the full 18-surface contract.

## Bucket 6 — Profile360/graph gap

| Gap |
|---|
| `docs/architecture/PROFILE-360-AGGREGATION.md` has no Agent entity section |
| No Profile360 tabs for: MCP connections, external accounts, inbox activity, x402 interactions, trade intent observations, risk signals |
| Graph schema (`shared/graph/graph.py`) missing 26 observation vertex types |
| Graph schema missing 38 observation edge types |

## Bucket 7 — Source-of-truth drift

| File | Drift |
|---|---|
| `docs/reference/source-of-truth/EVENT_REGISTRY.md` | Missing 47 new observability events across 4 families |
| `docs/reference/source-of-truth/ENTITY_MODEL.md` | Missing 44 new entity types across 4 groups |
| `docs/reference/source-of-truth/SDK_SCOPE.md` | No explicit no-execution rule |
| `docs/reference/BACKEND-API.md` | Missing 30+ observability routes, 7 Kyber admin routes |
| `docs/architecture/ECONOMIC-OBSERVABILITY.md` | Framing does not distinguish "externally observed" from "AETHER-originated" |
| `docs/architecture/PROFILE-360-AGGREGATION.md` | No Agent entity Profile360 sections |

## PR 1 current-state audit and gap matrix (2026-07-03)

| Capability | Current implementation | Current source files | Status | Required action | Target PR | Acceptance test |
|---|---|---|---|---|---|---|
| Router activation | Agentic, protocol, communication, and external-account routers are mounted from `main.py` behind `AGENTIC_*` feature flags. | `services/api/main.py`, `services/api/config/settings.py` | partial | Add capabilities endpoint exposure and deeper per-route disabled-state tests. | PR 1 follow-up | Router mounting and feature-flag tests. |
| Tenant authority | Routes now reject request-body tenant mismatches and use authenticated request tenant for persisted rows. | `services/api/actions/agentic_observability/foundation.py`, observability route modules | partial | Extend the same helper through x402 routes and legacy repositories. | PR 1/2 | Missing/mismatched/cross-tenant tests. |
| Graph tenant naming | Graph-boundary helper adds canonical `tenantId` while preserving legacy `tenant_id` for current graph readers. | `services/api/actions/agentic_observability/foundation.py` | partial | Complete graph-contract migration to one reader-visible canonical property. | PR 5 | Graph contract parity and cross-tenant graph tests. |
| Mutation counts | Agentic routes report built and persisted counts; compatibility `graph_mutations_queued` now equals persisted count. | `services/api/actions/agentic_observability/routes.py`, `schemas.py` | partial | Move all graph writes to durable outbox and update protocol/comm/external responses with the richer schema. | PR 2 | Truthful mutation count tests. |
| Silent graph failures | Shared helper logs structured graph projection failures and returns `failed` status without rejecting accepted observations. | `services/api/actions/agentic_observability/foundation.py` | partial | Store failures durably in outbox/dead-letter tables. | PR 2 | Worker retry/dead-letter tests. |
| Event name validation | Generic agent event endpoint rejects names not present in canonical generated registry. | `services/api/actions/agentic_observability/foundation.py`, `services/api/ingestion/ingestion/generated_registry.py` | partial | Add generated TS/Python/OpenAPI parity checks for all observability event families. | PR 1/3 | Unknown-event and parity tests. |
| No-execution invariant | Existing `Literal[False]` checks are backed by a shared route validator with clearer error text. | `services/api/actions/agentic_observability/foundation.py` | partial | Extend import-boundary/static dependency checks. | PR 8 | Negative route and import-boundary tests. |
| Kyber placeholders | Agentic, inbox, and external-account Kyber endpoints return repository-backed counts/lists instead of placeholder messages or hardcoded empty arrays. | observability route modules | partial | Build full Kyber lineage, replay, reconciliation, and health surfaces. | PR 7 | Non-placeholder route tests. |
| Canonical ingestion | Observability-specific JSONB repositories still accept production writes. | `repositories/agentic_observability_repos.py` | scaffold | Route through Bronze → Silver → canonical_activity → outbox. | PR 2 | Pipeline integration test. |
| Product surfaces | Profile 360, Journey v2, Cluster360, campaign, Noesis, and frontend propagation remain incomplete. | profile/journey/cluster/campaign/noesis/frontend services | missing | Implement propagation and evidence labeling. | PR 6/7 | End-to-end product scenario. |
