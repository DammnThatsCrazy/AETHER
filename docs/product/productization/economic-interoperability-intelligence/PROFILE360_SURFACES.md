---
title: Profile360 Surfaces
slug: productization/economic-interoperability-intelligence/profile360-surfaces
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [packages/shared/profile360-contract.ts, services/api/identity/profile/routes.py]
canonical_owner: platform@aether
source_hashes:
  "packages/shared/profile360-contract.ts": "sha256:bad6bde6b18cd49a1ba08093b02ac9d1c97f75dfe30154e82565b71c2ae15033"
  "services/api/identity/profile/routes.py": "sha256:db152bc22effffbb626e2de110e7b369c05be76efd543316045fabd54066b70a"
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
`services/api/identity/profile/routes.py` (gated by BOTH
`AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED` and
`AETHER_CARD_LINKED_PROFILE360_ENABLED`):
`GET /v1/profile/{id}/card-linked-activity`, its alias
`GET /v1/profile/{id}/economic/card-linked`, and
`GET /v1/profile/{id}/drill/card-linked/{object_id}` (registered before
the generic drill route). Responses carry `basis`/`source`/`confidence`
on every flow, the entity story (campaign → provider → top-up → spends),
and a warning when an entity has top-up volume but no observed spend —
top-up is never presented as card spend. See
`docs/architecture/PROFILE-360-AGGREGATION.md` and
`docs/reference/source-of-truth/CARD_LINKED_PAYMENT_RAILS.md`.

## Semantic dimension

`GET /v1/profile/{id}/semantic` (`read` permission; tenant-scoped) surfaces the
entity's durable weighted semantic state from the semantic Gold reducer — active
topics, stance/intent distribution, summary, confidence, freshness, model/taxonomy
mix, and reducer provenance. It returns an empty-but-shaped response
(`computed: false`, `semantic_summary: "insufficient_data"`) rather than a 404
when no semantic observations exist yet, and delegates to the
semantic-intelligence service's weighted reducer (no duplicated aggregation
logic). Backing data: `gold_entity_semantic_state`. See
`services/api/intelligence/semantic_intelligence/reducers.py`.
