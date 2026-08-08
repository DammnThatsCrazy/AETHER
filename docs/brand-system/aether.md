---
title: Aether identity
status: active
canonical_owner: frontend@aether
---

# Aether identity

Aether is the customer product. Its five-layer mark, warm/stone surfaces, and
Geist-led application language are the default visual system.

```tsx
import { AetherLockup } from '@aether/ui';

<AetherLockup variant="responsive" label="Aether" size={28} />
```

- Use the Aether manifest and package-owned marks; Aether app builds serve the
  same reviewed files from `packages/brand/src/identity/marks/`.
- Select `full` at 112px+, `compact` at 72px+, and `mark` in collapsed/mobile
  navigation. Keep an accessible Aether label for a mark-only shell.
- Do not create a second wordmark or duplicate the layer paths in JSX.
- Keep customer capability, entitlement, and lifecycle language truthful; the
  Aether mark is never a live/healthy status signal.
