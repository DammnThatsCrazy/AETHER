---
title: Aether Surface
slug: product-aether-surface
section: concepts
visibility: P
audience: [buyer]
status: experimental
since_version: "0.1.0"
---

# Aether Surface

Aether is a contract-governed intelligence infrastructure platform.
The platform surface is the unified view across all productized
graph views (360 surfaces), interpretive lenses, and the underlying
tenant-scoped intelligence graph.

## Productized Graph Views

Every named surface in Aether is a **productized graph view** — a
governed projection of the intelligence graph rendered for a specific
operational or analytical purpose. Surfaces are not independent
applications; they are facets of the same graph, scoped to the
requesting tenant.

- **Kyber** — operational graph view for real-time decisioning,
  campaign orchestration, and agent execution
- **Noesis** — analytical graph view for retrospective analysis,
  cohort insights, and predictive modeling
- **360 Surfaces** — entity-centric graph views (Profile360,
  Campaign360, Journey360, etc.)
- **Lenses** — interpretive graph views that compose multiple
  projections (Value, Risk, Signals, etc.)

## Architectural Boundary

Surfaces read from governed graph projections; they never write to
the graph directly (see ADR-0008). New evidence re-enters the
platform through the canonical `/v1/batch` ingestion path.

## See Also

- `docs/product/kyber-surface.md` — Kyber operational surface
- `docs/product/noesis-surface.md` — Noesis analytical surface
- `docs/product/graph-model.md` — Graph primitives
- `docs/architecture/decisions/ADR-0007-360s-as-productized-graph-surfaces.md`
- `docs/architecture/decisions/ADR-0008-no-direct-graph-writes.md`
