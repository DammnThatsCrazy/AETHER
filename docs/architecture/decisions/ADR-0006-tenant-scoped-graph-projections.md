---
title: "ADR-0006: Tenant-Scoped Graph Projections"
slug: architecture/decisions/adr-0006-tenant-scoped-graph-projections
section: architecture
visibility: P
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
---

# ADR-0006: Tenant-Scoped Graph Projections

## Status

Accepted

## Context

The graph could be global or tenant-scoped. A global graph risks data leakage between tenants.

## Decision

All graph state is tenant-scoped. Cross-tenant queries are prohibited by design. Graph projections are scoped to the tenant that owns the source data.

## Consequences

- No cross-tenant graph traversal
- Tenant isolation is enforced at the graph layer
- Multi-tenant aggregation requires explicit, governed mechanisms

## Enforcement

- `scripts/validate_graph_scoped_reads.py` validates scoped read patterns
- Graph write paths validated by `scripts/validate_graph_write_paths.py`
