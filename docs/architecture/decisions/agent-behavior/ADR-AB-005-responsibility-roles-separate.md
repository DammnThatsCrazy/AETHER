---
title: "ADR-AB-005: Actor, authority, decision and execution roles are separate"
slug: decisions/agent-behavior/adr-ab-005-responsibility-roles-separate
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0-alpha.0
---

# ADR-AB-005: Actor, authority, decision and execution roles are separate

**Status:** Accepted for the Agent Behavioral Intelligence program (WO-001).
Applies to every later work order.

## Context

Today an agent fact carries one `agent_id`, a delegation carries a grantor
and grantee, and a beneficiary may come from `context.beneficiaryActorId`.
Collapsing these into "the actor" would mean that whoever executed an action
is assumed to have decided it, authorised it, funded it and benefited from it.

## Decision

The program keeps nine roles separately resolvable: objective owner,
initiating actor, instruction source, decision actor, execution actor,
authorization actor, funding actor, beneficiary actor and influencing actor.
Each role is filled only from evidence and carries its own epistemic status.
An unknown role stays `unknown`. It is not copied from another role.

Fleet attribution keeps its current rule: delegation proves that authority was
granted, not who acted or intended. A person link is always shown with the
competing explanation that the principal did not act.

## Consequences

- WO-022 exposes the roles. Value (WO-092) and Risk (WO-093) read them; neither infers them.
