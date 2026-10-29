---
title: "ADR-AB-004: OpportunityEnvelope separates availability from preference"
slug: decisions/agent-behavior/adr-ab-004-opportunity-envelope
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0-alpha.0
---

# ADR-AB-004: OpportunityEnvelope separates availability from preference

**Status:** Accepted for the Agent Behavioral Intelligence program (WO-001).
Applies to every later work order.

## Context

"The agent did not buy X" can mean it did not prefer X, could not see X,
was not allowed to buy X, or had no budget. If behavior features are computed
only from selected actions, the first reading wins by default and preference
inference is wrong.

## Decision

Each decision context records an `OpportunityEnvelope`: which candidates or
actions were observably **available** to the actor, under which constraints,
authority and resources, and how complete that observation is. Preference may
only be inferred over candidates the envelope shows were available and
permitted. A non-selection outside that set is recorded as `not_applicable` or
`unknown`, never as a negative preference.

## Consequences

- WO-045 (Opportunity), WO-046 (non-action) and WO-083 (preference) depend on this.
- GS-C (constrained non-action) is the guarding fixture.
