---
title: UX Handoff Notes
slug: operations/ux-handoff-notes
section: operations
visibility: I
audience: [dev-senior, exec]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# UX Handoff Notes

Notes for a production designer picking up the three apps. The current frontends
are **functional and pre-production (~90%)**: routed, wired, state-complete, and
consistent on `@aether/ui` — but intentionally utilitarian, not final design.

## Design system

- Shared component library `@aether/ui` (Card, Badge, DataTable, EmptyState,
  LoadingState, ErrorState, Tabs, Modal, UsageBar, …) on a dark token theme.
- Aether/Kyber/Demo all consume the same preset; extend the library, don't fork.

## Design debt (prioritized)

1. **Visual hierarchy**: dashboards are dense card grids; add hierarchy,
   summaries, and progressive disclosure (esp. Kyber mission, reliability,
   intelligence quality).
2. **Graph visualization**: Profile360 / entity graph deserve a first-class
   visual (a cytoscape view exists in Aether — generalize it).
3. **Demo App**: convert the numbered value-loop into a guided, animated flow
   with side-by-side "tenant vs operator" framing — see [Demo App UX](DEMO-APP-UX.md).
4. **Responsive**: layouts are desktop-first; define tablet/mobile breakpoints.
5. **Accessibility**: audit focus order, `aria-*` on custom controls (view
   toggles, tabs), and color contrast (badges in light mode).
6. **Copy**: tighten microcopy; standardize empty-state guidance.
7. **Navigation**: Kyber's flat nav list is long — consider grouping
   (operate / grow / govern).

## Constraints to preserve

Tenant isolation in the UI (Aether never shows Kyber internals; Kyber aggregate
views never show raw tenant-private payloads), every page's empty/loading/error
states, and local-mocked mode. See [Frontend QA](FRONTEND-QA.md).
