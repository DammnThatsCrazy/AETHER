---
title: Kyber identity
slug: kyber/brand-system
section: kyber
visibility: I
audience: [dev-senior, architect, ops]
status: stable
since_version: "8.12.0"
canonical_owner: frontend@aether
---

# Kyber identity

Kyber is Aether's operator/control-plane product. It shares the Olympus/Aether
lineage and can add an operator descriptor; it must not become a third palette
or independent corporate mark.

```tsx
import { KyberLockup } from '@aether/ui';

<KyberLockup variant="responsive" label="Kyber" size={28} />
```

- Follow `packages/brand/src/identity/kyber/manifest.ts`.
- Select `full` at 132px+, `compact` at 84px+, and `mark` only in collapsed
  navigation with an accessible Kyber name.
- Preserve Kyber's existing operator authority, environment, and forbidden
  states; replacing a glyph must never alter a gate or direct-route behavior.
- Do not retain a separate cold base palette, local lockup, or raw nav glyph
  system as an identity substitute.
