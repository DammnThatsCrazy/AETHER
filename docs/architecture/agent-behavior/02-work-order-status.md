---
title: Agent Behavioral Intelligence — Work-Order Status
slug: architecture/agent-behavior/work-order-status
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0-alpha.0
---

# Agent Behavioral Intelligence — work-order status

This page records where each work order landed, how it is tested, and what is
still open. "Built" means code and focused tests exist on the program branch.
It is not a production-readiness claim. `scripts/production_status.py` stays
the readiness authority, and nothing here changes its scorecard.

Owners follow the [current architecture map](00-current-architecture-map.md).
Design decisions are in the [ADRs](../decisions/agent-behavior/README.md).
"Current" golden expectations are listed in
[golden scenarios](01-golden-scenarios.md).

## Status by phase

| Work orders | Status | Where | Tests |
|---|---|---|---|
| WO-000 – WO-002 baseline, ADRs, golden scenarios | Built | `docs/architecture/agent-behavior/`, `docs/architecture/decisions/agent-behavior/`, `tests/fixtures/agent_behavior/` | `test_agent_behavior_golden_scenarios.py` |
| WO-010 ActorRef | Built | `services/api/identity/identity/actor_ref.py` | `test_agent_behavior_foundation.py` |
| WO-011 – WO-013 agent identity, continuity, resolution claims | Built. Validated agents are registered as unresolved source identities by the identity ingestion worker; one agent ref reported by several deployments queues an `agent_continuity_candidate` review shown in Agent 360 | `identity/identity/agent_identity.py` | same |
| WO-020 authority boundary | Built | `actions/delegation/authority_boundary.py` | `test_agent_behavior_authority.py` |
| WO-021 delegation and lineage edges | Built. Spawn/delegation edges come from Silver; the human→agent grant edge is the delegation authority's existing `DELEGATES` edge (no duplicate edge type) | `ingestion/silver/projectors/silver_graph_projector.py` | golden test (edges marked current and pending) |
| WO-022 – WO-023 responsibility roles, influence | Built | `intelligence/agent_behavior/responsibility.py` | `test_agent_behavior_authority.py` |
| WO-030 event taxonomy | Built: 37 registry rows plus a dotted→snake map; all require a validated deployment at ingestion | `event-registry.json`, `intelligence/agent_behavior/taxonomy.py`, `ingestion/ingestion/validation.py` | foundation test |
| WO-031 adapters | Built for generic, MCP, model gateway, browser, wallet; commerce and communication use the generic mapping | `taxonomy.py` | foundation test |
| WO-032 Bronze | Existing Bronze; secret scrubbing verified for agent payloads | `ingestion/ingestion/validation.py` | foundation test |
| WO-033 Silver | Built: projector refs plus migration `20261029_agent_behavior_fact_refs` and `AgentFact` view | `agent_execution_projector.py`, `intelligence/agent_behavior/facts.py` | foundation test |
| WO-040 – WO-044 objectives, mutation, constraints, resources, state | Built | `intelligence/agent_behavior/objectives.py` | `test_agent_behavior_decisions.py` |
| WO-045 – WO-046, WO-050 – WO-052 opportunity, disposition, DecisionEnvelope, projector | Built; GS-C current | `intelligence/agent_behavior/decisions.py` | decisions and golden tests |
| WO-060 – WO-063, WO-073 journey, tools, information, memory, failure resolution | Built; GS-D current | `intelligence/agent_behavior/activity.py` | `test_agent_behavior_model.py` |
| WO-070 – WO-083 capability, competency, features, uncertainty, exploration, confidence, observability, model, preference | Built | `intelligence/agent_behavior/model.py` | model test |
| WO-090 – WO-091 attribution, influence graph | Built | `intelligence/agent_behavior/dynamics.py` | `test_agent_behavior_advanced.py` |
| WO-092 Value | Built. Value 360 serves an `agent_mediated_activity` section: `not_applicable` for non-agent subjects; for a canonical Agent it joins source agent refs only through the tenant-admin deployment identity binding (exact deployment match), then reports agent-selected/executed/influenced totals per currency, `reported` until a rail confirms. No binding is `unknown`, a source failure `degraded` | `value/attribution/agent_activity_reader.py`, `value/economic/economic360_provider.py` | `test_value360_agent_activity.py` |
| WO-093 Risk | Built. `agent_behavior` is a Risk360 evidence-bundle producer, so `compute_assessment` turns behavior evidence into agent-subject signals (`agentic`, `execution`, `behavioral`, `identity`, `security`, `data_quality` dimensions); also composed into the Agent 360 `risk` section | `intelligence/risk360/agent_behavior_signals.py` | advanced test |
| WO-094 Trust | Built under Risk (ADR-AB-011) | `intelligence/risk360/agent_trust.py` | advanced test |
| WO-100 – WO-103 snapshots, drift, adaptation, counterfactuals | Built. Window snapshots are stored in `agent_behavior_snapshots` (deterministic row key, rebuildable cache, `delete_by_agent` / `purge_before`); `POST /v1/agent/agents/{agent_ref}/behavior/snapshots` records a window and `GET .../behavior/drift` compares the two latest stored windows | `dynamics.py`, `snapshot_store.py` | `test_agent_behavior_snapshots.py` |
| WO-110 – WO-113 read models | Built. Routes `GET /v1/agent/agents/{agent_ref}/behavior` and `/decisions/{decision_id}`, and ten `behavior_*` Agent360 projection sections from the same builder (`actions/agent/behavior_read_model.py`). Projection sections fail closed with route parity (`not_applicable` registry off, `suppressed` without a server-derived `agent_behavior` authorization). Profile 360 reconciliation is a function, not yet a Profile 360 section | `intelligence/agent_behavior/read_models.py`, `actions/agent/agent360_provider.py`, `deployment_routes.py` | `test_agent_behavior_read_models.py` |
| WO-114 graph UI | Built as the Agent 360 behavior panel | `apps/aether-web/src/features/agent360/agent-behavior-panel.tsx` | `agent360-behavior.test.tsx` |
| WO-115 query orchestration | Built: closed capability list plus the read-only Noesis `agent_behavior` intent. It reads the same model as the behavior route and has the same gates (registry flag, `agent:manage`) | `read_models.py` (`QUERY_CAPABILITIES`), `noesis/adapters/agent_behavior_adapter.py` | read-model test, `test_noesis_agent_behavior_intent.py`, Noesis parity suites |
| WO-120 instrumentation API | Built: server SDK helpers and Python `build_behavior_event` | `packages/sdk/server/src/agent-telemetry.ts`, `packages/sdk/python/aether_agentic/agentic.py` | vitest and pytest |
| WO-121 – WO-122 web, React, iOS, Android | Event types regenerated into every SDK's contract; no new client helpers (agents are server-side) | generated SDK files | registry parity validators |
| WO-123 MCP / CLI / Access Kit | Built: operations declare `required_server_permission`. `agents.behavior` and `agents.decision` require `agent:manage` and are not advertised to read-only delegated OAuth tokens | `packages/access-kit/src/access-operations.mjs`, `agent-behavior-tools.mjs` | `agent-behavior.test.mjs` |
| WO-124 external behavioral query API | The two routes above | `deployment_routes.py` | read-model test |
| WO-130 – WO-132 communications, override, coupling | Built (references only, never content) | `read_models.py` | read-model test |
| WO-140 – WO-144 syndicates, swarm, contagion, demand, market compatibility | Built; syndicates never imply common control | `intelligence/agent_behavior/population.py` | advanced test |
| WO-150 – WO-151 strategic episodes, negotiation | Built | `population.py` | advanced test |
| WO-160 – WO-161 discontinuity, adversarial | Built; Risk signals via `agent_behavior_signals.py` | `population.py` | advanced test |
| WO-170 – WO-175 quality gates | Built | `test_agent_behavior_quality_gates.py` | — |

## Open items

1. **Continuity decisions feed nothing.** Confirm and reject routes record the reviewer's decision and never merge. A confirmed decision does not yet feed any continuity claim, and no UI action calls the routes.
2. **Projection authorization issuer.** The Agent360 `behavior_*` sections need a server-derived `agent_behavior` read authorization. The projection runtime does not issue one yet, so today the sections are visible through the route only.
3. **Scheduled pipelines.** Risk360 accepts agent behavior evidence through its evidence bundle, but no caller assembles that bundle on a schedule. Nothing records behavior snapshots on a schedule either; windows are recorded on request.
4. **Behavior is bounded.** Models and DecisionEnvelopes are rebuilt on read from at most 1,000 recent facts per agent. Snapshots are stored per window but the model itself is not a stored projection.
5. **Profile 360.** Human-agent reconciliation is a function, not a Profile 360 section.
6. **Calibration.** Every rate and confidence is uncalibrated. Only Wilson intervals are reported.
