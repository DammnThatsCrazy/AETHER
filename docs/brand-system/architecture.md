---
title: Brand-system architecture and accessibility
slug: architecture/brand-system/architecture
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: stable
since_version: "8.12.0"
canonical_owner: frontend@aether
---

# Brand-system architecture and accessibility

## Dependency direction

```text
packages/shared and backend contracts  -> exact IDs, authority, capability truth
@olympus/brand                         -> manifests, taxonomy, token metadata
@aether/ui (frontend/shared)           -> React/SVG renderers and a11y behavior
apps, docs, demo, mobile                -> render or consume the canonical source
```

`@olympus/brand` may describe an existing identity or provider, but it does
not own authorization, data truth, route visibility, or a React component.
`@aether/ui` is the rendering boundary. Product-specific application code owns
route behavior and capability enforcement.

For the Aether-specific context, ownership, dependency sequence, and consumer
acceptance matrix, see [Aether context and consumer matrix](./aether-consumer-matrix.md).

Reviewed Aether/Olympus asset geometry lives once in
`packages/brand/src/identity/marks/`. The Aether and Kyber Vite public
directories point there, so a manifest `publicPath` resolves without duplicating
the SVGs in application public folders.

## Public API map

| Need | Data API (`@olympus/brand`) | React API (`@aether/ui`) |
| --- | --- | --- |
| Product identity | `aetherManifest`, `kyberManifest`, `olympusManifest`, `lockupVariantFor` | `AetherLockup`, `KyberLockup`, `OlympusLockup`, `BrandMark` |
| Provider presentation | `resolveProvider`, `providerAttribution`, `providerPlacementRules` | `ProviderMark`, `ProviderCard`, `ProviderSourceChip` |
| Navigation/action | `navigationDestinations`, `actionIcons` | `NavigationIcon`, `Icon` |
| Entity identity | `resolveEntityIdentity`, `entityIdentities` | `EntityIcon`, `EntityAvatar` |
| State and evidence | `statusIcons`, `severityIcons`, `freshnessIcons`, `confidenceIcons`, `provenanceIcons` | `StatusIcon`, `SeverityIcon`, `FreshnessIcon`, `ConfidenceIndicator`, `ProvenanceIcon` |
| Surfaces and interaction | `surfaceRecipes`, `focusStyles`, `motionRecipes`, `motionDuration` | `Surface`, `ElevatedSurface`, existing controls |

Examples should import through the two package barrels. Do not import a
feature's local implementation as a substitute for public brand API.

## Responsive and motion rules

Use `lockupVariantFor(brand, availableWidth)` when a non-DOM calculation is
available; otherwise use a responsive product lockup. Lockup policy uses inline
space, not a guessed device class.

The common breakpoints are `compact: 480`, `tablet: 720`, `desktop: 980`, and
`wide: 1180` in `packages/brand/src/responsive/logo.ts`. They guide layout
coordination; an app still owns its actual responsive layout.

In narrow layouts:

1. Keep an accessible provider label beside its mark.
2. Stack secondary detail before hiding status, remediation, or source text.
3. Use compact density/mark sizing before removing identity.
4. Keep primary interactive targets at 44px even when the visual icon is 16–24px.

Use a named recipe from `packages/brand/src/motion/recipes.ts`. The duration
scale is 0/120/180/240/320ms (`instant` through `complex`). Under
`prefers-reduced-motion: reduce`, use `motionDuration` or the renderer's
reduced-motion handling: animations reduce to 1ms, preserve focus/loading
labels/progress values, and avoid continuous pulse or decorative transforms.

## Accessibility baseline

- Decorative icons and marks have `aria-hidden`; meaningful icon-only controls
  retain a label or an accessible name.
- Provider marks are identifiers, not status indicators. Keep their visible
  label in dense lists and their required attribution nearby.
- State, severity, freshness, confidence, and provenance retain textual
  labels. A timestamp should accompany a freshness state whenever available.
- Use named focus tokens and `:focus-visible`; no control may lose its visible
  keyboard focus because it uses an icon.
- Graphs, charts, and state surfaces need non-color cues: labels, shapes,
  patterns, text values, or programmatic state.
- Do not announce a logo twice: a lockup is named once; its composed internal
  image and wordmark are decorative.

## Documentation and marketing use

Documentation should explain the product in the same hierarchy as the apps:
Olympus Labs attribution where appropriate, Aether for customer product
material, and Kyber for operator material. Use a manifest lockup and shared
tokens/components where the host supports `@aether/ui`; never attach an
external logo URL to a doc page.

The current `frontend/docs` SPA does **not** declare a dependency on
`@aether/ui` and uses local inline blue/gray styling. This slice intentionally
does not add a second docs theme, a copied CSS token set, or a cross-workspace
dependency. A future, separately-owned docs UI migration should first add the
existing shared package through the normal workspace dependency flow, import
the shared token CSS once, render a manifest lockup, and verify docs typecheck,
keyboard focus, contrast, and narrow-sidebar behavior.

Marketing and documentation copy may name providers in prose, but must not
claim a provider is enabled, live, integrated, approved, or customer-available
solely because it appears in the registry or an example.
