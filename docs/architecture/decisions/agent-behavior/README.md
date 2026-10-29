---
title: Agent Behavioral Intelligence — ADR index
slug: decisions/agent-behavior
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0-alpha.0
---

# Agent Behavioral Intelligence — ADRs

These are the WO-001 decisions. Architecture review uses them to reject PRs that
break the program's invariants. Owners are listed in the
[current architecture map](../../agent-behavior/00-current-architecture-map.md).

| ADR | Decision |
|---|---|
| [ADR-AB-001](ADR-AB-001-bounded-intelligence-domain.md) | Agent behavior is a bounded intelligence domain, not a platform |
| [ADR-AB-002](ADR-AB-002-behavior-model-is-derived.md) | AgentBehaviorModel is derived and rebuildable |
| [ADR-AB-003](ADR-AB-003-decision-envelope-immutable.md) | DecisionEnvelope is evidence-qualified and immutable after closure |
| [ADR-AB-004](ADR-AB-004-opportunity-envelope.md) | OpportunityEnvelope separates availability from preference |
| [ADR-AB-005](ADR-AB-005-responsibility-roles-separate.md) | Actor, authority, decision and execution roles are separate |
| [ADR-AB-006](ADR-AB-006-no-chain-of-thought.md) | Chain-of-thought is neither required nor treated as evidence |
| [ADR-AB-007](ADR-AB-007-internal-vs-observed-agents.md) | Internal Aether agents are separate from observed agents |
| [ADR-AB-008](ADR-AB-008-inference-never-writes-facts.md) | Behavioral inference never writes back into canonical facts |
| [ADR-AB-009](ADR-AB-009-unknown-and-not-observed.md) | Unknown and not-observed semantics are mandatory |
| [ADR-AB-010](ADR-AB-010-placement-follows-current-owners.md) | Schema paths follow current post-#734 ownership |
