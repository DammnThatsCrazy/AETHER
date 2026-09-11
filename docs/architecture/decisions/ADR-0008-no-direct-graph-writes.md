---
title: "ADR-0008: No Direct Graph Writes"
slug: architecture/decisions/adr-0008-no-direct-graph-writes
section: architecture
visibility: P
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
---

# ADR-0008: No Direct Graph Writes

## Status

Accepted

## Context

Sources could write directly to the graph or go through a governed projection pipeline.

## Decision

No source writes arbitrary ungoverned data directly into the graph. All graph state must pass through contract validation, normalization, resolution, projection, and explainability metadata.

## Consequences

- Every graph mutation has a traceable source event
- Graph state is always explainable
- Ad hoc graph writes are prohibited
- Graph write paths are frozen pending mutation-gateway migration

## Enforcement

- `scripts/validate_graph_write_paths.py` enforces the graph write freeze
