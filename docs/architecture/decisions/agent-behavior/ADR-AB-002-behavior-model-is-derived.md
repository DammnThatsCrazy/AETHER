---
title: "ADR-AB-002: AgentBehaviorModel is derived and rebuildable"
slug: decisions/agent-behavior/adr-ab-002-behavior-model-is-derived
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0-alpha.0
---

# ADR-AB-002: AgentBehaviorModel is derived and rebuildable

**Status:** Accepted for the Agent Behavioral Intelligence program (WO-001).
Applies to every later work order.

## Context

A behavior model summarises evidence. If the model were authoritative,
correcting an identity merge, a late event or a policy change would leave the
model and its evidence disagreeing, with no way to recompute.

## Decision

`AgentBehaviorModel`, behavior features, snapshots and drift are **derived
state**. Each record carries the input set (tenant, source-event watermark,
identity version), the model or feature version, and its computation time.
Recomputing from the same inputs and versions gives the same output. A new
version is produced by recomputation (`vN → recompute → vN+1`), never by
editing in place. Identity restatement and replay
(`replay/projections/projection_restatement_orchestrator.py`) trigger
recomputation the same way they do for other projections.

## Consequences

- Behavior stores are rebuildable caches. Deleting one loses no evidence.
- Every behavior projector has a determinism / replay test (WO-171).
- Erasure deletes the evidence and recomputes. It never edits a model to "forget".
