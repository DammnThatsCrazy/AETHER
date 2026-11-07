---
title: "ADR-AB-003: DecisionEnvelope is evidence-qualified and immutable after closure"
slug: decisions/agent-behavior/adr-ab-003-decision-envelope-immutable
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0-alpha.0
---

# ADR-AB-003: DecisionEnvelope is evidence-qualified and immutable after closure

**Status:** Accepted for the Agent Behavioral Intelligence program (WO-001).
Applies to every later work order.

## Context

`services/api/intelligence/intelligence/decision_models.py` already has a
`DecisionRecord`. It is Aether's own decision about a recommendation it made.
An observed agent's decision is a different thing: Aether reconstructs it from
evidence it did not produce, and the evidence may be partial.

## Decision

`DecisionEnvelope` describes a decision made by an **observed actor**. It is not
`DecisionRecord` and does not extend it. A DecisionEnvelope is open while
evidence for that decision is still arriving. It closes when the decision's
outcome, abandonment or timeout is observed. After closure the envelope is
immutable except for append-only references: late evidence, a review, a
supersession. A correction produces a new envelope version that supersedes the
old one.

Every field carries an epistemic status. The envelope cites the source events
for its objective, candidates, constraints, authority check, selected action
and outcome. A missing part is recorded as missing, not left out.

## Consequences

- No Value or Risk calculation is stored inside a DecisionEnvelope. Those domains consume it.
- Reviewers reject any code that mutates a closed envelope.
