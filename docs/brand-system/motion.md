---
title: Motion
slug: architecture/brand-system/motion
section: architecture
visibility: I
audience: [dev-junior, dev-senior, architect]
status: stable
since_version: "8.12.0"
canonical_owner: frontend@aether
---

# Motion

Motion is purposeful feedback, not decoration or evidence. Use named recipes
from `packages/brand/src/motion/`.

```ts
import { motionDuration, motionRecipes, transitionFor } from '@olympus/brand';

const cssTransition = transitionFor(motionRecipes.menu);
const duration = motionDuration(prefersReducedMotion, 180);
```

| Purpose | Recipe | Normal duration |
| --- | --- | --- |
| Hover/focus/press | `hover`, `focus`, `press` | 120ms |
| Menus/tabs | `menu`, `dropdown`, `tab` | 180ms |
| Sheets/modals/notifications | `sheet`, `modal`, `notification` | 240ms |
| Loading/graph layout | `loading`, `graphLayout` | 320ms |

- Honor `REDUCED_MOTION`: reduce duration to 1ms, preserve focus/loading label/
  progress value, and avoid continuous pulse, autoplay, and decorative movement.
- Never use animation to hide a slow, partial, stale, or failed state.
- Use a new recipe only when a distinct user-facing purpose cannot use an
  existing one; do not introduce a route-local easing scale.
