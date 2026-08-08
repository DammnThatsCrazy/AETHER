---
title: Olympus Labs identity
slug: architecture/brand-system/olympus
section: architecture
visibility: I
audience: [architect, exec, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: frontend@aether
---

# Olympus Labs identity

Olympus Labs is the corporate parent. Use it for corporate attribution, legal,
documentation, marketing, and the approved combined lockup—not routine product
navigation.

```tsx
import { OlympusLockup } from '@aether/ui';

<OlympusLockup variant="full" label="Olympus Labs" size={28} />
```

- Use the manifest in `packages/brand/src/identity/olympus/manifest.ts`.
- Use `full` for headers at 144px+ of inline space; reduce to `mark` only when
  another accessible Olympus Labs label remains.
- Keep Olympus attribution distinct from Aether or Kyber product labels.
- Never redraw the Arch, modify SVG geometry, or create a local corporate logo.
