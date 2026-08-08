---
title: Typography and spacing
status: active
canonical_owner: frontend@aether
---

# Typography and spacing

Use the metadata in `packages/brand/src/tokens/typography.ts` and the existing
shared CSS variables in `frontend/shared/src/styles/tokens.css`.

| Use | Token rule |
| --- | --- |
| Product copy and headings | Geist / `FONT_FAMILY.sans` |
| IDs, receipts, structured values, code | Geist Mono / `FONT_FAMILY.mono` |
| Type scale | `TYPOGRAPHY` role token; do not define a route-local scale |
| Composition gaps | `BRAND_SPACE` and `brandSpacingGuidance` |
| Lockup clear space | `brandSpacingGuidance.lockupClearSpace` |

```ts
import { BRAND_SPACE, TYPOGRAPHY } from '@olympus/brand';

const label = TYPOGRAPHY.label;
const iconLabelGap = BRAND_SPACE[2];
```

- Use mono for data hierarchy, not ordinary paragraphs.
- Do not introduce Inter, JetBrains Mono, or a marketing font as a product base
  typeface without a separately approved typography change.
