---
title: Campaign 360 API Reference
slug: api/campaign-360
section: api
visibility: I
audience: [dev-senior, dev-junior]
status: stable
canonical_owner: platform@aether
estimated_read_minutes: 15
toc_depth: 3
source_files:
  - Backend Architecture/aether-backend/services/campaign/routes.py
  - Backend Architecture/aether-backend/services/campaign/exploration.py
  - Backend Architecture/aether-backend/services/measurement/repositories/touchpoint_repo.py
last_synced_commit: "6306ea81"
---

# Campaign 360 API Reference

> All endpoints require a valid tenant session with `campaign:read` permission.
> Base path: `/v1/campaigns/{campaign_id}/`

---

## Authentication and permissions

| Permission | Required for |
|------------|-------------|
| `campaign:read` | All Campaign 360 endpoints including `POST /{campaign_id}/graph` |

Requests without a valid session return `401 Unauthorized`.
Requests for campaigns belonging to another tenant return `404 Not Found`
(existence is not disclosed across tenant boundaries).

---

## Rate limits

| Endpoint group | Limit |
|----------------|-------|
| `GET /{campaign_id}/graph` | 10 req/min per tenant |
| `GET /{campaign_id}/overview` | 60 req/min per tenant |
| All other Campaign 360 endpoints | 120 req/min per tenant |

Exceeded limits return `429 Too Many Requests` with a `Retry-After` header.

---

## Pagination

All list endpoints support keyset cursor pagination:

- `limit` — number of items per page (default: 50, max: 500)
- `cursor` — opaque string returned as `next_cursor` in the previous response
- Response shape: `{ data: { items: [...], pagination: { limit, next_cursor, has_more } }, status, timestamp }`

> **Envelope note:** All responses are wrapped in the standard API envelope. The `data` key
> contains the payload shown in the examples below. The `status` field is `"ok"` on success
> and `timestamp` is an ISO 8601 UTC string. For brevity, the examples below show only the
> `data.items` array and `data.pagination` (or `data.next_cursor`) fields.

---

## Endpoints

### GET `/{campaign_id}/overview`

Returns reconciled campaign metrics, population funnel counts, attribution
economics, and data quality indicators.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `time_start` | ISO 8601 datetime | — | Start of measurement window |
| `time_end` | ISO 8601 datetime | — | End of measurement window |
| `tz` | IANA timezone string | UTC | Timezone for time bucketing |
| `attribution_model` | string | `last_touch` | Attribution model to use for revenue totals |
| `attribution_run_id` | UUID | — | Pin to a specific attribution run |

**Response shape:**

```json
{
  "campaign_id": "string",
  "spend_usd": 0.0,
  "impressions": 0,
  "clicks": 0,
  "ctr": null,
  "cpc": null,
  "observed_count": 0,
  "resolved_count": 0,
  "engaged_count": 0,
  "converted_count": 0,
  "attributed_count": 0,
  "touchpoint_count": 0,
  "fractional_attributed_conversions": 0.0,
  "gross_attributed_revenue": 0.0,
  "net_attributed_revenue": 0.0,
  "roas": null,
  "identity_resolution_rate": null,
  "attribution_model": "last_touch",
  "attribution_run_id": null,
  "total_credit_weight": 0.0,
  "data_quality": {
    "connector_freshness": "ok | warn | error | unknown",
    "attribution_run_freshness": "fresh | stale | error",
    "projection_lag_hours": null,
    "reconciliation_status": "ok | warn | error",
    "completeness_pct": null
  }
}
```

**Errors:**
- `404` — campaign not found or belongs to another tenant
- `422` — invalid time range (start > end)

---

### GET `/{campaign_id}/population`

Paginated population list. Entities are classified into the requested
population tier and returned with attribution economics.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `population` | enum | `observed` | One of: `observed`, `resolved`, `engaged`, `converted`, `attributed` |
| `group_by` | enum | — | `cluster` — group entities into cluster rows |
| `channel` | string | — | Filter to entities that had touchpoints on this channel |
| `time_start` | ISO 8601 | — | Filter touchpoints/conversions after this time |
| `time_end` | ISO 8601 | — | Filter touchpoints/conversions before this time |
| `limit` | integer | 50 | Items per page (max 500) |
| `cursor` | string | — | Pagination cursor |

**Response shape:**

```json
{
  "items": [
    {
      "entity_id": "string",
      "entity_type": "profile | cluster | anonymous",
      "cluster_id": "string | null",
      "touchpoint_count": 0,
      "conversion_count": 0,
      "attributed_revenue": 0.0,
      "attribution_credit": 0.0,
      "identity_confidence": null,
      "last_activity_at": "ISO 8601 | null",
      "channels": ["email", "paid_search"]
    }
  ],
  "pagination": { "limit": 50, "next_cursor": "string | null", "has_more": false }
}
```

---

### GET `/{campaign_id}/touchpoints`

Paginated touchpoint list for the campaign.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `channel` | string | — | Filter by channel |
| `touchpoint_type` | string | — | Filter by type (click, impression, email_open, etc.) |
| `after` | ISO 8601 | — | Touchpoints occurred after this time |
| `before` | ISO 8601 | — | Touchpoints occurred before this time |
| `limit` | integer | 50 | Items per page (max 500) |
| `cursor` | string | — | Pagination cursor |

**Response shape:**

```json
{
  "items": [
    {
      "touchpoint_id": "string",
      "touchpoint_type": "string",
      "channel": "string",
      "profile_id": "string | null",
      "cluster_id": "string | null",
      "anonymous_id": "string | null",
      "source_class": "string | null",
      "referral_mediation_type": "string | null",
      "ai_provider": "string | null",
      "ai_product": "string | null",
      "verification_level": "string | null",
      "evidence_confidence": 0.0,
      "source_classifier_version": "string | null",
      "attribution_eligible": true,
      "occurred_at": "ISO 8601"
    }
  ],
  "pagination": { "limit": 50, "next_cursor": "string | null", "has_more": false }
}
```

---

### GET `/{campaign_id}/entities`

Paginated entity list grouped by canonical entity type.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `entity_type` | string | — | Filter by type (`profile`, `cluster`, `account`) |
| `time_start` | ISO 8601 | — | Activity window start |
| `time_end` | ISO 8601 | — | Activity window end |
| `limit` | integer | 50 | Items per page (max 500) |
| `cursor` | string | — | Pagination cursor |

**Response shape:**

```json
{
  "items": [
    {
      "entity_id": "string",
      "entity_type": "string",
      "touchpoint_count": 0,
      "conversion_count": 0,
      "attributed_revenue": 0.0,
      "channels": ["string"],
      "last_activity_at": "ISO 8601 | null"
    }
  ],
  "pagination": { "limit": 50, "next_cursor": "string | null", "has_more": false }
}
```

---

### GET `/{campaign_id}/clusters`

Cluster rollup with attribution economics for the campaign.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `attribution_run_id` | UUID | — | Pin to a specific attribution run |
| `time_start` | ISO 8601 | — | Activity window start |
| `time_end` | ISO 8601 | — | Activity window end |
| `limit` | integer | 50 | Items per page (max 500) |
| `cursor` | string | — | Pagination cursor |

**Response shape:**

```json
{
  "items": [
    {
      "cluster_id": "string",
      "member_count": 0,
      "touchpoint_count": 0,
      "conversion_count": 0,
      "attributed_gross_revenue": 0.0,
      "attributed_net_revenue": 0.0,
      "top_channels": ["string"],
      "identity_confidence": null
    }
  ],
  "pagination": { "limit": 50, "next_cursor": "string | null", "has_more": false }
}
```

---

### GET `/{campaign_id}/journeys`

Journey versions where this campaign appears as a touchpoint source.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `after` | ISO 8601 | — | Journeys compiled after this time |
| `before` | ISO 8601 | — | Journeys compiled before this time |
| `limit` | integer | 50 | Items per page (max 500) |
| `cursor` | string | — | Pagination cursor |

**Response shape:**

```json
{
  "items": [
    {
      "journey_id": "string",
      "journey_version": 0,
      "entity_id": "string",
      "entity_type": "string",
      "step_count": 0,
      "campaign_role": "string",
      "compiled_at": "ISO 8601"
    }
  ],
  "pagination": { "limit": 50, "next_cursor": "string | null", "has_more": false }
}
```

---

### GET `/{campaign_id}/conversions`

Conversions linked to this campaign. Returns attributed conversions by default;
pass `include_unattributed=true` to include all campaign-associated conversions.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `cluster_id` | UUID | — | Filter to a specific cluster |
| `channel` | string | — | Filter to conversions from this channel |
| `attribution_run_id` | UUID | — | Filter to a specific attribution run |
| `creative_id` | string | — | Filter to a specific creative |
| `status` | string | — | Conversion status filter |
| `include_unattributed` | boolean | `false` | Include conversions without active credits |
| `after` | ISO 8601 | — | Conversions occurred after this time |
| `before` | ISO 8601 | — | Conversions occurred before this time |
| `limit` | integer | 50 | Items per page (max 500) |
| `cursor` | string | — | Pagination cursor |

**Response shape:**

```json
{
  "items": [
    {
      "conversion_id": "string",
      "conversion_type": "string",
      "gross_value": 0.0,
      "net_value": 0.0,
      "credit_weight": null,
      "cluster_id": "string | null",
      "channel": "string | null",
      "occurred_at": "ISO 8601"
    }
  ],
  "pagination": { "limit": 50, "next_cursor": "string | null", "has_more": false }
}
```

---

### GET `/{campaign_id}/attribution`

Returns tenant-scoped active credit totals plus dimension rollups for channel,
source class, referral mediation, AI provider/product, actor type, and journey
role. Credit rows retain verification, evidence-confidence, classifier-version,
classification-ID, and verified-referral-link provenance. The route accepts
`model`, `start_date`, and `end_date`; date-only `end_date` is inclusive by
normalizing it to an exclusive next-day UTC boundary. Datetimes without an
offset are interpreted as UTC.

---

### POST `/{campaign_id}/graph`

Build a bounded campaign-centered graph query. Returns nodes, edges, and
truncation status when limits are hit.

**Required permission:** `campaign:read`

**Request body:**

```json
{
  "population": "observed",
  "depth": 2,
  "max_nodes": 100,
  "max_edges": 300,
  "time_range": {
    "start": "ISO 8601",
    "end": "ISO 8601"
  },
  "continuation_token": null
}
```

| Field | Type | Default | Max | Description |
|-------|------|---------|-----|-------------|
| `population` | enum | `observed` | — | Population tier to include as vertices |
| `depth` | integer | 2 | **3** | Graph traversal depth |
| `max_nodes` | integer | 100 | **500** | Hard cap on returned nodes |
| `max_edges` | integer | 300 | **1500** | Hard cap on returned edges |
| `time_range` | object | — | — | Optional time window for touchpoint/conversion edges |
| `continuation_token` | string | — | — | Resume a truncated query |

**Response shape:**

```json
{
  "nodes": [
    {
      "id": "string",
      "label": "string",
      "type": "Campaign | Entity | IdentityCluster | User"
    }
  ],
  "edges": [
    {
      "id": "string",
      "source": "string",
      "target": "string",
      "type": "string"
    }
  ],
  "node_count": 0,
  "edge_count": 0,
  "truncated": false,
  "truncation_reason": null,
  "continuation_token": null
}
```

**Errors:**
- `400` — `depth` exceeds 3
- `404` — campaign not found
- `429` — rate limit exceeded (10 req/min)
- `504` — graph query timed out (10s budget)

---

### Communications surfaces (v8.11.0+)

Email-aware Campaign 360 endpoints backed by `silver_comms_facts` and the
`campaign_messages` dimension (see
[Communications Intelligence Overview](../comms/COMMUNICATIONS_INTELLIGENCE_OVERVIEW.md)):

| Endpoint | Returns |
|---|---|
| GET `/{campaign_id}/messages` | Per-message rollup: delivered, human-qualified clicks, replies, bounces, machine events; merged with synced message dimension rows |
| GET `/{campaign_id}/messages/{external_message_id}` | Message detail: dimension record, engagement stats, link rollup |
| GET `/{campaign_id}/links` | Link performance: human-qualified clicks and unique clickers per link |
| GET `/{campaign_id}/comms-population` | Recipient population with communication stages (attempted → delivered → engaged → replied) and composable flag filters (`bounced`, `complained`, `unsubscribed`, `suppressed`, `human_qualified`); alias-keyed rows with Profile360 links |
| GET `/{campaign_id}/comms-funnel` | Email funnel in two modes — `provider_reported` (every provider event) and `human_qualified` (suspected machine activity and automated replies excluded) — plus delivery detail (bounces, complaints, unsubscribes, suppressions), quality (machine-event rate), and governed `*_rate_result` objects |

Each communication rate is registry-governed. The legacy scalar fields
(`open_rate`, `click_rate`, `reply_rate`, and `machine_event_rate`) are
nullable and mirror the corresponding result's `value`. Each
`*_rate_result` and entry in `measurement_integrity` has this shape:

```json
{
  "metric_name": "email_open_rate",
  "metric_version": "1",
  "value": null,
  "value_state": "observed | insufficient_sample | missing",
  "unit": "ratio",
  "sufficiency": {
    "sufficient": false,
    "observations": 4,
    "minimum_observations": 20
  },
  "uncertainty": null,
  "lineage": {
    "source": "comms_facts",
    "tenant_id": "string",
    "campaign_id": "string",
    "denominator": "delivered"
  }
}
```

When the governed minimum sample is not met, `value` and the matching legacy
scalar are `null`; consumers must use `value_state` and `sufficiency`
instead of interpreting the absence as zero. Sufficient rates include a Wilson
interval in `uncertainty`.

---

## Error contract

All errors use this envelope:

```json
{
  "error": {
    "code": "string",
    "message": "string",
    "detail": {}
  }
}
```

| HTTP status | `error.code` | When |
|-------------|--------------|------|
| 400 | `invalid_request` | Bad parameters (depth > 3, invalid enum, etc.) |
| 401 | `unauthenticated` | Missing or expired session |
| 403 | `forbidden` | Insufficient permission |
| 404 | `not_found` | Campaign not found or cross-tenant |
| 422 | `validation_error` | Request body fails schema validation |
| 429 | `rate_limited` | Too many requests |
| 504 | `timeout` | Graph query exceeded 10s budget |


---

## Campaign Registry API (v8.11.0+)

The Campaign Registry API is a separate API surface introduced in v8.11.0 for managing canonical campaign identities, external references, aliases, campaign sources, and mapping review. It lives at `/v1/campaigns` (list/create), `/v1/campaign-sources`, `/v1/mapping-review`, and `/v1/campaign-quality`. These endpoints use the same permission model (`campaign:read` / `campaign:write`) and error envelope as the Campaign 360 API above.

See `docs/campaign/CAMPAIGN_INTELLIGENCE_OVERVIEW.md` and `docs/campaign/CAMPAIGN_REGISTRY_ARCHITECTURE.md` for the full contract.
