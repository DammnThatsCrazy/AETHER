---
title: "ADR-AB-011: Agent trust and reputation live under Risk, kept apart"
slug: decisions/agent-behavior/adr-ab-011-trust-under-risk
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0-alpha.0
---

# ADR-AB-011: Agent trust and reputation live under Risk, kept apart

**Status:** Accepted for the Agent Behavioral Intelligence program (WO-094).

## Context

WO-094 needs a Trust owner. No code owns trust today
([current architecture map](../../agent-behavior/00-current-architecture-map.md)),
and the product naming truth already places trust exposure under Risk. Risk360
has a registered `reputation` dimension.

## Decision

Agent trust and agent reputation are produced in
`services/api/intelligence/risk360/agent_trust.py`, not in a new Trust package.

- **Trust** is Aether's own evidence-qualified view of reliability per
  capability: competency, authority compliance and failure recovery. It is
  derived from behavior facts and uncalibrated.
- **Reputation** is what third parties report (ratings, reviews, listings). It
  is source-asserted.

The two are never blended into one score. Neither is a fraud finding or an
authorization decision.

## Consequences

- No new owner is created. A future Trust surface reads these two profiles.
- Risk signals derived from behavior use registered Risk360 dimensions and
  carry no calibrated score.
