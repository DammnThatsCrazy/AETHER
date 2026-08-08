---
title: Entity identity
slug: architecture/brand-system/entities
section: architecture
visibility: I
audience: [dev-senior, architect, ops]
status: stable
since_version: "8.12.0"
canonical_owner: frontend@aether
---

# Entity identity

Entity mappings live in `packages/brand/src/iconography/entities.ts`. They
describe the base entity type and fallback behavior; an external provider is an
optional source overlay, never the entity's replacement identity.

```tsx
import { EntityAvatar, EntityIcon } from '@aether/ui';

<EntityIcon entityType="wallet" decorative />
<EntityAvatar entityType={entity.type} name={entity.displayName} />
```

- Use an approved avatar if present, then meaningful initials for people/orgs,
  then the semantic entity icon.
- Preserve entity type, graph semantics, node data, and profile route behavior.
- Add a new canonical type/alias to the taxonomy and test `resolveEntityIdentity`
  before rendering it in a graph or list.
- Use the mapped shape for a stable visual distinction; do not rely on color as
  the only entity differentiator.
