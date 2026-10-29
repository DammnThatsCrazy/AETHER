---
title: "ADR-AB-001: Agent behavior is a bounded intelligence domain, not a platform"
slug: decisions/agent-behavior/adr-ab-001-bounded-intelligence-domain
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0-alpha.0
---

# ADR-AB-001: Agent behavior is a bounded intelligence domain, not a platform

**Status:** Accepted for the Agent Behavioral Intelligence program (WO-001).
Applies to every later work order.

## Context

Observed agents already enter Aether through the canonical ingestion spine
(`/v1/batch`, Bronze, `silver_agent_execution_facts`), resolve through the
identity authority, and appear in Agent360 and Execution360. The work-order
program adds objectives, decisions, journeys and behavior models on top. The
risk is a second agent stack: its own ingestion service, store, graph and
evidence format.

## Decision

Agent behavioral intelligence is a bounded **intelligence** area. It has one
new package, `services/api/intelligence/agent_behavior/`, which holds
projectors and models that read Silver facts, resolved identities and graph
state, and that produce derived records and projection sections.

It owns no ingestion route, Bronze table, event bus, replay system, graph store
or identity resolver. Raw and normalized agent evidence stays in the existing
ingestion owners. Relationships stay in the graph through
`GraphMutationGateway.apply`. Read models are registered projection providers.

## Consequences

- A PR adding `AgentBehaviorIngestionService`, `AgentBehaviorDatabase`, an agent-specific graph store, or a microservice per behavioral feature is rejected.
- Provider- and runtime-specific branching stops at the Silver boundary.
