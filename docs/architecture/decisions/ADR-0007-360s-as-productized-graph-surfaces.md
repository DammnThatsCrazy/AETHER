---
title: "ADR-0007: 360s as Productized Graph Surfaces"
slug: architecture/decisions/adr-0007-360s-as-productized-graph-surfaces
section: architecture
visibility: P
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
---

# ADR-0007: 360s as Productized Graph Surfaces

## Status

Accepted

## Context

Graph data needs to be surfaced to users in meaningful, contextual views.

## Decision

360s are productized graph surfaces that provide a complete view around one entity or domain. Lenses are interpretive views over graph state. Both are read/query surfaces — they do not write to the graph.

## Consequences

- 360 surfaces are defined by the graph schema, not ad hoc queries
- Each 360 has a defined set of graph traversals and aggregations
- New 360s require graph schema support

## Enforcement

- 360 surfaces validated against graph schema
- Lens composition validated for consistency
