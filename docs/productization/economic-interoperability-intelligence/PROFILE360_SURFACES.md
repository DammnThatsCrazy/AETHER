---
title: Profile360 Surfaces
slug: productization/economic-interoperability-intelligence/profile360-surfaces
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - packages/shared/profile360-contract.ts
  - Backend Architecture/aether-backend/services/profile/routes.py
canonical_owner: platform@aether
last_synced_commit: "03ab3a6"
---

# Profile360 Surfaces

`Profile360SubResources` (packages/shared/profile360-contract.ts) gains
`stablecoin_activity?`, `derivatives_trading?`, `interop_activity?`.

Routes (each flag-gated by its domain's `profile360_enabled`; disabled →
404; `read` permission; tenant-scoped):

| Route | Backing data | Attribution |
|---|---|---|
| `GET /v1/profile/{id}/stablecoin` | stablecoin observations | entity refs / wallet ids on observations |
| `GET /v1/profile/{id}/derivatives` | positions + fills | trading accounts with `owner_entity_id == id` |
| `GET /v1/profile/{id}/interoperability` | intents + asset legs | initiator refs and from/to addresses |

Every response returns `{entity_id, items, summary, count, computed_at,
provenance}` with Decimals serialized as strings. Sub-resources are
additive: entities with no economic activity return empty envelopes,
not errors.
