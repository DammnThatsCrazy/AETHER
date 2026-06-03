---
title: Demo App UX
slug: operations/demo-app-ux
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Demo App UX

UX notes and design-debt for the Demo App, for handoff to a production designer.

## Current

- Single-page narrative laid out as a numbered value loop (steps 1–8) using
  `@aether/ui` `Card`/`Badge`, dark theme, on the shared tokens.
- Header with tenant + environment badge and a **Tenant (Aether) / Operator
  (Kyber)** view toggle.
- An ingestion simulator (SDK / webhook buttons) backed by MSW.
- Empty/loading states are not needed in the closed demo (fixtures are always
  present and synchronous); the ingestion simulator surfaces an error string if a
  mocked request fails.

## Design debt / handoff notes

- Replace the numbered-card layout with a guided, animated flow (step transitions)
  for a stronger live-demo arc.
- Add a graph visualization for the Profile360 step (reuse the entity-graph
  component from Kyber/Aether).
- Add per-step "what the tenant sees" vs "what Olympus sees" side-by-side framing.
- Add a reset control in the UI (currently reload-to-reset).
- Accessibility: ensure the view-toggle buttons expose `aria-pressed`; verify
  color contrast on badges in light mode.

See [Demo App](DEMO-APP.md) and [Frontend QA](FRONTEND-QA.md) when available.
