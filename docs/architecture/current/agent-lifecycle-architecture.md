---
title: Agent Lifecycle Architecture
slug: agent-lifecycle-architecture
section: architecture
visibility: I
audience: [dev-senior, architect]
status: experimental
since_version: "0.1.0"
---

# Agent Lifecycle Architecture

## Overview

Agents in Aether are autonomous or semi-autonomous entities that act on
intelligence graph state — triggering communications, adjusting campaign
parameters, or surfacing recommendations.

## Lifecycle States

```
defined → configured → activated → running → paused → deactivated
```

- **Defined**: agent template exists but is not bound to a tenant.
- **Configured**: bound to a tenant with parameters set.
- **Activated**: ready to process triggers.
- **Running**: actively processing graph events.
- **Paused**: temporarily suspended, state preserved.
- **Deactivated**: removed from active processing.

## Architecture

```
graph event / schedule trigger
→ agent trigger evaluation
→ consent + governance check
→ agent action execution
→ action observation (re-enters ingestion)
→ graph update
```

## Governance

- Agent actions are observations that re-enter the standard ingestion
  pipeline.
- Model governance gates (consent-scoped training + inference) apply to
  ML-backed agents.
- Agent actions are auditable and reversible.

## Current State

Agent lifecycle is partially implemented. See
`Backend Architecture/aether-backend/services/agents/` and
`ML Models/` for current runtime components.
