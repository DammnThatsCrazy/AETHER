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
| WO-011 – WO-013 agent identity, continuity, resolution claims | Built; claims are not yet submitted to the resolver | `identity/identity/agent_identity.py` | same |
| WO-020 authority boundary | Built | `actions/delegation/authority_boundary.py` | `test_agent_behavior_authority.py` |
| WO-021 delegation and lineage edges | Built for spawn and delegation; the human→agent grant edge is still pending | `ingestion/silver/projectors/silver_graph_projector.py` | golden test (edges marked current and pending) |
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
| WO-092 Value | Built as a Value-owned seam; not yet called by a Value 360 provider | `value/attribution/agent_behavior_value.py` | advanced test |
| WO-093 Risk | Built as RiskSignal adapters; not yet wired into the Risk360 pipeline run | `intelligence/risk360/agent_behavior_signals.py` | advanced test |
| WO-094 Trust | Built under Risk (ADR-AB-011) | `intelligence/risk360/agent_trust.py` | advanced test |
| WO-100 – WO-103 snapshots, drift, adaptation, counterfactuals | Built; snapshots are computed on read, not stored | `dynamics.py` | advanced test |
| WO-110 – WO-113 read models | Built: routes `GET /v1/agent/agents/{agent_ref}/behavior` and `/decisions/{decision_id}`; Profile 360 reconciliation is a function, not yet a Profile 360 section | `intelligence/agent_behavior/read_models.py`, `actions/agent/deployment_routes.py` | `test_agent_behavior_read_models.py` |
| WO-114 graph UI | Built as the Agent 360 behavior panel | `apps/aether-web/src/features/agent360/agent-behavior-panel.tsx` | `agent360-behavior.test.tsx` |
| WO-115 query orchestration | Built as a closed capability list; not yet registered with Noesis | `read_models.py` (`QUERY_CAPABILITIES`) | read-model test |
| WO-120 instrumentation API | Built: server SDK helpers and Python `build_behavior_event` | `packages/sdk/server/src/agent-telemetry.ts`, `packages/sdk/python/aether_agentic/agentic.py` | vitest and pytest |
| WO-121 – WO-122 web, React, iOS, Android | Event types regenerated into every SDK's contract; no new client helpers (agents are server-side) | generated SDK files | registry parity validators |
| WO-123 MCP / CLI / Access Kit | **Gap.** The Access Kit operation table declares `read` permission; the behavior routes need `agent:manage`. Adding them needs a read-scoped route first. | — | — |
| WO-124 external behavioral query API | The two routes above | `deployment_routes.py` | read-model test |
| WO-130 – WO-132 communications, override, coupling | Built (references only, never content) | `read_models.py` | read-model test |
| WO-140 – WO-144 syndicates, swarm, contagion, demand, market compatibility | Built; syndicates never imply common control | `intelligence/agent_behavior/population.py` | advanced test |
| WO-150 – WO-151 strategic episodes, negotiation | Built | `population.py` | advanced test |
| WO-160 – WO-161 discontinuity, adversarial | Built; Risk signals via `agent_behavior_signals.py` | `population.py` | advanced test |
| WO-170 – WO-175 quality gates | Built | `test_agent_behavior_quality_gates.py` | — |

## Open items

1. **Human→agent grant edge.** `HUMAN_DELEGATED_TO_AGENT` is not emitted when a delegation is recorded. It stays pending in GS-A and GS-B.
2. **Resolver submission.** Agent identity claims and continuity review items are produced but not yet submitted to the identity resolver or the pending-review queue.
3. **Pipeline wiring.** The Value, Risk360 and Noesis seams are callable and tested, but no provider or pipeline run calls them yet.
4. **Persistence.** Behavior models, snapshots and DecisionEnvelopes are rebuilt on read from at most 1,000 recent facts per agent. Longer histories need a stored, replayable projection. That decision goes through the projection registry.
5. **Access Kit.** See WO-123 above.
6. **Calibration.** Every rate and confidence is uncalibrated. Only Wilson intervals are reported.
