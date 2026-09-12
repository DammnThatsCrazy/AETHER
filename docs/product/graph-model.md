---
title: Graph Model
slug: product-graph-model
section: concepts
visibility: P
audience: [dev-senior, architect]
status: experimental
since_version: "0.1.0"
---

# Graph Model

The intelligence graph is the core data structure underlying all
Aether product surfaces. Every entity, relationship, and event
is a node or edge in the tenant-scoped graph.

## Core Invariants

- The graph is tenant-scoped; cross-tenant edges do not exist.
- Identity resolution merges observation keys into canonical
  entity nodes.
- Projections are governed views over the graph — never raw
  graph access.

## Graph Primitives

| Primitive | Description |
|---|---|
| Entity | A resolved identity node (person, account, device) |
| Observation | A raw event before resolution |
| Edge | A typed relationship between entities |
| Projection | A governed, filtered view of the graph |

## See Also

- `docs/architecture/current/identity-resolution.md`
- `docs/product/profiles.md` — Profile 360 surface
- `docs/product/contract-model.md` — Contract model
