---
title: Kyber Surface
slug: product-kyber-surface
section: concepts
visibility: P
audience: [buyer]
status: experimental
since_version: "0.1.0"
---

# Kyber Surface

Kyber is an operational **productized graph view** within Aether —
a governed projection of the intelligence graph focused on real-time
decision-making, campaign orchestration, and agent execution. It is
not a standalone application; it reads from the same tenant-scoped
graph as every other surface.

## Capabilities

- Real-time entity resolution and graph traversal
- Campaign trigger evaluation against graph state
- Agent task dispatch and lifecycle tracking
- Communication orchestration through connectors
- Operational dashboards over live projections

## Architectural Boundary

Kyber renders governed graph projections; it does not write to the
graph directly. Operational actions (agent dispatches, communication
sends) re-enter the platform as observations through `/v1/batch`.

## See Also

- `docs/product/aether-surface.md` — Aether platform surface
- `docs/product/noesis-surface.md` — Noesis analytical surface
- `docs/architecture/decisions/ADR-0007-360s-as-productized-graph-surfaces.md`
