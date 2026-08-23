---
title: Profile 360 Aggregation Layer
slug: api/profile-360-aggregation
section: api
visibility: P
audience: [dev-senior, architect]
status: stable
since_version: "8.8.0"
source_files:
  - Backend Architecture/aether-backend/services/profile/aggregator.py
  - Backend Architecture/aether-backend/services/profile/routes.py
  - Backend Architecture/aether-backend/services/profile/intelligence.py
  - Backend Architecture/aether-backend/services/profile/read_result.py
  - Backend Architecture/aether-backend/services/reconciliation/expectations.py
  - Backend Architecture/aether-backend/services/reconciliation/coverage.py
  - Backend Architecture/aether-backend/services/card_linked_payments/profile_summary.py
canonical_owner: backend@aether
estimated_read_minutes: 8
toc_depth: 3
last_synced_commit: "74086291"
---

# Profile 360 Aggregation Layer

The Profile 360 aggregation layer is the frontend-facing read API for any
entity in Aether — human, agent, organization, wallet, or system actor. It
sits on top of the existing Profile 360 subsystems (entities, identity
clusters, delegations, flows, behavior, journey chains, agent executions,
payment intents, settlements, analytics, graph) and exposes normalized
drill-down endpoints that a UI can render directly.

This document is the source of truth for the response shape, the dimensions
the layer surfaces, and the migration story for older Profile 360 callers.

---

## Why a dedicated aggregation layer

The Profile 360 backend (entities/delegations/flows/behavior/etc.) was
already implemented service-by-service. Frontend code was paying the cost
of stitching those services together — three to seven round-trips just to
render a single profile header — and was making cross-tenant filtering
decisions client-side.

The aggregator does that stitching once, in one place, tenant-scoped, with
a single response envelope. Frontends now fetch one endpoint per dimension
and never join data themselves.

The aggregator is **additive and read-only**. It does not mutate any
state, does not duplicate any repository, and does not replace any
existing endpoint.

---

## Architectural position

```
┌──────────────────────────────────────────────────────────────┐
│  /v1/profile/{user_id}/...   (this layer)                    │
│  Profile360Aggregator                                        │
└──────────────┬───────────────────────────────────────────────┘
               │ reads
               ▼
┌──────────────────────────────────────────────────────────────┐
│  Existing Profile 360 subsystems (unchanged)                 │
│                                                              │
│  EntityRepository       IdentityClusterRepository            │
│  DelegationRepository   WalletRepository  AssetRepository    │
│  TransferRepository     AgentConfigRepository                │
│  AgentExecutionRepository  BehaviorProfileRepository         │
│  JourneyChainRepository    PaymentIntentRepository           │
│  SettlementEventRepository AnalyticsRepository  GraphClient  │
└──────────────────────────────────────────────────────────────┘
               ▲                              ▲
               │                              │
               │ writes                       │ events
               │                              │
       /v1/entities  /v1/delegations  /v1/flows  /v1/behavior
       /v1/agents    /v1/realtime     /v1/ingest ...
```

Existing direct endpoints (`/v1/entities`, `/v1/delegations`, …) remain
the source of writes. The aggregator only reads, so it cannot drift from
the canonical state.

---

## Endpoints

All routes mount under `/v1/profile/{user_id}` and require the `read`
permission on the active tenant. Every response is wrapped in the
standard `APIResponse` envelope (`{ok, data, ...}`); the `data` payload
is what is documented below.

| Method | Path                                                       | Returns                                            |
|--------|------------------------------------------------------------|----------------------------------------------------|
| GET    | `/v1/profile/{id}`                                         | Full omniview (existing, unchanged)                |
| GET    | `/v1/profile/{id}/summary`                                 | Dashboard-ready snapshot                           |
| GET    | `/v1/profile/{id}/graph`                                   | Graph nodes + edges                                |
| GET    | `/v1/profile/{id}/timeline`                                | Event timeline                                     |
| GET    | `/v1/profile/{id}/agents`                                  | Owned agents                                       |
| GET    | `/v1/profile/{id}/wallets`                                 | Owned wallets across chains                        |
| GET    | `/v1/profile/{id}/journeys`                                | Cross-session journey chains                       |
| GET    | `/v1/profile/{id}/unified-journey`                         | Current typed-identity journey, ordered steps, source evidence, and quality metadata |
| GET    | `/v1/profile/{id}/behavior`                                | Latest derived behavior snapshot                   |
| GET    | `/v1/profile/{id}/predictions`                             | Predicted next + anomaly flags                     |
| GET    | `/v1/profile/{id}/rewards`                                 | Rewards earned                                     |
| GET    | `/v1/profile/{id}/platforms`                               | Platform attribution                               |
| GET    | `/v1/profile/{id}/protocols`                               | Protocol interactions                              |
| GET    | `/v1/profile/{id}/devices`                                 | Devices (deterministic + observed)                 |
| GET    | `/v1/profile/{id}/sessions`                                | Sessions with rollups                              |
| GET    | `/v1/profile/{id}/financials`                              | Inflow/outflow/settlement summary                  |
| GET    | `/v1/profile/{id}/delegations`                             | Granted / received delegations                     |
| GET    | `/v1/profile/{id}/external-deployments`                    | External agent deployment activity (flag-gated: `AETHER_AGENT_DEPLOYMENT_PROFILE360_ENABLED`) |
| GET    | `/v1/profile/{id}/payment-rails`                           | Funding-session rollup: counts by provider/rail/status/reconciliation + per-currency native totals (flag-gated: `AETHER_PAYMENT_RAILS_ENABLED`) |
| GET    | `/v1/profile/{id}/relationships`                           | Typed normalized relationships                     |
| GET    | `/v1/profile/{id}/drill/{object_type}/{object_id}`         | Generic deep drill                                 |
| GET    | `/v1/profile/{id}/identifiers`                             | All linked identifiers                             |
| GET    | `/v1/profile/{id}/provenance`                              | Source attribution                                 |
| GET    | `/v1/profile/{id}/intelligence`                            | Risk + features + models                           |
| GET    | `/v1/profile/{id}/lake/{domain}`                           | Gold-tier lake data                                |
| GET    | `/v1/profile/{id}/flows`                                   | Asset transfers (raw list)                         |
| GET    | `/v1/profile/{id}/campaigns`                               | Campaign attribution (derived from event stream)   |
| GET    | `/v1/profile/resolve`                                      | Resolve any identifier to canonical id             |

### Identity cluster and quality endpoints

Added after v8.8.0 (`services/profile/routes.py`):

| Method | Path                                                | Returns                                                   |
|--------|-----------------------------------------------------|-----------------------------------------------------------|
| GET    | `/v1/profile/{id}/cluster`                          | Primary identity cluster (confidence, membership)         |
| GET    | `/v1/profile/{id}/clusters`                         | All cluster memberships for this entity                   |
| GET    | `/v1/profile/{id}/identity-confidence`              | Confidence breakdown by identifier type                   |
| GET    | `/v1/profile/{id}/merge-history`                    | Historical merge events (pagination supported)            |
| GET    | `/v1/profile/{id}/split-history`                    | Historical split events (pagination supported)            |
| GET    | `/v1/profile/{id}/attribution`                      | Multi-touch attribution; supports `?window=`              |
| GET    | `/v1/profile/{id}/consent`                          | Consent state, allowed/blocked use cases, DSR state       |
| GET    | `/v1/profile/{id}/activation-eligibility`           | Whether the entity may be activated for a given use case  |
| GET    | `/v1/profile/{id}/quality`                          | Profile completeness, freshness, and confidence scores    |
| GET    | `/v1/profile/{id}/data-freshness`                   | Per-dimension freshness timestamps                        |
| GET    | `/v1/profile/{id}/data-status`                      | Canonical per-dimension `DimensionEnvelope` (state + reason + freshness) with a worst-wins `overall_state` |
| GET    | `/v1/profile/{id}/reconciliation`                   | Per-dimension expectation-vs-actual (declared min-events + freshness SLA against the actual reading), with `met` / `unmet_dimensions` |
| GET    | `/v1/profile/{id}/recommendations`                  | Active intelligence recommendations                       |
| GET    | `/v1/profile/{id}/outcomes`                         | Observed outcomes from executed recommendations           |
| GET    | `/v1/profile/{id}/outcome-ledger`                   | Paginated outcome ledger with attribution                 |
| GET    | `/v1/profile/{id}/agent-executions`                 | Agent executions owned or observed by this entity         |
| GET    | `/v1/profile/{id}/actions`                          | Discrete profile actions (pagination supported)           |
| GET    | `/v1/profile/{id}/events`                           | Profile-scoped events (alternative to timeline)           |

### Unified journey source evidence

`GET /v1/profile/{id}/unified-journey` preserves the generic `items` envelope
and also returns stable `steps` and `meta` fields for the Aether journey hook.
Each eligible step can include `source_class`, referral mediation, AI
provider/product, verification level, evidence confidence, classifier version,
and `attribution_eligible`. Net revenue is joined from the tenant's active,
immutable attribution credits by captured touchpoint ID; it is not inferred
from journey-step data. Discovery crawlers, scanners, link previews, and other
explicitly ineligible source evidence remain auditable in canonical activity
but are omitted from primary steps and counted in
`meta.excluded_source_noise_count`.

### Economic intelligence endpoints

All economic sub-routes accept `?window=30d|60d|90d|lifetime`:

| Method | Path                                                | Returns                                                   |
|--------|-----------------------------------------------------|-----------------------------------------------------------|
| GET    | `/v1/profile/{id}/economic`                         | Unified economic breakdown (Web2 + Web3 + Agentic)        |
| GET    | `/v1/profile/{id}/economic/web2`                    | TradFi economic breakdown                                 |
| GET    | `/v1/profile/{id}/economic/web3`                    | On-chain economic breakdown                               |
| GET    | `/v1/profile/{id}/economic/agentic`                 | Agentic economy breakdown (fees, x402 payments, rewards)  |
| GET    | `/v1/profile/{id}/economic/campaigns`               | Campaign-level economic attribution                       |
| GET    | `/v1/profile/{id}/economic/warnings`                | Economic risk flags for this entity                       |

Sensitive economic surfaces are consent-gated. The web2/credit surface
(`economic/web2`) evaluates a central consent `PolicyDecision`
(`services/policy`): its envelope summary carries a `policy_decision_id`, and on
missing `credit` consent it returns `{consent_required: true, granted: false,
policy_decision_id, redacted_fields}` rather than the data.

### Kyber Profile360 surface

The full Kyber operator surface (`ProfileComposer.get_profile360_surface`) is available at:

| Method | Path                                                | Returns                                                   |
|--------|-----------------------------------------------------|-----------------------------------------------------------|
| GET    | `/v1/profile360/{entity_type}/{entity_id}`          | Full kyber_internal surface — identity, system, financial, graph, timeline, analytics, debug |
| GET    | `/v1/profile/{entity_id}/agent`                     | Full agent profile (agent-specific view)                  |
| GET    | `/v1/profile/{entity_id}/agent/identity`            | Agent identity sub-section                                |
| GET    | `/v1/profile/{entity_id}/agent/delegation`          | Agent delegation chain                                    |
| GET    | `/v1/profile/{entity_id}/agent/subagents`           | Spawned sub-agents                                        |
| GET    | `/v1/profile/{entity_id}/agent/tasks`               | Current and historical tasks                              |
| GET    | `/v1/profile/{entity_id}/agent/tools`               | Tool inventory and usage stats                            |
| GET    | `/v1/profile/{entity_id}/agent/resources`           | MCP resources accessed                                    |
| GET    | `/v1/profile/{entity_id}/agent/x402`                | x402 payment activity                                     |
| GET    | `/v1/profile/{entity_id}/agent/trust`               | Agent trust score breakdown                               |
| GET    | `/v1/profile/{entity_id}/agent/outcomes`            | Agent execution outcomes                                  |
| GET    | `/v1/profile/{entity_id}/agent/graph`               | Agent graph context                                       |

The `kyber_internal` surface response carries `surface: "kyber_internal"` and
`visibility: "internal_full"`, signalling that no redaction has been applied.
End-user surfaces will require a separate redaction pass before exposure.
Every response includes `alignment_audit.end_user_surface_requires_redaction: true` as a guard.

Graph nodes returned by the Kyber surface include `profile_id`, `entity_type`,
`display_label`, and `profile_links` (with `summary` and `full` URLs) so the
frontend can open a Profile360 preview card directly from a graph node selection
without an additional round-trip.

### Intelligence extension endpoints

These endpoints are powered by `IntelligenceAggregator` (`services/profile/intelligence.py`)
and query the Gold-tier intelligence repositories.  All support `?window=30d|60d|90d|lifetime`.
When no Gold data exists for an entity they return an empty `items` list — never an error.

| Method | Path                                              | Returns                                                     |
|--------|---------------------------------------------------|-------------------------------------------------------------|
| GET    | `/v1/profile/{id}/tier`                           | Entity tier (Whale/Shark/Dolphin/Fish/Shrimp) + percentile  |
| GET    | `/v1/profile/{id}/asset-composition`              | On-chain portfolio by asset category + USD values           |
| GET    | `/v1/profile/{id}/pnl`                            | Realized + unrealized PNL, TVL delta (FIFO cost basis)      |
| GET    | `/v1/profile/{id}/trading-profile`                | Favorite pairs, protocol loyalty, gas strategy, slippage    |
| GET    | `/v1/profile/{id}/location-history`               | City-level location history with classification             |
| GET    | `/v1/profile/{id}/temporal-heatmap`               | 24×7 activity density matrix + streak data                  |
| GET    | `/v1/profile/{id}/social-intelligence`            | Cross-platform social (Twitter/Farcaster/Lens/Discord/GH)   |
| GET    | `/v1/profile/{id}/journey-economics`              | Per-journey ROAS, CPA, LTV, retarget score                  |
| GET    | `/v1/profile/{id}/device-performance`             | Conversion rate + avg value per device type                 |
| GET    | `/v1/profile/{id}/funnel`                         | Staged funnel (Impression→Click→Visit→Connect→Swap→LP)      |
| GET    | `/v1/profile/{id}/time-to-convert`                | Median + P90 time between funnel stage transitions          |
| GET    | `/v1/profile/{id}/retarget-recommendations`       | Pending/historical retargeting recommendations              |
| GET    | `/v1/profile/{id}/web2`                           | TradFi portfolio + credit signals (requires `credit` consent) |
| GET    | `/v1/profile/{id}/protocol-metrics`               | Protocol TVL, volume, fee revenue (DAO/DEX entity types)    |
| GET    | `/v1/profile/{id}/governance-activity`            | Governance proposals + votes (DAO/Protocol entity types)    |

The `/web2` and `/economic/web2` endpoints enforce `credit` consent via a **hard gate** at
the route layer: `require_consent(consent_repo, tenant_id, user_id, "credit")` is called
before any data is fetched.  Callers without an active `credit` consent grant receive
**HTTP 403** (`"Credit consent required for this resource"`).  This is a deliberate
fail-closed gate — not a soft empty-envelope fallback.

Gold-tier data is populated by external ETL pipelines (Moralis, CoinGecko, DeFiLlama, Snapshot,
Plaid).  Until an ETL pipeline has run for a given entity, these endpoints return an empty items
list — this is correct behavior, not an error.

Realtime fan-out for any of these dimensions is available via
`/v1/realtime/sse?entity_id={id}` and `/v1/realtime/ws?entity_id={id}`,
unchanged from before.

---

## Response envelope

Every drill endpoint (`summary` excepted, see below) returns the same
top-level shape:

```json
{
  "entity_id": "user-1",
  "tenant_id": "tenant-a",
  "kind": "wallets",
  "items": [
    {
      "id": "w-1",
      "type": "wallet",
      "displayLabel": "0xabc…",
      "chain": "evm",
      "address": "0xabc…",
      "timestamps": { "linkedAt": "2026-01-01T00:00:00Z" },
      "metadata": { "...": "raw row" },
      "links": { "transfers": "/v1/profile/user-1/flows" }
    }
  ],
  "summary": { "wallet_count": 1, "chains": ["evm"] },
  "pagination": { "limit": 100, "count": 1, "has_more": false },
  "computed_at": "2026-05-13T...Z",
  "provenance": { "sources": ["entity_wallets"] }
}
```

Items always include `id`, `type`, `displayLabel`, `timestamps`,
`metadata`, and `links`. The UI should depend only on this normalized
projection — not on the underlying repository row layout — so future
schema changes do not propagate to the client.

### `/summary` is shaped differently

`/summary` is the one endpoint that does not return a list. Instead it
returns a single `snapshot` object with:

- `entity` — the normalized canonical entity record
- `canonical_entity_id` — stable backend-assigned UUID from `services/identity/resolver.py`; falls back to `entity_id` if the identity system has not yet resolved this entity
- `counts` — pre-computed counts for every Profile 360 dimension
- `financials` — currency-safe inflow / outflow / net values. USD-first fields
  (`inflow_usd`, `outflow_usd`, `net_usd`, `settled_usd`, `rollup_status`,
  `by_native_currency`, `unpriced_count`) are canonical; legacy scalar fields
  (`inflow_total`, etc.) are deprecated and populated only for a single native
  currency (null when mixed — see
  [`FINANCIAL_VALUE_SEMANTICS.md`](source-of-truth/FINANCIAL_VALUE_SEMANTICS.md))
- `behavior` — latest behavior signals
- `links` — drill URLs for every other dimension

This is meant to power a header / tile bank in one call.

---

## Tenant isolation

Every aggregator method takes `tenant_id` and filters every repository
result on it before returning. Legacy rows with no `tenant_id` at all are
permitted (they pre-date the multi-tenant rollout) but the aggregator
inherits the existing `_compose_graph` alignment audit so operators can
backfill them. Cross-tenant rows are silently dropped, never surfaced.

The graph aggregator additionally respects the existing alignment audit
counters (`cross_tenant_neighbors_excluded`,
`legacy_unscoped_neighbors`).

---

## Graceful degradation

Every repository read inside the aggregator is wrapped in a `_safe()`
helper. If a backing store is briefly unavailable, the affected dimension
returns an empty list with the matching summary set to zero — the rest
of the response still succeeds. This keeps Profile 360 surfaces useful
during partial outages rather than 500-ing whole pages.

Degradation is reported, not hidden: the unified-journey envelope carries
`degraded_dimensions` (e.g. `attribution_credits` when the revenue join
failed), so zeroed attribution revenue reads as "unknown", never as a
verified zero.

The composer (`get_full_profile`) applies the same principle across its
dimensions: each is assembled under `asyncio.gather(return_exceptions=True)`,
so a single subsystem raising degrades only its own dimension to a typed
default. Rather than erasing the failure, the response carries an additive
`readiness` block — `{state: "ready" | "degraded", degraded_dimensions: [...]}`
— so callers can see which dimensions degraded and why.

The `/quality` and `/data-freshness` surfaces compute freshness for real: a
present dimension whose newest record exceeds the 24h freshness SLA is
reported stale (`stale_dimensions` / per-dimension `stale`), and
`contradiction_count` reflects the detected anomaly-flag count.

`/data-status` reports the same slices in the canonical **dimension-state**
vocabulary (`packages/shared/dimension-state.ts` ↔ `shared/dimension_state.py`,
parity-tested): each dimension is a `DimensionEnvelope`
(`{state, reason_code, freshness, count}`) whose state is one of `ready`,
`empty`, `partial`, `stale`, `insufficient_data`, `degraded`, `suppressed`,
`not_applicable`, `pending`, or `error`, and the surface rolls them into a
worst-wins `overall_state`. A dimension that fails to compute degrades to an
`error` envelope rather than 500-ing or silently reading empty
(`services/reconciliation/dimension_status.py`).

Staleness and sufficiency are judged **per dimension** from an expectation
registry (`services/reconciliation/expectations.py`): each dimension declares
its minimum volume and freshness SLA (sessions go stale in a day, a wallet link
stays fresh a week, campaign attribution a month). `/reconciliation` reports
that expectation against the actual reading per dimension — `met` /
`unmet_dimensions` — so an operator sees exactly which slices fall short and
why.

This is verified by `test_aggregator_degrades_on_repo_failure_without_raising`,
`tests/unit/test_profile_360_truth.py`, `tests/unit/test_dimension_status.py`,
and `tests/contracts/test_dimension_state_parity.py`.

---

## Drill semantics

`/v1/profile/{user_id}/drill/{object_type}/{object_id}` resolves any
related Profile 360 object and returns:

```json
{
  "entity_id": "user-1",
  "tenant_id": "tenant-a",
  "kind": "drill",
  "object_type": "agent",
  "object_id": "a-1",
  "found": true,
  "object": { "...raw record..." },
  "related": {
    "executions":     [ {...} ],
    "payment_intents":[ {...} ]
  },
  "computed_at": "..."
}
```

Supported object types:

| Object type          | Backing repository                |
|----------------------|-----------------------------------|
| `agent`              | `AgentConfigRepository`           |
| `wallet`             | `WalletRepository`                |
| `delegation`         | `DelegationRepository`            |
| `transfer` / `flow`  | `TransferRepository`              |
| `asset`              | `AssetRepository`                 |
| `entity`/`human`/`org` | `EntityRepository`              |
| `journey` / `chain`  | `JourneyChainRepository`          |
| `payment_intent`     | `PaymentIntentRepository`         |
| `settlement`         | `SettlementEventRepository`       |
| `agent_execution`    | `AgentExecutionRepository`        |

The drill route returns 404 when the record is not found or belongs to a
different tenant. Adding a new drillable type means adding a branch in
`Profile360Aggregator.drill` — no schema or route change required.

---

## Realtime composition

The aggregator is pull-based. For push updates, frontends subscribe to
`RealtimeHub` topics via SSE or WebSocket. The hub already fans out
every Profile 360 topic that mutates aggregator state:

- `ENTITY_CREATED`, `ENTITY_UPDATED`, `ENTITY_IDENTIFIER_LINKED/UNLINKED`
- `DELEGATION_CREATED`, `DELEGATION_REVOKED`
- `FLOW_TRANSFER`, `FLOW_WALLET_LINKED`
- `AGENT_EXECUTION_STARTED/COMPLETED/FAILED/RECOVERED`
- `BEHAVIOR_PROFILE_UPDATED`, `PROFILE_UPDATED`

A typical UI flow is:

1. Open SSE/WS subscription for the profile.
2. Call `/summary` for the initial paint.
3. On a relevant `<topic>` event, re-fetch the affected drill endpoint
   (e.g. `/wallets`, `/financials`) — not the entire summary — to keep
   bandwidth low.

---

## Migration strategy

The aggregator is **additive**, so there is no destructive migration.
Existing callers do not have to change anything. The recommended
incremental migration path is:

1. **Phase 1 — Co-existence (now).** New `/v1/profile/{id}/*` drill
   endpoints are live. The original `/v1/profile/{id}` omniview and the
   `/v1/profile360/{entity_type}/{entity_id}` Kyber surface continue to
   serve their existing clients.
2. **Phase 2 — Frontend cutover.** New Profile 360 UI surfaces (header
   tiles, drill panels, relationship explorer) call the aggregator
   directly. Legacy UI keeps calling the omniview.
3. **Phase 3 — Deprecate cross-service client joins.** Any frontend code
   that combines two or more direct service routes (e.g.
   `/v1/entities` + `/v1/flows/transfers`) for a single view migrates to
   the aggregator. Direct service routes remain available for writes and
   non-profile use cases.
4. **Phase 4 — Optional caching.** When `/summary` traffic dominates, the
   aggregator gains an opt-in cache decorator keyed on
   `(tenant_id, entity_id, dimension)`. The shape stays the same; only
   the source of the response changes.

No database migration is required. Every repository the aggregator reads
through is already provisioned. No new tables, no new topics, no new
columns.

---

## Extending the aggregator

To add a new dimension:

1. Add a method to `Profile360Aggregator` that returns the standard
   envelope from `_envelope(...)`. Use `_safe()` for every repository
   read.
2. Register the route under `services/profile/routes.py` following the
   pattern of the existing drill endpoints (tenant guard → aggregator
   call → `APIResponse`).
3. Add a row to the endpoints table above and a test in
   `tests/profile360/test_aggregator.py`.
4. If the new dimension changes when a topic fires, list that topic in
   `RealtimeHub.DEFAULT_TOPICS` so subscribers can refetch.

That's it — no graph schema change, no event schema change, no
repository change unless the underlying read pattern is new.

---

### Silver-backed sub-resource endpoints (v8.10.0+)

These endpoints read directly from Silver fact tables populated by the Silver projector layer.
They return `{entity_id, items, count, source, source_status}`. `source_status`
distinguishes three states honestly: `available` (rows returned), `empty`
(Silver consulted, no rows for this entity), and `missing` (the Silver read
failed — the empty list is *not* a confirmed absence). A store outage
degrades to an empty list with `source_status: "missing"` rather than
masquerading as confirmed-empty. All require the `read` permission on the
active tenant.

| Method | Path                              | Silver table                    | Returns                                    |
|--------|-----------------------------------|---------------------------------|--------------------------------------------|
| GET    | `/v1/profile/{id}/exposures`      | `silver_exposure_facts`         | Content and recommendation exposures       |
| GET    | `/v1/profile/{id}/revenue`        | `silver_revenue_facts`          | Revenue and subscription facts             |
| GET    | `/v1/profile/{id}/friction`       | `silver_friction_facts`         | UX friction observations                   |
| GET    | `/v1/profile/{id}/accounts`       | `silver_account_activity_facts` | B2B account activity facts                 |
| GET    | `/v1/profile/{id}/communications` | `silver_comms_facts`            | Communication facts (filterable: channel, category, direction, campaign, state, `human_qualified`; cursor paginated; includes summary counts) |
| GET    | `/v1/profile/{id}/communication-state` | `communication_state`      | Rebuildable per-channel state: subscription, deliverability, engagement counters, suppression scopes |
| GET    | `/v1/profile/{id}/integrations`   | `silver_server_operation_facts` | Integration and server operation facts     |
| GET    | `/v1/profile/{id}/data-quality`   | `silver_data_quality_facts`     | Data quality and schema completeness       |

### Economic intelligence sub-resource endpoints (v8.12.0+)

Observation-only economic sub-resources backed by the typed domain
repositories. Each is flag-gated by its domain's `profile360_enabled`
setting (`404` when the domain is disabled), requires the `read`
permission, is tenant-scoped, and serializes Decimals as strings. All
return `{entity_id, items, summary, count, computed_at, provenance}`.

| Method | Path                                   | Backing data                          | Attribution                                    |
|--------|----------------------------------------|---------------------------------------|------------------------------------------------|
| GET    | `/v1/profile/{id}/stablecoin`          | stablecoin observations               | entity refs / wallet ids on observations       |
| GET    | `/v1/profile/{id}/derivatives`         | derivatives positions + fills         | trading accounts with `owner_entity_id == id`  |
| GET    | `/v1/profile/{id}/interoperability`    | interop intents + asset legs          | initiator refs and from/to addresses           |

Silver fact tables are populated asynchronously by the `SilverDispatcher` projector chain
(`services/silver/dispatcher.py`), attached to `SDK_EVENTS_VALIDATED` via the
`silver_fact_projector` ingestion worker. One event may fan out to several projectors
(communications lifecycle first — ADR-C3); rows are persisted by
`services/silver/writer.py`. Until a projector has written records for a given entity the
endpoint returns `source_status: "empty"` — this is correct behavior, not an
error. A failed Silver read is reported as `source_status: "missing"` instead,
so consumers can tell "no data yet" from "could not check".

Communication items never contain raw addresses (tenant-scoped alias hashes with
redacted displays only) and carry machine-activity classification so reported
engagement and human-qualified engagement are always distinguishable.

### Card-linked activity sub-resource endpoints (v8.12.0+)

Card-linked (crypto-card) economic observability surfaces under
`Profile360 → Economic Activity → Payment Rails → Card-linked Activity`.
Gated by **both** `AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED` and
`AETHER_CARD_LINKED_PROFILE360_ENABLED` (`404` when either is off);
backed by `services/card_linked_payments/profile_summary.py`.

| Method | Path                                              | Purpose                                                            |
|--------|---------------------------------------------------|--------------------------------------------------------------------|
| GET    | `/v1/profile/{id}/card-linked-activity`           | Summary, filtered flows, and the entity story (campaign → provider → top-up → spends) |
| GET    | `/v1/profile/{id}/economic/card-linked`           | Alias of the above under the economic sub-tree                     |
| GET    | `/v1/profile/{id}/drill/card-linked/{object_id}`  | Single-flow drilldown with evidence refs, provenance, reconciliation records |

Every row carries `basis` (`topup`/`funding`/`spend`/`settlement`/`clearing`/
`refund`/`reversal`/`mixed`/`benchmark_only`/`unknown`), `source`, and
`confidence`; top-up and spend are never merged, and a top-up-only entity
response includes an explicit "top-up volume is not card spend" warning.
Filters: program/issuer/network/basis/source/confidence/chain/asset/
campaign/journey plus `volume_min`/`volume_max`/`since`/`until`. The
card-linked drill route is registered before the generic
`/drill/{object_type}/{object_id}` route so it wins path matching.

---

## Agentic Observability Dimensions (v8.9.0+)

The Agentic Observability Layer writes to `obs_*` repositories that Profile 360
can surface as additional read dimensions on `agent` entity types. These are
**observation-only** — all data was recorded by the observability ingestion layer,
never executed by AETHER.

Planned future drill-down endpoints for agent profiles:

| Endpoint | Description | Source Repository |
|----------|-------------|-------------------|
| `GET /v1/profile/{id}/agent/mcp-connections` | MCP server connections observed for this agent | `obs_agent_mcp_connections` |
| `GET /v1/profile/{id}/agent/activities` | Observed activity timeline | `obs_agent_activities` |
| `GET /v1/profile/{id}/agent/risk-signals` | Risk signals produced from observations | `obs_agent_risk_signals` |
| `GET /v1/profile/{id}/agent/inboxes` | Observed agent inboxes | `obs_agent_inboxes` |
| `GET /v1/profile/{id}/agent/x402-interactions` | Observed x402 protocol interactions | `obs_x402_interactions` |
| `GET /v1/profile/{id}/agent/trade-observations` | Observed trade intents and orders | `obs_trade_observations` |
| `GET /v1/profile/{id}/agent/portfolio-snapshots` | Observed portfolio state | `obs_portfolio_snapshots` |

**Clarification on "agent executions" dimension:** The existing
`GET /v1/profile/{id}/agent-executions` endpoint reads `AgentExecutionRepository`,
which stores externally-observed agent task outcomes. AETHER records these
observations but does not originate, authorize, or execute any of the tasks itself.
## Dependency availability and tenant expectations

Profile360 dependency reads use `DimensionReadResult` so a legitimate empty
dimension remains `available`, while a failed repository read is
`unavailable` with a stable error code. Summary, quality, and freshness
responses surface dependency status instead of making an outage
indistinguishable from “this tenant has no data.”

Dimension readiness expectations inherit checked-in defaults and can be
overridden per tenant through
`config/reconciliation_expectations.json`. Overrides are validated and scoped
by exact tenant id; an invalid operator configuration fails closed.

Tenant SDK coverage uses an exact census when the population fits under the
configured threshold. Larger tenants use a deterministic hash-ranked sample over
the complete tenant population—not the first N rows. Responses report population
size, method, seed version, and per-dimension Wilson confidence intervals.
Coverage is nullable for an empty or unavailable sampling frame; it is never
invented as zero.
