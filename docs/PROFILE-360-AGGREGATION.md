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
canonical_owner: backend@aether
estimated_read_minutes: 8
toc_depth: 3
last_synced_commit: 9b8116d
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
| GET    | `/v1/profile/{id}/behavior`                                | Latest derived behavior snapshot                   |
| GET    | `/v1/profile/{id}/predictions`                             | Predicted next + anomaly flags                     |
| GET    | `/v1/profile/{id}/rewards`                                 | Rewards earned                                     |
| GET    | `/v1/profile/{id}/platforms`                               | Platform attribution                               |
| GET    | `/v1/profile/{id}/protocols`                               | Protocol interactions                              |
| GET    | `/v1/profile/{id}/devices`                                 | Devices (deterministic + observed)                 |
| GET    | `/v1/profile/{id}/sessions`                                | Sessions with rollups                              |
| GET    | `/v1/profile/{id}/financials`                              | Inflow/outflow/settlement summary                  |
| GET    | `/v1/profile/{id}/delegations`                             | Granted / received delegations                     |
| GET    | `/v1/profile/{id}/relationships`                           | Typed normalized relationships                     |
| GET    | `/v1/profile/{id}/drill/{object_type}/{object_id}`         | Generic deep drill                                 |
| GET    | `/v1/profile/{id}/identifiers`                             | All linked identifiers                             |
| GET    | `/v1/profile/{id}/provenance`                              | Source attribution                                 |
| GET    | `/v1/profile/{id}/intelligence`                            | Risk + features + models                           |
| GET    | `/v1/profile/{id}/lake/{domain}`                           | Gold-tier lake data                                |
| GET    | `/v1/profile/{id}/flows`                                   | Asset transfers (raw list)                         |
| GET    | `/v1/profile/{id}/campaigns`                               | Campaign attribution (derived from event stream)   |
| GET    | `/v1/profile/resolve`                                      | Resolve any identifier to canonical id             |

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

The `/web2` endpoint enforces `credit` consent via `ConsentRepository` before serving any
TradFi or credit data.  Entities without consent receive `{"items": [], "summary": {"consent_required": true}}`.

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
- `counts` — pre-computed counts for every Profile 360 dimension
- `financials` — inflow / outflow / net totals
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

This is verified by `test_aggregator_degrades_on_repo_failure_without_raising`.

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
