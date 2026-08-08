---
title: Accessibility
slug: architecture/brand-system/accessibility
section: architecture
visibility: I
audience: [dev-senior, architect, ops]
status: stable
since_version: "8.12.0"
canonical_owner: frontend@aether
---

# Accessibility

The renderer contract is semantic first. Visual identity must not be the only
way to understand a route, provider, state, or action.

- A meaningful icon-only control needs an accessible label. Decorative icons
  and marks use `aria-hidden` only when adjacent text supplies the equivalent.
- Keep named icons, visible focus, logical keyboard order, and 44px pointer
  targets for primary interaction.
- Provider identity, status, severity, confidence, freshness, and provenance
  need independent text/non-color cues. Add timestamps for freshness where data
  permits.
- A lockup has one accessible name; internal composed images/wordmark are
  decorative to avoid duplicate announcement.
- Honor `prefers-reduced-motion` and retain loading/error/progress text after
  animation is reduced.
- Graphs/charts need labels, shapes, patterns, values, or programmatic state;
  color and raw glyphs alone are insufficient.

```tsx
// Visible text already names Graph.
<NavigationIcon destination="aether-graph" decorative />

// No adjacent label: this control keeps a name.
<Icon name="refresh-cw" label="Refresh connector status" />
```
