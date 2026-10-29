---
title: Agent Behavioral Intelligence — Current Architecture Map (WO-000)
slug: architecture/agent-behavior/current-architecture-map
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0-alpha.0
---

# Agent Behavioral Intelligence — current architecture map

This is work order WO-000 of the Agent Behavioral Intelligence program. It
records where each concern lives today, after the PR #734 architecture reset
and the agent work that followed it (#815, #816, #826, #828, #832). Every later
work order names its owner from this page. No new behavior package may be
created until its owner is listed here.

This page is a dated snapshot, not a readiness claim. It was taken at
`development` @ `50bb9ec10` (2026-10-26). The integration branch is
`development`; `main` is held behind it (see
[architecture reset](../blueprints/architecture-reset/README.md)). The layer
owners below agree with the
[runtime authority map](../blueprints/architecture-reset/runtime-authority-map.md),
which remains the authority for L0–L8 runtime ownership.

Related: [ADRs](../decisions/agent-behavior/README.md) ·
[golden scenarios](01-golden-scenarios.md).

## 1. What already exists for agents

The program's evidence boundary (§0 of the work orders) lists six things that
must be proved in code. Several are partly built. Later work orders extend
these; they must not rebuild them.

| Proof item | Current implementation | What is still missing |
|---|---|---|
| Mobile → web journey continuation | `services/api/journeys/handoff/{service,routes,sweep}.py` issue and redeem a single-use, tenant-bound handoff token. A redemption records `link_basis = "explicit_handoff"` and never merges identities. SDK methods ship in web, iOS, Android and React Native (#832). | No link from a handoff to the agent run the user then started. The journey and the agent run are joined only in tests. |
| Nested-agent lineage | `services/api/actions/agent/lineage.py` builds a bounded, cycle-safe spawn tree from `agent_subagent_spawned` Silver rows. Every edge is `source_reported`; the tree sets `attribution = "none"`. | Agent refs are source claims, not resolved identities. No configuration-version or runtime-instance layer (WO-012). |
| Tool call / result capture | `agent_tool_invocation_observed`, `agent_tool_called` and `agent_tool_observed` project to `silver_agent_execution_facts` with `tool_name`, `server_url`, `status`, `object_type/id`. Lineage rolls up calls per agent. | No Tool entity or ToolInvocation record, no result payload, and no retry or switch semantics (WO-061). A failed call counts as a call. |
| Actor / fleet attribution | `services/api/intelligence/fraud_networks/fleet_hypothesis.py` builds evidence-qualified hypotheses. Circumstantial evidence is capped at 0.55, delegation at 0.9. Only a human reviewer can confirm. Competing explanations are always generated. | Responsibility roles are not separated (WO-022). Influence is not a typed edge (WO-023). |
| Risk 360 surfacing | Fleet hypotheses carry Risk360 `risk_context`. `fraud_networks/fleet_fraud360.py` and `fraud_networks/risk360_projection.py` project findings into Fraud360/Risk360. | Risk does not yet consume behavioral features. There are none yet (WO-093). |
| End-to-end reconstruction | `services/api/tests/agent/test_multi_agent_attribution_scenarios.py` runs GS-A and GS-B from SDK-shaped events through the real Silver projector, lineage, handoff and fleet routes. | No objective, DecisionEnvelope, candidate set, AgentJourney or behavior model. Those are WO-040 to WO-082. |

## 2. Domain owners

"Owner" is the code that is the authority today. A work order that needs a
concern adds to this owner. A parallel owner needs an ADR
([ADR-AB-010](../decisions/agent-behavior/ADR-AB-010-placement-follows-current-owners.md)).

| Concern | Owner today | Notes for agent behavior |
|---|---|---|
| Canonical contracts | `packages/shared/contracts/*.json` → `scripts/generate_contracts.py` → generated TS in `packages/shared/` and backend `generated_registry.py` files | Event types, consent purposes, observation envelopes, projections and lenses are registry rows. Never hand-edit generated outputs. |
| Ingress | `services/api/ingestion/ingestion/batch.py` (`/v1/batch`), `ingestion/ingestion/gateway.py` (Envelope B), `ingestion/ingestion/validation.py`. Connectors use `services/api/connectors/provider_runtime/{acquisition,webhook}.py`. | Agent telemetry already enters through `/v1/batch` with `context.agentDeployment` validated against the deployment registry. See [external agent telemetry plane](../../reference/source-of-truth/EXTERNAL_AGENT_TELEMETRY_PLANE.md). |
| Raw evidence (Bronze, L0) | `ingestion/ingestion/bronze_bulk.py`, `services/api/repositories/lake.py` (`BronzeRepository`), `connectors/provider_runtime/raw_store.py` | Provider rights admission (`connectors/provider_runtime/rights_admission.py`) is the single raw-admission authority. |
| Normalized facts (Silver, L1) | `services/api/ingestion/silver/{dispatcher,writer}.py`, projectors in `ingestion/silver/projectors/` | Agent facts are written by `agent_execution_projector.py` to `silver_agent_execution_facts`. Projector ownership is a registry (`packages/shared/contracts/projector-ownership-registry.json`). |
| Identity / resolution (L2) | `services/api/identity/identity/{source_identity_registry,resolver,merge_policy,repository,split_service,resolution_replay}.py` | `agent_id` and `deployment_id` are on the merge denylist (`merge_policy.py`). Agent ↔ human no-merge is pinned by `tests/e2e/proof/packages/fixtures/fixtures/identity/scenario_d_agent_human_no_merge.json`. |
| Relationship graph (L3) | `services/api/shared/graph/{mutation_gateway,mutation_intents,write_validator}.py`; vertex and edge types in `shared/graph/graph.py`; ledger in `repositories/graph_mutation_ledger.py` | All graph writes go through `MutationIntent → GraphMutationGateway.apply` (ADR-0008). Agent edges already exist: `OWNS_AGENT`, `AUTHORIZED_AGENT`, `DELEGATED_TO`, `SPAWNED_SUBAGENT`, `HANDED_OFF_TO`, `CALLED_TOOL`, `ACTED_FOR`, `HUMAN_DELEGATED_TO_AGENT`, `ESCALATED_TO_HUMAN`. |
| Authority / delegation | `services/api/actions/delegation/engine.py` with `DelegationRepository` (`repositories/repos.py`) | Scoped grants: actions, resources, `max_amount`. A stored grant is not an effective authorization decision. Agent360 says so explicitly. |
| Journeys / value computation (L4) | `services/api/journeys/measurement/` (journey compiler, outcome contracts); `services/api/value/` (economic, attribution, commerce, x402) | `value/economic/journey_operation_evidence.py` already joins agent operations to economic evidence. |
| Projections / read models (L5) | `services/api/shared/intelligence_projections/{contracts,registry,provider,frame_runtime}.py`, registry `packages/shared/contracts/intelligence-projection-registry.json` | `ProjectionRequest → ProjectionResult` of `ProjectionSection`s carrying `ClaimEnvelope`s. Agent360 is `actions/agent/agent360_provider.py`; Execution360 is `actions/agent/execution360_provider.py`; Profile360 is `identity/profile/profile360_provider.py`; Relationship360 is `identity/relationship_intelligence/relationship360_provider.py`. |
| Intelligence (L6) | `services/api/intelligence/` | `intelligence/intelligence/decision_models.py` holds Aether's **own** recommendation `DecisionRecord`. It is not an observed agent's decision (see ADR-AB-003). `intelligence/behavior/` and `intelligence/behavioral/` hold **human** Profile360 behavior signals. |
| Risk | `services/api/intelligence/risk360/`, `intelligence/fraud360/`, `intelligence/fraud_networks/` | Fleet hypotheses and Risk360/Fraud360 projections live here. |
| Trust / reputation | `services/api/intelligence/risk360/agent_trust.py` (ADR-AB-011) | Trust and reputation are separate profiles under Risk; product naming (`naming-truth.md`) already puts trust exposure under Risk. |
| Actions / execution (L7) | `services/api/actions/delivery/`, `intelligence/intelligence/routes.py` | Aether-executed actions only. Observed agents' actions are facts, not Aether actions. `execution_by_aether` stays `False` (ADR-011). |
| Agentic observability | `services/api/actions/agentic_observability/` (normalizer, provenance, risk signals, graph mutations) | Provider-framework normalization for agent accounts, inboxes and trading. Adapters only; no behavioral inference. |
| Query / access | `services/api/intelligence/noesis/` (natural-language graph intelligence), `packages/access-kit/` (CLI and MCP read bridge), `services/api/governance/kyber/access/` (operator access) | No cross-domain "query orchestrator" module exists by that name. WO-115 extends Noesis capability registration and the Access Kit closed read list. |
| Replay / restatement | `services/api/replay/projections/projection_restatement_orchestrator.py`, `identity/identity/resolution_replay.py` | Behavior models must be rebuildable through this path (ADR-AB-002). |
| Tenant / rights | `services/api/shared/auth/auth.py` (`TenantContext`), `services/api/tenancy/rights_authority/`, `services/api/governance/consent/` | Tenant comes from authentication, never from a payload. Rights and consent are checked at the owning boundary. |
| Control plane | `docs/architecture/RECONCILED_CONTROL_PLANE.md` and its implementation | Owns rollout, compatibility, quarantine and replay. It does not own behavioral meaning (INV-009). |
| Internal agents | `services/agents/` (the Nous controller with intake, discovery, enrichment, verification and commit controllers) | Internal operations agents. The work orders call them "KIRA / LOOP / controllers"; those names do not appear in the tree. They may consume behavioral intelligence. They are never the source of truth for observed external agents (ADR-AB-007). |
| Frontend | `apps/aether-web/src/features/agent360/`, `features/agent-access/`, `pages/agent-access/` | Reads backend projections only (INV-007). |

## 3. Legacy and deprecated paths

Do not add agent-behavior work to any of these:

- Direct graph writes outside `GraphMutationGateway.apply`. `scripts/validate_graph_write_paths.py` enforces this.
- The retired legacy resolution graph writer and the fail-closed cluster, approval, batch and engine mutation entry points.
- `services/api/intelligence/recommendations/{engine,executor}.py` and `intelligence/suggestions/adapters/recommendation_adapter.py`. These are parallel recommendation and execution seams being merged into the canonical decision and delivery authority.
- `services/api/actions/agent/mutation_commit.py` as an execution path.
- `services/api/journeys/journeys/stitching.py` and `intelligence/intelligence/outcome_ledger.py` as journey or outcome truth. The measurement journey compiler and outcome contracts own those.
- SDK V1 `BronzeRepository("sdk_events")` for new event families. Use the V2 typed Bronze and outbox path.
- `docs/archive/legacy-architecture/`.
- The old `frontend/` tree. Web apps live in `apps/`.

## 4. Event versioning

- One registry: `packages/shared/contracts/event-registry.json` (`schemaVersion` 2.2.0, `contractVersion` 0.1.0-alpha.0). It has 453 event rows today (416 before WO-030).
- Each row declares `type`, `family`, `semanticLevel`, `sdkEmitable`, `requiredPurposes`, `privacyClass`, `retentionClass`, `silverProjection`, `graphProjection`, `status`, `introducedVersion` and per-field `fieldTrust`.
- Event types are **snake_case** (`agent_tool_invocation_observed`, `agent_subagent_spawned`). The work orders' dotted names (`agent.tool.invoked`) are a design vocabulary. WO-030 must map them onto registry rows. It must not add a parallel dotted namespace. Observed external-agent facts use the `_observed` suffix.
- The registry already has 64 event types whose name contains `agent`, including `agent_task_*`, `agent_decision`, `agent_delegated_task`, `agent_subagent_spawned`, `agent_tool_*`, `agent_policy_evaluated`, `agent_authorized` / `agent_deauthorized`, `agent_capability_granted` / `agent_capability_revoked`, `agent_handoff`, `agent_escalated_to_human`, `agent_outcome_recorded`, `agent_human_override_observed`, agent messaging and agent trading.
- New types are added as registry rows, then regenerated with `scripts/generate_contracts.py`. Unknown fields or unsupported versions are kept as typed degraded or quarantined evidence, not dropped.

## 5. Evidence and provenance primitives

| Primitive | Location | Use |
|---|---|---|
| Observation envelope | `services/api/shared/observation/envelope.py` (`SourceBlock`, `SubjectRef`, `TemporalBlock`, `CorrelationBlock`, `PrivacyBlock`) | Ingress provenance. The SDK can assert at most `CLIENT_HINT` trust. |
| Epistemic status | `services/api/shared/contracts_models/epistemic.py`, TS twin `packages/shared/epistemic-status.ts` | One vocabulary for claim strength: `observed`, `verified`, `resolved`, `derived`, `inferred`, `predicted`, `correlated`, `attributed`, `causally_supported`, `disputed`, `superseded`, `stale`, `unknown`, `unavailable`, `not_applicable`. The no-silent-escalation rule lives here. |
| Claim envelope | `shared/intelligence_projections/contracts.py` (`ClaimEnvelope`) | How a projection presents a claim with evidence and status. |
| Graph mutation provenance | `shared/graph/mutation_intents.py` plus the mutation ledger | Tenant, source event identity, provenance, rights reference and idempotency on every graph write. |
| Agentic provenance | `actions/agentic_observability/provenance.py`, `value/x402/provenance.py` | Domain provenance for agent and x402 observations. |

The program's state list (INV-002: `declared`, `observed`, `resolved`,
`derived`, `inferred`, `unknown`, `not_observed`, `not_applicable`) maps onto
`EpistemicStatus` with two gaps. `declared` has no member. Today a source
declaration is `observed` with `SOURCE_ASSERTED` field trust. `not_observed`
has no member. It is closest to `unavailable`. ADR-AB-009 records how both are
represented without forking the vocabulary.

## 6. Tenant and rights boundaries

- The tenant comes from `TenantContext`. Every repository read and write is tenant-scoped. A cross-tenant read returns not-found without revealing that the record exists.
- Consent purposes come from `packages/shared/contracts/consent-registry.json`. Each event row declares `requiredPurposes`.
- Erasure and DSR propagation run through `services/api/governance/consent/{erasure_jobs,erasure_planes}.py` and `governance/dsr_propagation/`. Journey handoff erasure was added in #832. Every new agent store must register an erasure plane.
- Storage retention is declared per store in `config/storage_policies.yaml`.
- Secrets (private keys, passwords, tokens, raw credentials) are never persisted. The SDK scrubs them and ingestion validation scrubs them again.

## 7. Persistence interfaces

- **Graph:** produce `MutationIntent`s and submit them through `GraphMutationGateway.apply`. Read through tenant-qualified vertex IDs.
- **Silver:** `SilverFactWriter.persist(ProjectionResult)`. Projectors are pure functions from event to rows.
- **Domain repositories:** `services/api/repositories/repos.py` (`BaseRepository` and domain repositories), with in-memory fallbacks for tests (`reset_in_memory_stores`).
- **Read models:** register an `IntelligenceProjectionProvider` in the projection registry. Do not add a bespoke route-level composer.
- **Migrations:** Alembic in `services/api/alembic/versions/`.

## 8. Current naming

- Product surfaces: Agent 360, Execution 360, Profile 360, Relationship 360, Journey 360, Risk 360, Fraud 360, Value 360 (contract ID `economic360`). Experience 360 composes actor parties. Deprecated terms are listed in `docs/reference/source-of-truth/naming-truth.md`.
- The operator plane is **Kyber**. The tenant app is **Aether**.
- Graph vertices: `Agent`, `ExternalAgent`, `AgentExecutionRun`, `AgentTemplate`, `User`, `Organization`, `Wallet`.
- Lineage status vocabulary: `source_reported`. Fleet status vocabulary: `unconfirmed`, `needs_review`, `confirmed_by_reviewer`, `rejected_by_reviewer`.

## 9. Work-order placement

Each work order is placed with its owner. "Extend" means add to the named
module or registry. "New, in owner" means a new module inside the owning
package.

| Work orders | Owner | Placement |
|---|---|---|
| WO-010 ActorRef | Identity | Extend `SubjectRef`, the graph vertex types and the identity subject model. Do not add a parallel actor table. |
| WO-011 – WO-013 Agent identity and continuity | Identity / resolution | New, in `services/api/identity/identity/`. Agent claims go through `SourceIdentityRegistry` and the resolver. Keep the merge denylist. |
| WO-020 Authority | Delegation engine and graph | Extend `actions/delegation/engine.py` scope with the economic constraints. Authorization events are registry rows. |
| WO-021 – WO-023 Delegation, lineage, responsibility, influence | Relationship graph | Edge types in `shared/graph/graph.py`, produced as `MutationIntent`s. Lineage reads extend `actions/agent/lineage.py`. |
| WO-030 Event taxonomy | Contracts | Rows in `event-registry.json`, mapped to snake_case. |
| WO-031 Adapters | Provider runtime / agentic observability | `connectors/provider_runtime/`, `actions/agentic_observability/provider_framework.py`, and the server SDK `packages/sdk/server/src/agent-telemetry.ts`. |
| WO-032 – WO-033 Bronze and Silver | Ingestion | Existing Bronze. Extend `agent_execution_projector.py` or add a sibling projector registered in the projector ownership registry. |
| WO-040 – WO-075 Objectives through behavior features | Intelligence (new bounded area) | New, in `services/api/intelligence/agent_behavior/` as projectors over Silver and the graph. Read-only toward facts (ADR-AB-001, ADR-AB-008). |
| WO-080 – WO-083 Confidence, observability, behavior model | Intelligence plus contracts | Reuse `EpistemicStatus` and `ClaimEnvelope`. The model is a rebuildable projection. |
| WO-090 – WO-091 Attribution and influence | Intelligence plus graph | Influence edges are inferred `MutationIntent`s with evidence. |
| WO-092 Value | Value | `services/api/value/` consumes behavior facts. Value math never goes inside DecisionEnvelope. |
| WO-093 Risk | Risk | `intelligence/risk360/` and `fraud_networks/` consume behavior signals. |
| WO-094 Trust | Risk | `intelligence/risk360/agent_trust.py` (ADR-AB-011). |
| WO-100 – WO-103 Drift and counterfactuals | Intelligence | `intelligence/agent_behavior/`. |
| WO-110 – WO-113 Read models | Projections | Extend the Agent360 and Profile360 providers and the projection registry. |
| WO-114 Graph UI | Frontend | `apps/aether-web/src/features/agent360/`. |
| WO-115 Query | Noesis and Access Kit | Capability registry and closed read list. |
| WO-120 – WO-124 SDK, API, MCP, CLI | SDKs and Access Kit | `packages/sdk/*`, `packages/access-kit/`. |
| WO-160 – WO-161 Adversarial | Risk | `intelligence/fraud_networks/`, `intelligence/risk360/`. |
| WO-170 – WO-175 Tests | Owning domain | Next to each implementation. Golden fixtures live in `tests/fixtures/agent_behavior/`. |

`services/api/intelligence/agent_behavior/` is the only new package this
program introduces. It is justified in ADR-AB-001. It does not exist yet and is
created by the first work order that needs it (WO-040).
