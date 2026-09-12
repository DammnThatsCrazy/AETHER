---
title: Noesis Surface
slug: product-noesis-surface
section: concepts
visibility: P
audience: [buyer]
status: experimental
since_version: "0.1.0"
---

# Noesis Surface

Noesis is an analytical **productized graph view** within Aether —
a governed projection of the intelligence graph focused on
retrospective analysis, cohort insights, and predictive modeling.
It is not a standalone application; it reads from the same
tenant-scoped graph as every other surface.

## Capabilities

- Cohort analysis and segmentation over graph projections
- Attribution modeling across entity relationships
- Predictive scoring using ML model outputs projected into the graph
- Trend analysis over time-series graph state
- Reporting and export from governed projections

## Architectural Boundary

Noesis renders governed graph projections; it does not write to the
graph directly. Analytical outputs (scores, segments, predictions)
re-enter the platform as observations through `/v1/batch`.

## See Also

- `docs/product/aether-surface.md` — Aether platform surface
- `docs/product/kyber-surface.md` — Kyber operational surface
- `docs/architecture/decisions/ADR-0007-360s-as-productized-graph-surfaces.md`
