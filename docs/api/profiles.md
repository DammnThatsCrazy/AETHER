---
title: Profiles API
slug: api/profiles
section: reference
visibility: P
audience: [dev-senior]
status: stable
since_version: 0.1.0
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 3
---

# Profiles API

Read a resolved [profile](../concepts/profiles.md) — the composed 360 view
of one entity, or any single facet of it — with a read-scoped API key.

## Authentication

`Authorization: Bearer <read_key>` with `read` permission. See
[Authentication](authentication.md).

## Full profile

```
GET /v1/profile/{user_id}
```

Query parameters (all optional, all default to `true` except `timeline_limit`):

| Parameter | Type | Default | Description |
|---|---|---|---|
| `include_timeline` | boolean | `true` | Include the event timeline. |
| `include_graph` | boolean | `true` | Include graph relationship edges. |
| `include_intelligence` | boolean | `true` | Include risk scores, ML features, model outputs. |
| `include_lake` | boolean | `true` | Include aggregated Gold-tier analytical data. |
| `timeline_limit` | integer | `50` | Timeline events returned, 1–500. |

```bash
curl -H "Authorization: Bearer $AETHER_READ_KEY" \
  "https://api.aether.io/v1/profile/usr_18f2?include_lake=false&timeline_limit=100"
```

```json
{
  "data": {
    "user_id": "usr_18f2",
    "identity": { "userId": "usr_18f2", "anonymousIds": ["anon_c3d4"] },
    "timeline": [ { "type": "order_completed", "timestamp": "…" } ],
    "graph": { "edges": [ /* … */ ] },
    "intelligence": { "churn_risk": "low" }
  }
}
```

## Facet endpoints

Every section of the full profile is also independently addressable, so a
caller that only needs one slice doesn't have to pay for (or wait on) the
rest:

| Endpoint | Returns |
|---|---|
| `GET /v1/profile/{user_id}/timeline` | Event history |
| `GET /v1/profile/{user_id}/graph` | Relationship edges |
| `GET /v1/profile/{user_id}/intelligence` | Risk/feature/model outputs |
| `GET /v1/profile/{user_id}/identifiers` | Known identifiers (device, email hash, wallet, …) |
| `GET /v1/profile/{user_id}/provenance` | Where each fact came from |
| `GET /v1/profile/{user_id}/wallets` | Connected wallets |
| `GET /v1/profile/{user_id}/sessions` / `/devices` | Session and device history |
| `GET /v1/profile/{user_id}/journeys` / `/unified-journey` | Journey history (see [Journeys](../concepts/journeys.md)) |
| `GET /v1/profile/{user_id}/campaigns` | Attributed campaign touchpoints |
| `GET /v1/profile/{user_id}/rewards` | Reward eligibility and claim history |
| `GET /v1/profile/{user_id}/financials` | Financial activity (opt-in gated) |
| `GET /v1/profile/{user_id}/predictions` | Model-derived predictions |
| `GET /v1/resolve?…` | Resolve a profile from a partial identifier (email hash, wallet, device) |

Every list-shaped response carries `limit`, `returned`, and `truncated` /
`has_more` so a caller can tell the difference between "there is no more
data" and "there is more than fits in this page" — Aether never implies
completeness when a response was truncated.

## Next steps

- [Profiles concept](../concepts/profiles.md) — identity resolution and how
  a profile is composed.
- [Lenses](../concepts/lenses.md) — composable views over the same
  underlying subject.
