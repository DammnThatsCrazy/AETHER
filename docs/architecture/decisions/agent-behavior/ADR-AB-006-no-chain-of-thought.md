---
title: "ADR-AB-006: Chain-of-thought is neither required nor treated as evidence"
slug: decisions/agent-behavior/adr-ab-006-no-chain-of-thought
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0-alpha.0
---

# ADR-AB-006: Chain-of-thought is neither required nor treated as evidence

**Status:** Accepted for the Agent Behavioral Intelligence program (WO-001).
Applies to every later work order.

## Context

Some runtimes expose model reasoning text. It is unavailable for most agents.
It is not a faithful record of what drove the action, and it can be
manipulated by injected content.

## Decision

Aether reconstructs behavior from observable evidence: instructions, context
received, candidate sets, tool calls and results, API responses, permissions,
policy decisions, prices, latency, failures, actions and outcomes. No contract
requires reasoning text. If a source sends reasoning text, it is treated as
source-asserted content. It does not support a claim on its own and cannot
raise the epistemic status of one. It follows the payload's privacy and
retention class.

## Consequences

- No schema field named or meaning "reasoning" or "thought" is required.
- A behavioral claim whose only support is reasoning text fails review.
