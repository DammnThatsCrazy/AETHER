---
title: Campaign 360 Architecture
slug: architecture/campaign-360
section: architecture
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: 0.1.0
canonical_owner: platform@aether
estimated_read_minutes: 20
toc_depth: 4
source_files: [services/api/journeys/campaign/exploration.py, services/api/journeys/campaign/routes.py, services/api/journeys/campaign/campaign_population_links.py, services/api/journeys/measurement/repositories/touchpoint_repo.py, services/api/journeys/measurement/repositories/conversion_repo.py, services/api/journeys/measurement/repositories/attribution_run_repo.py, services/api/journeys/traffic/repair.py]
source_hashes:
  "services/api/journeys/campaign/campaign_population_links.py": "sha256:edb58c750b362e6a0441c88225007acd563e9f9fb105b31629cd8653a6dea894"
  "services/api/journeys/campaign/exploration.py": "sha256:e13313cc1041aa66ea25ded2d3fac22af21bb6ab7c5ce61641184ed3ac364f13"
  "services/api/journeys/campaign/routes.py": "sha256:43cafac0205f69a989aa26ba63b89075b9d4acbacfdeb672f5768099c19a4bd9"
  "services/api/journeys/measurement/repositories/attribution_run_repo.py": "sha256:56ebf7f346abbd3d9edd84908563baed5baf8967fd8ae4294c2fa0b32ce7c27c"
  "services/api/journeys/measurement/repositories/conversion_repo.py": "sha256:7b3f6cdb71101a726f21444595ef22224b8cc57f7b02fa37313f478e546eebb8"
  "services/api/journeys/measurement/repositories/touchpoint_repo.py": "sha256:98bb17dd43058e20aef6b5430e1d33f69efbd66558a7ac58afd3e460ca63f20e"
  "services/api/journeys/traffic/repair.py": "sha256:309a31315d07945083aa693341cff37b4fe5cefbc71592925c38ad818acfab68"
---

# Campaign 360 Architecture

> Single-page architecture reference for the Campaign 360 exploration surface:
> a drill-down path from any campaign through macro performance → population →
> clusters → entities → journeys → conversions → attribution → graph.

---

## 1. Overview

Campaign 360 is the canonical operator and tenant surface for inspecting a
campaign across every measurement dimension. It is served by a dedicated
`CampaignPopulationExplorer` service that orchestrates reads across the five
existing measurement repositories without performing any attribution
calculations itself.

```
Campaign 360 page
    │
    ├── Overview tab      ← CampaignPopulationExplorer.get_overview()
    ├── Population tab    ← CampaignPopulationExplorer.get_population()
    ├── Clusters tab      ← AttributionRunRepository.campaign_cluster_rollup()
    ├── Entities tab      ← CampaignPopulationExplorer.get_entities()
    ├── Journeys tab      ← CampaignPopulationExplorer.get_journeys()
    ├── Conversions tab   ← ConversionRepository.list_by_campaign()
    ├── Attribution tab   ← AttributionRunRepository.campaign_credit_summary()
    │                        (source/referral dimensions + evidence provenance)
    ├── Graph tab         ← CampaignPopulationExplorer.get_graph_anchor()
    └── Quality tab       ← CampaignPopulationExplorer.get_overview() (data_quality field)
```

---

## 2. Population Semantics

The Campaign 360 population model defines five cumulative stages of the
identity funnel. An entity may appear in each stage it reaches; the API returns
the selected stage's population rather than assigning each entity to only one
stage.

| Population | Definition | Data source |
|------------|------------|-------------|
| `observed` | Any entity that generated at least one campaign touchpoint | `silver_campaign_touchpoint_facts` |
| `resolved` | Observed entities with a non-null `profile_id` or `cluster_id` | `silver_campaign_touchpoint_facts` (identity join) |
| `engaged` | Resolved entities with at least one interaction touchpoint (click, open, reply, visit — not impression-only). Email engagement touchpoints (`email_open`, `email_click`, `email_reply`) are created only for human-qualified activity: suspected machine events and automated replies never become engagement touchpoints (ADR-C8) | `silver_campaign_touchpoint_facts` WHERE touchpoint_type NOT IN ('impression', 'viewable_impression', 'ad_exposure', 'email_delivery', 'push_presentation') |
| `converted` | Entities with at least one canonical conversion linked to this campaign | `canonical_conversions` (reverse lookup via touchpoint profile match) |
| `attributed` | Entities with at least one active attribution credit for this campaign | `attribution_credits` JOIN `attribution_runs` WHERE is_active=TRUE |

The touchpoint-based populations above are complemented by the comms-specific
recipient population (`GET /{campaign_id}/comms-population`): alias-keyed
recipients with the highest reached communication stage
(attempted → delivered → engaged → replied) and delivery flags, derived from
`silver_comms_facts` — machine-classified engagement never advances a stage.

Communication funnel rates are computed through the shared measurement registry,
not as ad hoc divisions. Every rate carries a versioned metric name, value state,
sample sufficiency, Wilson uncertainty (when observed), and source lineage. The
legacy scalar rate mirrors the governed value and is nullable; insufficient or
missing samples are therefore withheld rather than presented as zero. The Aether
tenant surface renders the state and does not reveal a numeric rate until the
registry minimum is met.

### Reconciliation invariants

The overview targets this funnel ordering:

```
attributed_count ≤ converted_count ≤ resolved_count ≤ observed_count
```

The current implementation clamps `resolved` to `observed`, `engaged` to the
clamped `resolved`, and `attributed` to `converted`. It does not clamp
`converted` to `resolved`. If one of those three clamps changes a value,
`data_quality.reconciliation_status` is `inconsistent`; otherwise it is
`unknown`. The explorer does not raise an assertion or report `ok` for this
check.

---

## 3. Data Source Strategy

| Data type | Primary store | Fallback (local/test) |
|-----------|---------------|-----------------------|
| Touchpoints | PostgreSQL `silver_campaign_touchpoint_facts` | `_local_store` dict in `touchpoint_repo.py` |
| Conversions | PostgreSQL `canonical_conversions` | `_local_store` dict in `conversion_repo.py` |
| Attribution credits | PostgreSQL `attribution_credits` + `attribution_runs` (tenant-qualified active-run joins, immutable config snapshots, source/referral dimensions) | `_local_credits` list in `attribution_run_repo.py` |
| Spend | PostgreSQL `spend_records` | `_local_spend` dict in `spend_repo.py` |
| Journeys | PostgreSQL `journey_versions` | `_local_journeys` dict in `journey_repo.py` |

Explicit campaign-to-population associations are recorded separately as
append-only `campaign_population_link_events`, after exact same-tenant
campaign and population validation. Current reads choose the latest event per
population whose effective time has arrived; future-effective links do not
hide the current association. These links do not establish cluster membership
or syndicate topology. Journey attribution credit reads join a completed,
active run by exact tenant, journey ID, and journey version and remain bounded.

The explorer never reads directly from ClickHouse gold tables. Those are used
by the Journey Explorer and Attribution Studio pages separately for aggregate
analytics. Campaign 360 reads from the PostgreSQL canonical layer for
entity-level drill-down.

`ConversionRepository` also provides exact tenant/account and tenant/agent
reads for the Account360 and Agent360 projections. These are separate subject
lookups: they do not infer a campaign association, replace the campaign
touchpoint join, or change the campaign-scoped `list_by_campaign()` path.

Signals360 uses a separate event-to-campaign read through
`TouchpointRepository.list_by_source_event(tenant_id, source_event_id)`. The
query requires both exact keys. A touchpoint's campaign ID is exposed only
after `CampaignRepository.get_by_id()` resolves that exact ID for the same
tenant. This projection read does not infer links from campaign names, source
labels, or external IDs; malformed, unresolved, cross-tenant, and truncated
results keep the slot partial or degraded. It does not add a public Campaign
360 endpoint.

Source classification is evidence carried through the canonical touchpoint,
journey step, attribution credit, and Campaign 360 read models. Campaign 360
does not reclassify traffic. It groups persisted credits by source class,
mediation type, AI provider/product, actor type, and journey role, and retains
the classifier version and verification provenance used by the run. A repair
creates a new classification revision and recomputed attribution run linked to
the prior run; it does not mutate historical credit evidence in place.
The backend Campaign360 projection now checks an exact tenant, touchpoint, and
classification ID against the immutable revision store before treating that
revision as a source fact. It compares the current pointer's class, classifier
version, and time, and keeps campaign registry source provenance unresolved.

**Money in credit rollups.** `canonical_conversions` keeps the native amount
and currency; `exchange_rate` is a real recorded rate (with
`provenance.fx_conversion`), exactly `1.0` for same-currency rows, or **NULL**
when no rate is known (unconverted). Attribution credits and runs carry revenue
in the conversion's normalized currency (USD): `native × exchange_rate`, and
NULL for an unconverted conversion. Campaign revenue totals, the cluster
rollup, and referral rollups therefore sum a single currency; unconverted
credits are excluded and counted in `unconverted_credit_count` (the summary's
`data_quality` becomes `partial`). The canonical row for a dedup key is owned
by the greatest `(authority_rank, occurred_at, source_event_id)` source record,
so it does not depend on arrival order (Silver conversions are written through
`ConversionRepository`, not the generic first-write-wins insert).

### Ad-platform source connect (WS-2, additive)

The Campaign Sources page's advertising connect flow is additive to this
architecture and does not change the explorer's read repos. It is orchestrated
by `services/api/journeys/campaign/ad_source_links.py` over the canonical
`measurement_connectors` store — the same rows the measurement ad connectors
read at sync time. Connect is idempotent (one *active* source per
tenant/family) and requires a complete credential set at store time — first
connect never overwrites a stored config. Account selection remains an explicit
rotation (archive + fresh active row carrying the credentials forward). A
degraded/failed/stale, disabled, or secret-missing source instead has a separate
in-place re-credential path, `POST /v1/campaign-sources/{connector_id}/reconnect`,
which replaces the stored credential set on the SAME row and resets its
health/error state to the never-synced baseline (refused with `409` while the
row is active and healthy; a credential swap is not evidence of a healthy sync).
Read models are redacted: `config` is never returned. The endpoints hang off the same
`/v1/campaign-sources` router used by the registry API; ambiguous campaign
resolution (mapping an external provider campaign to a canonical Aether
campaign) stays in the `/v1/mapping-review` surface, which is unchanged.

---

## 4. Query Budget Policy

Graph queries are the most expensive operation in Campaign 360. The explorer
enforces hard limits at the service layer (not just the route layer):

| Parameter | Default | Maximum | Enforcement |
|-----------|---------|---------|-------------|
| `depth` | 2 | 3 | `ValueError` if exceeded |
| `max_nodes` | 100 | 500 | Capped by explorer, not rejected |
| `max_edges` | 300 | 1500 | Capped by explorer, not rejected |
| Timeout | — | 10s | `asyncio.wait_for` in `get_graph_anchor()` |

When `max_nodes` or `max_edges` is hit, the response includes:
- `truncated: true`
- `truncation_reason: "node_limit"` or `"edge_limit"`
- `continuation_token` (opaque cursor for the next page)

Rate limits are enforced at the route layer (not the explorer):
- Graph endpoint: 10 req/min per tenant
- Overview endpoint: 60 req/min per tenant

---

## 5. Graph Architecture

### Vertex types used as anchors

Campaign 360 uses two existing vertex types from `shared/graph/graph.py`:

| Vertex type | When used |
|-------------|-----------|
| `VertexType.CAMPAIGN` ("Campaign") | Primary anchor for all campaign graph queries |
| `VertexType.AD_CAMPAIGN` ("AdCampaign") | Paid-media hierarchy variant (when campaign type is "paid") |

No new vertex types were added. The graph is built at query time by expanding
from the campaign anchor through existing relationship edges in the graph store.

### Edge traversal strategy

The graph expands outward from the campaign anchor using BFS up to the
configured `depth`. At each hop, the explorer loads related vertices from the
following relationship layers (in priority order):

1. `CAMPAIGN → ENTITY` (direct touchpoint relationships)
2. `CAMPAIGN → IDENTITY_CLUSTER` (cluster-level attribution)
3. `ENTITY → IDENTITY_CLUSTER` (cluster membership)
4. `IDENTITY_CLUSTER → IDENTITY_CLUSTER` (cross-cluster resolution)

Only edges that exist in the local or PostgreSQL graph store are returned.
Phantom edges (edges implied by touchpoint data but not yet persisted to the
graph) are not synthesized.

---

## 6. Security and Tenant Isolation

Every method on `CampaignPopulationExplorer` accepts `tenant_id` as the first
argument and propagates it to every repository call. The explorer never accepts
a raw campaign ID without also passing the tenant ID to the underlying repo —
there is no method signature that takes only a campaign ID.

At the route layer, every endpoint verifies:
```python
campaign.tenant_id == request.tenant.tenant_id
```
before delegating to the explorer. Cross-tenant access returns HTTP 404
(not 403) to avoid leaking the existence of campaigns in other tenants.

Audit events are emitted for:
- Graph queries (`POST /{campaign_id}/graph`)
- Large population requests (> 1000 rows)

---

## 7. Frontend Surface

### Kyber (operator)

- Page: `apps/kyber-web/src/pages/measurement/campaign-360-page.tsx`
- Route: `/measurement/campaigns/:campaignId`
- Hooks: `apps/kyber-web/src/features/measurement/use-campaign-360.ts`
- Tab components: `apps/kyber-web/src/features/measurement/campaign360/`
- URL state: `?tab=overview&population=observed&start=&end=&attribution_model=`
- Operator-only tabs: Quality, Attribution diagnostics

### Aether (tenant)

- Page: `apps/aether-web/src/pages/campaigns/campaign-360-page.tsx`
- Route: `/campaigns/:id`
- Hooks: `apps/aether-web/src/features/campaigns/use-campaign-360.ts`
- Same tab structure as Kyber, minus operator diagnostics

### Cross-feature integration

| Integration point | What was added |
|-------------------|----------------|
| Campaign Intelligence page | "Open Campaign 360 →" link per campaign row |
| Attribution Studio | `?campaign_id=` URL param pre-filters runs; "Compare in Campaign 360 →" link |
| Journey Explorer | `campaign_id` filter input |
| Conversion Explorer | `campaign_id`, `cluster_id`, `attribution_run_id`, `channel` filter inputs |

---

## 8. Testing Strategy

| Layer | File | Coverage |
|-------|------|----------|
| Unit | `tests/unit/test_campaign_population_explorer.py` | Explorer methods, reconciliation, graph budget |
| Integration | `tests/integration/test_campaign_360_api.py` | API routes, pagination, 404 cross-tenant |
| Security | `tests/security/test_campaign_360_tenant_isolation.py` | Cross-tenant isolation |
| E2E (flow) | `tests/e2e/test_campaign_360_flow.py` | Full A/B/C scenarios |
| E2E (paid media) | `tests/e2e/test_paid_media_ecommerce_flow.py` | Full paid-media journey with Campaign 360 verification |
