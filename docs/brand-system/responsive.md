---
title: Responsive behavior
slug: architecture/brand-system/responsive
section: architecture
visibility: I
audience: [dev-junior, dev-senior, architect]
status: stable
since_version: "8.12.0"
canonical_owner: frontend@aether
---

# Responsive behavior

Responsive brand rules are in `packages/brand/src/responsive/`. They define
lockup reduction and density, not a replacement application layout system.

```ts
import { densityRules, lockupVariantFor, RESPONSIVE_BREAKPOINT } from '@olympus/brand';

const variant = lockupVariantFor('aether', availableInlineWidth);
const compactRow = densityRules.compact.rowMinHeight;
```

- Choose the largest lockup variant that fits its available inline width; use
  mark-only only when an accessible product name remains.
- Common coordination breakpoints are 480/720/980/1180px (`compact` through
  `wide`); an app owns its layout and sidebars.
- On narrow surfaces, stack secondary detail before hiding status/remediation or
  the provider label. Provider identity never replaces its text label.
- Comfortable/narrow interactive controls remain 44px; compact keyboard-only
  density may use 32px as defined by the token.
- Test shell, table/card, empty/error, and keyboard focus behavior at narrow and
  desktop widths whenever changing a route family.
