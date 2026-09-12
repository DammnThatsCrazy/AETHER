---
title: "Graph Architecture"
slug: architecture/current/graph-architecture
section: architecture
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# Graph Architecture

## Model

Tenant-scoped intelligence graph built from four primitives:
**Entity**, **Observation**, **Edge**, and **Projection**.

## Graph Primitives

- **Entity** — a resolved identity node (Profile, Account, Organization,
  Agent, Campaign, Journey)
- **Observation** — an immutable fact attached to an entity (event,
  measurement, communication, value, risk)
- **Edge** — a typed, directed relationship between entities
- **Projection** — a governed, materialized view of graph state for a
  specific surface or lens

## Entity Types

- Profile (human, account, organization)
- Agent
- Campaign
- Journey
- Episode
- Communication

## Projection

Graph state is populated through governed projections, not direct ad hoc
writes (see ADR-0008). Every projection cites source observations and
attaches explainability metadata.

## Query

Graph queries are scoped to the requesting tenant. Cross-tenant queries are prohibited by design.

## Current State

Graph projection and Profile360 are functional. Multi-hop traversal, lens composition, and advanced query surfaces are converging.
