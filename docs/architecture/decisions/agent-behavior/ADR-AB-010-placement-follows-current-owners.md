---
title: "ADR-AB-010: Schema paths follow current post-#734 ownership"
slug: decisions/agent-behavior/adr-ab-010-placement-follows-current-owners
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0-alpha.0
---

# ADR-AB-010: Schema paths follow current post-#734 ownership

**Status:** Accepted for the Agent Behavioral Intelligence program (WO-001).
Applies to every later work order.

## Context

The work orders deliberately do not hard-code paths. WO-000 records the
owners in the [current architecture map](../../agent-behavior/00-current-architecture-map.md).

## Decision

Every work order places code with the owner named in the map's §2 and §9. A PR
that introduces a parallel owner for a concern that already has one must add an
ADR explaining why the existing owner cannot hold it. The map is updated in the
same PR when ownership changes. Event types follow the registry's snake_case
convention. The work orders' dotted names are design vocabulary only.

## Consequences

- Trust (WO-094) has no owner today and needs such an ADR.
- The anti-patterns in §7 of the work orders are review rejections.
