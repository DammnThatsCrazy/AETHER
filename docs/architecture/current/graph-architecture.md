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

Tenant-scoped property graph with typed nodes and edges.

## Node Types

- Profile (human, account, organization)
- Agent
- Campaign
- Journey
- Episode
- Communication
- Value event
- Risk event

## Projection

Graph state is populated through governed projections, not direct ad hoc writes. Every projection cites source events and attaches explainability metadata.

## Query

Graph queries are scoped to the requesting tenant. Cross-tenant queries are prohibited by design.

## Current State

Graph projection and Profile360 are functional. Multi-hop traversal, lens composition, and advanced query surfaces are converging.
