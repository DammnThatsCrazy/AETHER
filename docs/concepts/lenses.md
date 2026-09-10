---
title: Lenses
slug: concepts/lenses
section: concepts
visibility: P
audience: [dev-senior, architect]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
toc_depth: 3
---

# Lenses

A lens is a composable viewing frame the platform applies over canonical
Aether truth — a declared, typed way of asking "show me this subject, but
foreground a particular dimension of it." A lens never owns truth and never
adds a write path; it only changes how an existing 360 view is projected and
rendered.

## Base lens and overlays

Every lens set names exactly one **base** lens — `standard`, the identity
element of composition, which is the plain, unadorned projection over
identity, relationship facts, graph, evidence, and temporal state — followed
by zero or more **overlay** lenses that compose additively on top of it.
Composition is order-stable: applying `temporal` then `campaign` produces
the same result as applying `campaign` then `temporal`.

Overlays available today span a wide range of domains, including:

| Lens | Foregrounds |
|---|---|
| `temporal` | State over time, transitions, bitemporal history |
| `geographic` | Location, region, movement |
| `population` | Cohort membership and comparison baselines |
| `relationship` | The connection graph — edges, hop structure |
| `journey` | Journey stages and step structure ([Journeys](journeys.md)) |
| `campaign` / `attribution` | Campaign touchpoints and attribution weight |
| `economic` / `payment` | Payment, revenue, and economic activity |
| `agent` / `execution` | Agent task lifecycle and execution traces |
| `risk` / `fraud` / `trust` | Risk scoring and trust signals |
| `consent` / `policy` | Consent state and policy evaluation |
| `wallet` | On-chain wallet activity |
| `evidence` / `data_quality` | Provenance and data-quality metadata |

Not every lens applies to every kind of subject — a `LensDescriptor`
declares which subject kinds (`entity`, `relationship`, `campaign`,
`episode`, `population`, `source`, `agent`, …) and temporal modes
(`window`, `as_of`, `compare`, `relative`) it supports, and an overlay must
declare the same base lens as the rest of the set it's composed into.

## Where lenses show up

The **Explore** page in the dashboard (`/explore`) surfaces the registered
lens dock for whatever graph object is currently focused, showing each
lens's availability honestly — `available`, `not entitled`, `no access`, or
`not ready` — rather than hiding lenses your plan doesn't include. A lens
that isn't available to your plan or role stays visible with its real
registry state, so you always know what exists even before you've bought
it.

## Custom and filtered views

Beyond the registered lens vocabulary, the exploration surface supports ad
hoc filters (a population filter plus arbitrary filter builder clauses)
layered on top of whatever lens set is active — so a lens gives you the
*dimension* you're viewing through, and filters narrow *which* subjects
appear in that view.

## Next steps

- [Journeys](journeys.md) — the `journey` overlay lens in more depth.
- [Profiles](profiles.md) — the 360 view lenses project over.
