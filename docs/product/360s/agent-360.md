---
title: "Agent 360"
slug: product/360s/agent-360
section: concepts
visibility: P
audience: [buyer, dev-senior]
status: stable
since_version: "0.1.0"
---

# Agent 360

The Agent 360 provides a complete view around its domain, built on top of the tenant-scoped intelligence graph.

In Aether, the customer route is `/agents/:agentId`; it composes the existing
tenant-scoped `/v1/profile/{agentId}/agent` read. Agent Access remains the
separate capability-reach and authorization view.

Aether observes agents; it does not run or admit them (ADR-012). A tenant may
declare its own agent through `POST /v1/agents`, and observed runs arrive
through `POST /v1/batch`. Execution rows written by the retired
`POST /v1/agents/{agent_id}/execute` and `.../status` routes stay readable as
history. Completion records that
the executor finished the task; it does not establish payment settlement or
successful business value. Those require the matching authoritative commerce,
x402, or chain evidence.

## Status

See `docs/architecture/target/360-system-blueprint.md` for the current state and gaps.
