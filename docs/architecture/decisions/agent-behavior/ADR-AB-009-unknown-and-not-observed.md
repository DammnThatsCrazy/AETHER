---
title: "ADR-AB-009: Unknown and not-observed semantics are mandatory"
slug: decisions/agent-behavior/adr-ab-009-unknown-and-not-observed
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0-alpha.0
---

# ADR-AB-009: Unknown and not-observed semantics are mandatory

**Status:** Accepted for the Agent Behavioral Intelligence program (WO-001).
Applies to every later work order.

## Context

The program's state list is `declared`, `observed`, `resolved`, `derived`,
`inferred`, `unknown`, `not_observed` and `not_applicable`. The repository's
single vocabulary is `EpistemicStatus`, with 15 members. It has no `declared`
and no `not_observed`. A second vocabulary would break the parity tests and
the no-silent-escalation rule.

## Decision

`EpistemicStatus` stays the only status vocabulary. The program's states map
onto it:

| Program state | Representation |
|---|---|
| declared | `observed`, with field trust `SOURCE_ASSERTED` / `CLIENT_HINT` and `basis = "declared"` |
| observed | `observed` |
| resolved | `resolved` |
| derived | `derived` |
| inferred | `inferred` |
| unknown | `unknown` |
| not_observed | `unavailable`, with `basis = "not_observed"` and an observability reason |
| not_applicable | `not_applicable` |

Every behavior contract field that can be absent must say why: `unknown`
(could have been seen, was not), `unavailable` / not_observed (outside what
Aether can see), or `not_applicable`. Null without a status is invalid. If
`declared` or `not_observed` later needs to be a first-class member, that is a
change to `EpistemicStatus` and its TS twin together, with the parity test.

## Consequences

- WO-080 (ConfidenceEnvelope) and WO-081 (ObservabilityEnvelope) build on this mapping.
