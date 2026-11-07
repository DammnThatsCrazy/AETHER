---
title: "ADR-AB-008: Behavioral inference never writes back into canonical facts"
slug: decisions/agent-behavior/adr-ab-008-inference-never-writes-facts
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0-alpha.0
---

# ADR-AB-008: Behavioral inference never writes back into canonical facts

**Status:** Accepted for the Agent Behavioral Intelligence program (WO-001).
Applies to every later work order.

## Context

The runtime authority map ranks layers L0 (raw evidence) to L8 (user-confirmed
truth). Behavior inference sits at L5/L6. If it wrote to L1–L3, an inference
would become indistinguishable from an observation, and replay would compound
it.

## Decision

Behavior projectors read L0–L4 and write only derived records. They never
modify Bronze, Silver, identity decisions or observed graph edges. When an
inference must be visible in the graph (for example an influence edge), it is
written as a separate `MutationIntent` whose edge is marked `inferred`, with
evidence references and confidence. It never upgrades an observed edge. Status
upgrades follow the no-silent-escalation rule in
`shared/contracts_models/epistemic.py`.

## Consequences

- Fleet hypotheses already follow this rule. The builder never confirms; only a reviewer can.
