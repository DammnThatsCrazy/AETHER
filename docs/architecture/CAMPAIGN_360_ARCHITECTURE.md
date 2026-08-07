---
title: Campaign 360 Architecture
slug: architecture/campaign-360
section: architecture
visibility: I
audience: [architect, dev-senior]
status: stable
canonical_owner: platform@aether
estimated_read_minutes: 20
toc_depth: 4
source_files:
  - Backend Architecture/aether-backend/services/campaign/exploration.py
  - Backend Architecture/aether-backend/services/campaign/routes.py
  - Backend Architecture/aether-backend/services/measurement/repositories/touchpoint_repo.py
  - Backend Architecture/aether-backend/services/measurement/repositories/conversion_repo.py
  - Backend Architecture/aether-backend/services/measurement/repositories/attribution_run_repo.py
  - Backend Architecture/aether-backend/services/traffic/repair.py
last_synced_commit: "23fc60a"
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

The Campaign 360 population model defines five stages of the identity funnel.
Every entity can only belong to one stage at a time (the highest it has reached).

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

The explorer enforces these invariants on every `get_overview()` call:

```
attributed_count ≤ converted_count ≤ resolved_count ≤ observed_count
```

Any violation raises an assertion error and is surfaced as a `reconciliation_status: error`
in the `data_quality` block. This is a strict invariant — it will never be silenced.

---

## 3. Data Source Strategy

| Data type | Primary store | Fallback (local/test) |
|-----------|---------------|-----------------------|
| Touchpoints | PostgreSQL `silver_campaign_touchpoint_facts` | `_local_store` dict in `touchpoint_repo.py` |
| Conversions | PostgreSQL `canonical_conversions` | `_local_store` dict in `conversion_repo.py` |
| Attribution credits | PostgreSQL `attribution_credits` + `attribution_runs` (tenant-qualified active-run joins, immutable config snapshots, source/referral dimensions) | `_local_credits` list in `attribution_run_repo.py` |
| Spend | PostgreSQL `spend_records` | `_local_spend` dict in `spend_repo.py` |
| Journeys | PostgreSQL `journey_versions` | `_local_journeys` dict in `journey_repo.py` |

The explorer never reads directly from ClickHouse gold tables. Those are used
by the Journey Explorer and Attribution Studio pages separately for aggregate
analytics. Campaign 360 reads from the PostgreSQL canonical layer for
entity-level drill-down.

Source classification is evidence carried through the canonical touchpoint,
journey step, attribution credit, and Campaign 360 read models. Campaign 360
does not reclassify traffic. It groups persisted credits by source class,
mediation type, AI provider/product, actor type, and journey role, and retains
the classifier version and verification provenance used by the run. A repair
creates a new classification revision and recomputed attribution run linked to
the prior run; it does not mutate historical credit evidence in place.

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

- Page: `frontend/kyber/src/pages/measurement/campaign-360-page.tsx`
- Route: `/measurement/campaigns/:campaignId`
- Hooks: `frontend/kyber/src/features/measurement/use-campaign-360.ts`
- Tab components: `frontend/kyber/src/features/measurement/campaign360/`
- URL state: `?tab=overview&population=observed&start=&end=&attribution_model=`
- Operator-only tabs: Quality, Attribution diagnostics

### Aether (tenant)

- Page: `frontend/aether/src/pages/campaigns/campaign-360-page.tsx`
- Route: `/campaigns/:id`
- Hooks: `frontend/aether/src/features/campaigns/use-campaign-360.ts`
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
