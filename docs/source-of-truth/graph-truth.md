---
title: Graph truth
slug: source-of-truth/graph-truth
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Graph Truth

Aether's graph is tenant-scoped, contract-governed, and projection-driven.

## Graph Sources

The graph is populated from:

- SDK observations
- Provider connector events
- Communication events
- Campaign events
- Financial/value events
- Agent lifecycle events
- Identity resolution events
- System/runtime events

## Projection Rule

No source writes arbitrary ungoverned data directly into the graph.

All graph state must pass through:

1. Contract validation
2. Normalization
3. Resolution
4. Projection
5. Explainability metadata

## Core Graph Domains

- Profiles
- Agents
- Accounts
- Organizations
- Campaigns
- Journeys
- Episodes
- Communications
- Value
- Risk
- Signals
- Syndicates
- Lenses
