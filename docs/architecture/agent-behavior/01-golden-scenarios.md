---
title: Agent Behavioral Intelligence — Golden Scenarios (WO-002)
slug: architecture/agent-behavior/golden-scenarios
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0-alpha.0
---

# Agent Behavioral Intelligence — golden scenarios

Work order WO-002 defines what "working" means for the program as four
permanent fixtures:

- Data: `tests/fixtures/agent_behavior/golden_scenarios.json`
- Test: `services/api/tests/agent/test_agent_behavior_golden_scenarios.py`

Run them with:

```bash
PYTHONPATH=services/api .venv/bin/python -m pytest -q services/api/tests/agent/test_agent_behavior_golden_scenarios.py
```

## Scenarios

| ID | Scenario | What it guards |
|---|---|---|
| GS-A | A person goes from mobile to web through an explicit handoff, delegates to an orchestrator, which spawns two workers that call tools and return an outcome. | Cross-device continuity without identity merge. Spawn lineage. Tool capture. A small user-owned fleet stays low priority. |
| GS-B | A Risk360-flagged actor's orchestrator spawns 15 workers that scan one wallet and quote swaps over one shared RPC endpoint. One swap attempt is rejected. | Fleet attribution stays a reviewable hypothesis. Cluster evidence is never shown as a proven operator. |
| GS-C | An agent with a purchase objective finds a candidate. A spend policy denies the purchase and the agent abstains. | Policy denial is recorded and nothing executes. Non-selection is not read as preference (ADR-AB-004). |
| GS-D | Tool A fails, is retried and fails again. The agent switches to tool B, which succeeds. | Failed and successful tool results are captured in order, so retry and switch can be derived later. |

## Current and pending expectations

Each expectation in the fixture is in one of two states:

- **current** — true of today's code. The test asserts it.
- **pending** — the target shape. It names the work order (`owner_work_order`) that must make it current.

The test checks both directions. A current graph edge must be emitted. A
pending graph edge must *not* be emitted yet. If a pending edge starts being
emitted, the test fails and tells the author to mark it current. When a work
order lands, it updates this fixture and test. It does not add a new fixture.

Today the current expectations cover:

- Silver facts in `silver_agent_execution_facts`.
- Spawn lineage: agent count, depth, per-child tools and outcomes, and the source event behind each spawn edge.
- Tool results and their status, and GS-D's failure resolution (retry, then switch, then resolved).
- Policy decisions, and GS-C's DecisionEnvelope, OpportunityEnvelope and ActionDisposition (`constrained_non_action`).
- Fleet hypotheses: status, priority, person link, confidence cap, competing explanations.
- `AGENT_USED_TOOL_OBS` and `SPAWNED_SUBAGENT` graph edges.
- The handoff link.

Still pending:

- DecisionEnvelopes for GS-A, GS-B and GS-D (WO-050). These need explicit decision events, which those scenarios do not emit.
- AgentJourney join to the human journey (WO-060). GS-A emits no `journeyId`.
- Scenario read models (WO-093, WO-110 – WO-112).
- The `HUMAN_DELEGATED_TO_AGENT` grant edge (WO-021).

## Rules for the fixture

- Event IDs are `<scenario>-evt-NNNN`, in occurrence order. They are unique across the file.
- Every event type must be an active row in `packages/shared/contracts/event-registry.json` and must be handled by the agent Silver projector.
- Every graph edge type must exist in `shared/graph/graph.py`.
- Every evidence reference must name an event in the same scenario.
- Each scenario's `known_gaps` lists what the current code cannot show. Do not delete a gap until a test proves it is closed.

The existing end-to-end route test
`services/api/tests/agent/test_multi_agent_attribution_scenarios.py` also runs
GS-A and GS-B through the HTTP route layer and the fleet review path. These
fixtures do not replace it.
