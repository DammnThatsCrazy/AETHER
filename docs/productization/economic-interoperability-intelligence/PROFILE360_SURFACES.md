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
last_synced_commit: "2ad2218"
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

The card-linked payment rail slice adds three more routes to
`services/profile/routes.py` (gated by BOTH
`AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED` and
`AETHER_CARD_LINKED_PROFILE360_ENABLED`):
`GET /v1/profile/{id}/card-linked-activity`, its alias
`GET /v1/profile/{id}/economic/card-linked`, and
`GET /v1/profile/{id}/drill/card-linked/{object_id}` (registered before
the generic drill route). Responses carry `basis`/`source`/`confidence`
on every flow, the entity story (campaign → provider → top-up → spends),
and a warning when an entity has top-up volume but no observed spend —
top-up is never presented as card spend. See
`docs/PROFILE-360-AGGREGATION.md` and
`docs/source-of-truth/CARD_LINKED_PAYMENT_RAILS.md`.

## Semantic dimension

`GET /v1/profile/{id}/semantic` (`read` permission; tenant-scoped) surfaces the
entity's durable weighted semantic state from the semantic Gold reducer — active
topics, stance/intent distribution, summary, confidence, freshness, model/taxonomy
mix, and reducer provenance. It returns an empty-but-shaped response
(`computed: false`, `semantic_summary: "insufficient_data"`) rather than a 404
when no semantic observations exist yet, and delegates to the
semantic-intelligence service's weighted reducer (no duplicated aggregation
logic). Backing data: `gold_entity_semantic_state`. See
`Backend Architecture/aether-backend/services/semantic_intelligence/reducers.py`.
