---
title: Olympus Labs / Aether / Kyber Brand System
status: active
canonical_owner: frontend@aether
---

# Olympus Labs / Aether / Kyber Brand System

This directory is the operational guide for the repository brand system. It
documents how to use the source of truth that is already implemented; it is not
a second asset library or a request to redraw product identity.

## Start here

- [Principles](./principles.md) defines the product hierarchy, visual language,
  semantic boundaries, and do/don't rules.
- [Architecture](./architecture.md) maps the public APIs, package ownership,
  responsive rules, accessibility, and documentation/marketing constraints.
- [Migration](./migration.md) is the safe adoption checklist for a route,
  provider, entity, or icon migration.
- [Final audit](./final-audit.md) is a living acceptance report. It records
  verified facts and open blockers only.
- [Historical inventory](./audit.md) records the pre-migration repository
  findings. It is useful context, but it is not the current acceptance status.

## Topic reference

| Topic | Operational reference |
| --- | --- |
| Product hierarchy | [Olympus](./olympus.md), [Aether](./aether.md), [Kyber](./kyber.md) |
| Foundations | [Typography](./typography.md), [iconography](./iconography.md), [surfaces](./surfaces.md), [motion](./motion.md), [responsive behavior](./responsive.md) |
| Truthful product semantics | [Providers](./providers.md), [entities](./entities.md), [status and severity](./status-severity.md), [provenance and confidence](./provenance-confidence.md) |
| Inclusive and external communication | [Accessibility](./accessibility.md), [marketing](./marketing.md), [documentation](./documentation.md), [do and don't](./do-dont.md) |
| Adoption | [Migration](./migration.md) |

## Canonical ownership

| Need | Canonical source | Consumer boundary |
| --- | --- | --- |
| Brand manifests and reviewed Aether/Olympus geometry | `packages/brand/src/identity/` | Read manifest data or render through `@aether/ui`; never copy/recreate SVG paths. |
| Provider IDs, aliases, categories, attribution, fallback policy | `packages/brand/src/providers/` | Runtime contracts remain authoritative for operational IDs and visibility. |
| Navigation, action, entity, status, severity, freshness, confidence, provenance taxonomies | `packages/brand/src/iconography/` | Use the typed UI renderers for React; do not reintroduce ASCII/Unicode glyph systems. |
| Typography, spacing, icon size, focus, borders, radius, elevation and shadows | `packages/brand/src/tokens/` | Existing shared CSS variables remain the visual CSS layer. |
| Motion, responsive and surface rules | `packages/brand/src/{motion,responsive,surfaces}/` | Apply by semantic purpose, not by copying literal transition/shadow values. |
| Accessible React rendering | `frontend/shared/src/components/` (`@aether/ui`) | Product apps and a compatible docs surface consume this layer. |

`@olympus/brand` is deliberately framework-free. It exports metadata and asset
references, contains no React, and never supplies a remote provider logo.
`@aether/ui` is the only React/SVG rendering adapter for this system.

## Normal React use

Use `@aether/ui` in product UI. It applies the manifest, the icon renderer,
and the accessibility defaults together.

```tsx
import {
  AetherLockup,
  NavigationIcon,
  ProviderSourceChip,
  StatusIcon,
} from '@aether/ui';

export function ConnectorHeader() {
  return (
    <header>
      <AetherLockup variant="responsive" label="Aether" size={28} />
      <NavigationIcon destination="aether-integrations" decorative />
      <ProviderSourceChip provider="generic_webhook" />
      <StatusIcon status="credential_required" />
    </header>
  );
}
```

Pass `decorative` only when adjacent visible text already supplies the same
meaning. An icon-only action or collapsed navigation item must keep its
accessible name. `ProviderSourceChip` and `StatusIcon` are intentionally
label-first defaults.

For a non-React consumer, resolve metadata rather than duplicating it:

```ts
import { lockupVariantFor, resolveProvider } from '@olympus/brand';

const lockup = lockupVariantFor('kyber', availableInlineWidth);
const provider = resolveProvider(serverProviderId);
// provider.known is false for an unregistered ID; identity remains a safe fallback.
```

## Add a provider safely

1. Keep the source/runtime ID in its owning contract. For tenant integrations,
   this is normally `packages/shared/contracts/integration-consent-registry.json`;
   payment IDs live in `packages/shared/payment-rails.ts`. Do not rename an API
   value to make it visually friendlier.
2. Add the exact ID and any display-only aliases to
   `packages/brand/src/providers/registry.ts`, with the correct category and
   attribution guidance. Add coverage in `packages/brand/src/brand.test.ts`.
3. Until legal review approves a committed local mark, leave `mark.kind` as
   `fallback`. The renderer uses neutral initials; it must not fetch a URL,
   recreate a third-party logo, or treat a provider color as a logo.
4. Render `ProviderMark`, `ProviderCard`, or `ProviderSourceChip` from
   `@aether/ui`. Keep provider identity separate from lifecycle, severity,
   confidence, freshness, and remediation controls.

Technical integrations such as `generic_webhook`, `webhook`, and
`outbound_activation` are neutral system identities. They are not a license to
invent a third-party trademark treatment.

## Add an entity or navigation destination

For an entity, add a semantic identity and aliases in
`packages/brand/src/iconography/entities.ts`, retain the product's existing
entity/graph contract, and render `EntityIcon` or `EntityAvatar`. A provider
may appear as a separate source overlay; it is not the entity's base identity.

For a shell destination, add a stable descriptor to
`packages/brand/src/iconography/navigation.ts`, then use `NavigationIcon` in
the product shell. The route and its capability/permission rule stay in the
application router and shell. A nav icon must never be used to infer or grant
authorization.

## Before requesting review

- Verify the affected source of truth and its unit test.
- Keep visible state text and machine-readable state attributes intact.
- Test both the normal and narrow layout; choose a smaller canonical lockup or
  compact density before hiding a label that carries meaning.
- Run the affected workspace checks. The full integration gate remains
  `make docs-fix` followed by `make ci-check` after all slices land.
