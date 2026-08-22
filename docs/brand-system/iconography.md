---
title: Iconography
slug: architecture/brand-system/iconography
section: architecture
visibility: I
audience: [dev-junior, dev-senior, architect]
status: stable
since_version: "8.12.0"
canonical_owner: frontend@aether
---

# Iconography

Use named semantic descriptors from `packages/brand/src/iconography/`; the
names are renderer-independent and are not SVG paths, Unicode, or ASCII glyphs.

| Need | Data taxonomy | React renderer |
| --- | --- | --- |
| Shell route | `navigationDestinations` | `NavigationIcon` |
| User action | `actionIcons` | `Icon` |
| Domain/entity | `domainIcons`, `entityIdentities` | `EntityIcon`, `EntityAvatar` |
| Lifecycle/evidence | Status, severity, freshness, confidence, provenance modules | Matching semantic indicator |

```tsx
<NavigationIcon destination="aether-graph" decorative size="md" />
<Icon name="refresh-cw" label="Refresh data" />
```

- Use `decorative` only next to a visible equivalent label.
- A collapsed nav/action button needs a text alternative; an icon alone is not
  its accessible name.
- Use `ICON_SIZE` for visual size (`xs` 12 through `xl` 32), while preserving
  the separate interactive hit target.
- Never add a raw bracketed navigation glyph or font-dependent status symbol.
