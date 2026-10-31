---
title: "ADR-AB-007: Internal Aether agents are separate from observed agents"
slug: decisions/agent-behavior/adr-ab-007-internal-vs-observed-agents
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0-alpha.0
---

# ADR-AB-007: Internal Aether agents are separate from observed agents

**Status:** Accepted for the Agent Behavioral Intelligence program (WO-001).
Applies to every later work order.

## Context

Aether runs its own internal agents (`services/agents/`: the Nous controller
and its intake, discovery, enrichment, verification and commit controllers).
Tenants' external agents are observed through telemetry. Mixing them would let
Aether's own automation write truth about the agents it observes.

## Decision

Observed external agents are the subject of this program. Internal Aether
agents may **consume** behavior projections through the same read contracts as
any other consumer. They are never a source of truth for an observed agent's
identity, decisions or behavior, and their outputs about observed agents are
recommendations or review items, not facts. If Aether's own agents are ever
observed, they are a separate, labelled source namespace.

## Consequences

- Reviewers reject any write path from `services/agents/` into agent behavior stores.
