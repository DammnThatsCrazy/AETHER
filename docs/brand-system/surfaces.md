---
title: Surfaces, borders, and focus
status: active
canonical_owner: frontend@aether
---

# Surfaces, borders, and focus

The visual system is warm/stone and border-led. Named recipes in
`packages/brand/src/surfaces/` and tokens in `packages/brand/src/tokens/` keep
surfaces consistent without a second palette.

| Use | Recipe/token |
| --- | --- |
| Application canvas | `surfaceRecipes.base` |
| Grouped content | `raised` |
| Menu/popover | `floating` / `popover` |
| Dialog or sheet | `modal` |
| Status context | `warning` / `critical`, with explicit state text |
| External provider | `provider`, neutral and label-first |

```ts
import { focusStyles, surfaceRecipes } from '@olympus/brand';

const card = surfaceRecipes.raised;
const keyboardFocus = focusStyles.keyboard;
```

- Prefer a border before adding a shadow; only floating/modal/tooltip layers
  receive their named elevation/shadow.
- Use `RADIUS`/`radiusUsage`, `borderTokens`, and `FOCUS_RING`; no arbitrary
  feature-local radius, glow, or focus removal.
- A selected or critical surface still needs an explicit text/ARIA state in
  addition to its color/border treatment.
