---
title: Naming truth
slug: source-of-truth/naming-truth
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Naming Truth

This document defines canonical product language across Aether, Kyber, Noesis, marketing sites, docs, SDKs, APIs, and internal architecture.

## Canonical Terms

| Canonical Term | Use |
|---|---|
| Signals | Observed or inferred indicators |
| Syndicates | Reusable entity groupings |
| Value | Financial, operational, conversion, or business impact |
| Profiles | Entity-level graph views |
| Journeys | Ordered paths of activity |
| Episodes | Bounded activity sequences |
| Communications | Messages, threads, campaigns, emails, notifications |
| Agents | Autonomous or assisted system actors |
| Lenses | Interpretive graph views |
| Risk | Compliance, anomaly, trust, security, or failure exposure |
| Snapshot | Point-in-time graph or surface view |

## Deprecated Terms

| Deprecated | Replacement |
|---|---|
| Audience Intelligence | Signals |
| Segments | Syndicates |
| Economic 360 | Value 360 |
| Business Value | Value |
| Audience Traits | Traits or Signals |
| Activity | Events or Signals |
| Graph Snapshot | Snapshot |

## Rule

Deprecated terms may only appear in:

`docs/archive/`

## Enforcement

`scripts/check_deprecated_language.py` runs in `make repo-doctor` and
`make docs-check`. It fails when a deprecated term appears in any tracked text
file outside `docs/archive/` and the two documents that define the terms
(this file and `docs/product/language-system/deprecated-language.md`).
`Segments` is checked only under `docs/` and `apps/`. Internal identifiers such
as `economic360` are contract IDs and are not display language.
