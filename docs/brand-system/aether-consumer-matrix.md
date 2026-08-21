---
title: Aether context, ownership, and consumer matrix
slug: architecture/brand-system/aether-consumers
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: stable
since_version: "8.12.0"
canonical_owner: frontend@aether
---

# Aether context, ownership, and consumer matrix

## Context and why

Aether is the customer-facing intelligence graph product. Its interface must
make tenant-scoped identity, source, freshness, confidence, capability state,
and remediation understandable without changing the underlying route,
authority, or data-truth contracts.

The brand system exists so those concepts are expressed once: official product
identity is not redrawn in an app, provider identity is not mistaken for
health, and a visual migration cannot silently change a capability gate.

## Value

- **Customer clarity:** named, accessible identity and state cues make the
  source and operating condition of a value understandable in dense screens.
- **Product consistency:** Aether, Kyber, docs, demo, and mobile can consume
  one manifest/taxonomy instead of maintaining competing assets and glyph maps.
- **Safer change:** the framework-free package and React adapter make visual
  ownership explicit while keeping runtime contracts, authorization, and routes
  with their existing owners.

## Ownership matrix

| Layer | Owner | Owns | Does not own |
| --- | --- | --- | --- |
| `@olympus/brand` | Brand architecture | Identity manifests, provider metadata/fallbacks, semantic taxonomies, token/motion/surface/responsive metadata | React rendering, routing, permissions, provider activation, runtime truth |
| `@aether/ui` | Shared UI | Accessible React/SVG renderers and shared visual primitives | Product feature behavior or backend contracts |
| `frontend/aether` | Aether product | Customer shell, routes, feature composition, capability-aware presentation | Duplicated logo/provider geometry or a second token system |
| `frontend/kyber` | Kyber product | Operator shell and feature composition | Customer entitlement semantics or a competing corporate identity |
| `frontend/docs` | Documentation | Accurate product explanation and, when migrated, a canonical consumer treatment | A copied theme, remote assets, or operational claims unsupported by contracts |
| QA/enforcement | QA / platform | Focused a11y, responsive, visual, and drift enforcement | Redefining product authority or provider state |

## Aether consumer matrix

| Consumer | Canonical consumption | Preserve | Next acceptance evidence |
| --- | --- | --- | --- |
| Customer shell | `AetherLockup`, `NavigationIcon`, named action icons | Exact paths, labels, `resolveDestinationAvailability`, direct-route behavior | Shell route/capability tests plus desktop/narrow visual and focus coverage |
| Connectors and payment rails | `ProviderMark`/`ProviderCard`/`ProviderSourceChip` plus separate state UI | Runtime provider ID, health/reconciliation wording, entitlement and remediation | Provider fallback, status separation, and narrow-row tests |
| Entity/profile/graph surfaces | `EntityIcon`/`EntityAvatar`, provenance/confidence/freshness indicators | Entity type, graph data, source overlay, timestamps, profile navigation | Non-color semantic and graph/profile regression coverage |
| Shared Aether feature states | `StatusIcon`, `SeverityIcon`, surface and motion metadata | Capability labels, `data-*` state markers, loading/error truth | Keyboard, reduced-motion, and state-matrix tests |
| Kyber and other product consumers | Same source package through `@aether/ui` | Operator authority/env gates and product-specific route behavior | Separate Kyber adoption review; not implied by Aether adoption |
| Docs/demo/mobile/non-React tools | Metadata directly or shared renderer when host supports it | Product hierarchy, approved assets, accurate capability/provider claims | Per-host dependency, a11y, and asset-path validation |

## Timeline and decision gates

This is a dependency sequence, not a calendar commitment.

1. **Foundation — available:** `@olympus/brand` owns manifest/taxonomy data and
   `@aether/ui` exposes the rendering boundary.
2. **Consumer migration — per owner:** each Aether/Kyber/docs/demo/mobile
   surface adopts the smallest matching primitive while retaining behavioral
   contracts.
3. **Evidence — per consumer:** add focused route/provider/entity/a11y and
   narrow/reduced-motion coverage before declaring that consumer migrated.
4. **Enforcement — integrated work:** run documentation sync, canonical CI, and
   hosted checks after the owned slices land. Do not treat this matrix as proof
   of production readiness.

Read [architecture](./architecture.md) for API boundaries,
[migration](./migration.md) for the change checklist, and
[final audit](./final-audit.md) for the current evidence and open blockers.

