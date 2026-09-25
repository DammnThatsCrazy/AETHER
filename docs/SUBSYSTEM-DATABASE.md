---
title: PostgreSQL / Repository Subsystem
slug: data/postgres
section: architecture
visibility: P
audience: [dev-senior, architect, ops]
status: stable
since_version: 0.1.0
source_files: [services/backend/repositories/repos.py, services/backend/repositories/lake.py]
canonical_owner: backend@aether
estimated_read_minutes: 5
toc_depth: 3
reviewed_source_commits:
  - {'commit': '54eaac5d', 'reason': 'Reviewed the staging first-admin bootstrap change; repository and database behavior remain unchanged.'}
source_hashes:
  "services/backend/repositories/lake.py": "sha256:88bf547d48f6e7daebde249ed6c16805fa9ff9d6462a2e4637bea89924cf5fdd"
  "services/backend/repositories/repos.py": "sha256:fa4001b9bad9ad493abce62503686d163770a5b4440e667df626c134273d6ad0"
---

# PostgreSQL / Repository Subsystem

## Architecture

All relational data is stored via the repository pattern in `repositories/repos.py`. Each service uses typed repository classes that abstract query logic.

**Backend selection:**
- `AETHER_ENV=local` → in-memory Python dicts
- `AETHER_ENV=staging/production` → PostgreSQL via `asyncpg`

## Schema

All tables use a JSONB document model with auto-creation:

```sql
CREATE TABLE IF NOT EXISTS {table_name} (
    id TEXT PRIMARY KEY,
    data JSONB NOT NULL DEFAULT '{}',
    tenant_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_{table_name}_tenant
ON {table_name} (tenant_id);
```

Tables are created automatically on first access when no migration has
created them. Most tables are now owned by Alembic migrations; runtime
auto-creation is only a bootstrap fallback for a table that doesn't exist yet:

- `_ensure_table` runs under a per-table transaction-scoped advisory lock
  (`pg_advisory_xact_lock(hashtextextended('aether.base_repository.ensure_table:<table>', 0))`).
  Postgres `CREATE TABLE/INDEX IF NOT EXISTS` is not safe under concurrency:
  the API and each worker loop build their own repository instances, and they
  used to fail with `duplicate key value violates unique constraint
  "pg_class_relname_nsp_index"` on a fresh database.
- If the table already exists (for example `reward_delivery_jobs` from
  `20260828_reward_delivery_tables`), no DDL is issued. The table keeps the
  schema and indexes the migration gave it, and doesn't gain a duplicate
  runtime `idx_<table>_tenant` index.

### Explicit-column repositories

Repositories whose migration creates named columns instead of a `data` JSONB
column set `_jsonb_mode = False`. This applies to
`NotificationIntelligenceRepository`, `OperatorActionRepository`,
`TenantNotificationConfigRepository`, `UserNotificationChannelRepository`,
`SlackOAuthStateRepository`, and the ten identity-resolution stores in
`services/identity/repository.py`. For these tables the repository reads the column
set and each column's `data_type` from `information_schema.columns` once per
table and caches it. Writes and filters are then bound to the migrated types:

- `find_many()` without `sort_by` orders by the repository's `_default_sort`.
  `notification_intelligence_events` has `detected_at` and no `created_at`, so
  it sorts by `detected_at`. If a caller asks for a sort column the table
  doesn't have, the query falls back to `_default_sort`.
- `insert()`/`update()` drop the `created_at`/`updated_at` stamps when the table
  has no such column.
- ISO-8601 strings for `timestamptz` columns are bound as aware UTC datetimes.
  This uses the lenient rule in `shared.temporal.instant.coerce_utc_lenient`.
- Only `json`/`jsonb` columns get a JSON cast. Array columns such as `text[]`
  receive the Python list.
- Boolean filters are bound as booleans.
- json/jsonb columns are decoded on read.
- A `None` for a `NOT NULL` column that has a server default is left out of
  the write, so the default or the existing value applies.
- `_payload_column` (optional) names a JSONB column that holds record keys the
  table has no column for. On read it is unpacked back into the flat record,
  and filters on those keys use `<payload>->>'key'`. Without it, an unknown key
  still fails loudly in Postgres.
- `_column_renames` (optional) maps a historical record key to the migrated
  column name. Reads expose both names.

## Tables

| Table | Repository Class | Used By |
|-------|-----------------|---------|
| `profiles` | `IdentityRepository` | Identity service |
| `events` | `AnalyticsRepository` | Analytics service, Profile 360 timeline — one row per processed SDK event, written by the `analytics_event_recorder` stream projector |
| `sessions` | `AnalyticsRepository` (rows with `record_type = analytics_session`), `SessionRepository` (fraud) | Analytics session rollup written by `analytics_event_recorder`; fraud detectors read their own rows by `entity_id` |
| `campaigns` | `CampaignRepository` | Campaign service |
| `consent_records` | `ConsentRepository` | Consent service |
| `webhooks` | `WebhookRepository` | Notification service (legacy) |
| `alerts` | `AlertRepository` | Notification service (legacy) |
| `tenants` | `AdminRepository` | Admin service |
| `users` | `UserRepository` | Auth (email+password signup, OTP, SSO via Auth0) |
| `api_keys` | `APIKeyRepository` | Admin service |
| `first_admin_bootstrap` | `FirstAdminBootstrapRepository` | Durable staging first-admin claim (key hash + request binding; identical retries only) |
| `provider_usage` | `UsageMeter` | Provider gateway |
| `investigations` | `InvestigationRepository` | Investigation service |
| `governance_decisions` | `GovernanceRepository` | Governance service |
| `event_replay_jobs` | `EventReplayRepository` | Events replay worker |
| `event_envelopes` | `EventEnvelopeRepository` | Events service |
| `providers` | `ProvidersRepository` | BYOK vault — encrypted channel credentials |
| `notification_intelligence_events` | `NotificationIntelligenceRepository` | Notification intelligence pipeline |
| `tenant_notification_configs` | `TenantNotificationConfigRepository` | Per-tenant notification routing config |
| `operator_actions` | `OperatorActionRepository` | Operator approve/suppress/escalate/annotate audit |
| `user_notification_channels` | `UserNotificationChannelRepository` | End-user Slack/Discord/Telegram/Webhook registrations |
| `slack_oauth_states` | `SlackOAuthStateRepository` | Slack OAuth 2.0 CSRF state nonces (10-min TTL) |
| `agent_executions` | `AgentExecutionRepository` | Per-execution reasoning log, confidence, policy log, task decomposition |
| `delegations` | `DelegationRepository` | Scoped, time-bound, revocable entity-to-entity delegations (hot-path Redis-cached) |
| `payment_intents` | `PaymentIntentRepository` | Pre-execution economic decisions: quotes, retries, budget eval, authorizations, settlements — full intent-to-outcome chain, tenant-scoped |
| `settlement_events` | `SettlementEventRepository` | Settlement attempts and terminal outcomes for PaymentIntent records, tenant-scoped |
| `economic_resources` | `EconomicResourceRepository` | Purchasable capabilities: inference, GPU compute, APIs, data, memory |
| `facilitators` | `FacilitatorRepository` | x402 facilitators, trust brokers, and authorization rails |
| `agent_economic_identities` | `AgentEconomicIdentityRepository` | Derived long-running economic identity per agent, keyed as `{tenant_id}:{agent_id}:economic_identity` |

**Tenant isolation enforcement:** The following repository methods require an explicit `tenant_id` argument (no default) — callers must always pass the tenant from request context:
- `AgentExecutionRepository.list_for_agent(agent_id, tenant_id)`
- `PaymentIntentRepository.list_for_agent(agent_id, tenant_id)`
- `SettlementEventRepository.list_for_agent(agent_id, tenant_id)`
- `SettlementEventRepository.list_for_intent(intent_id, tenant_id)`
- `DelegationRepository.active_for(grantee_entity_id, tenant_id)`

### Analytics event store

`AnalyticsRepository` reads the `events` and `sessions` tables; the
`analytics_event_recorder` projector (`services/ingestion/workers.py`, on the
`stream-ingestion-projection` consumer) is their only production writer.

- **Row identity:** `analytics_event_record_id(tenant_id, event_id)` and
  `analytics_session_record_id(tenant_id, session_id)` are tenant-scoped
  SHA-256 digests. `record_processed_event` inserts the event with
  `ON CONFLICT DO NOTHING` and, in the same transaction and only for a new
  row, upserts the session rollup (`first_seen_at`, `last_seen_at`,
  `event_count`, `page_views` = `page` / `screen` events), so at-least-once
  redelivery changes nothing.
- **Event row:** `tenant_id`, `event_id`, `event_type`, `event_family`,
  `session_id`, `anonymous_id`, `user_id`, `occurred_at` / `received_at`
  (fixed-width UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`), `schema_version`, `source`
  and a scalar, PII-filtered `properties` subset. SDK `context` is never stored.
- **Queries:** `query_events(tenant_id, params, limit)` always binds the
  request tenant (a `tenant_id` in `params` is ignored; an empty tenant returns
  nothing), matches `event_type` / `user_id` / `session_id` / ... by equality,
  and bounds `occurred_at` with `start_date` / `end_date` (inclusive; a
  date-only bound covers the whole day). `limit` is never a row predicate.
  Non-empty results are cached for up to 5 minutes under the tenant's query
  generation (`CacheKey.analytics_query_generation`), a token folded into every
  cached key. Each newly recorded event (and `record_event`) replaces the
  token after its write commits, so the next read of any query misses and sees
  the event; old entries age out under their TTL. The replacement is
  best-effort (a cache outage never fails a committed write; staleness is then
  TTL-bounded), and a missing token reads as `"0"`, never as a token a write
  issued. Concurrent identical misses in one process share a single store read.
  Empty results are never cached.
- **Session rollups:** `query_sessions(tenant_id, params, limit)` reads the
  tenant's analytics `sessions` rollups (never fraud rows), most recently
  active first, filtered by `session_id` / `user_id` / `anonymous_id`, and adds
  the derived `duration` in seconds. It backs the `sessions` root of
  `POST /v1/analytics/graphql` and is not cached.
- **Dashboard summary:** `dashboard_summary(tenant_id)` runs two aggregate
  statements over the tenant's `events` rows processed in the last 24 hours
  (`created_at` window, bounded by the `tenant_id` index) for `total_events`,
  `unique_users` (distinct `user_id`, else `anonymous_id`) and the ten most
  frequent `top_event_types`, plus one count of analytics sessions updated in
  the window for `total_sessions`. `tenant_id=None` summarises all tenants
  (Kyber cross-tenant scope).
- **DSR erasure:** `erase_subject(tenant_id, user_id, anonymous_id=None)`
  backs the `analytics_events` DSR propagation component, run by the
  `consent.erasure` job for `POST /v1/consent/dsr` erasure requests (the
  request's optional `anonymous_id` is passed through). In one transaction and
  always within the requesting tenant it hard-deletes (the tenant-erasure
  semantics for these tables) every `events` row whose `user_id` or
  `anonymous_id` is the subject's, and every analytics session rollup
  attributed to either identity. A rollup attributed to another identity that
  counted the subject's events is recomputed (`event_count`, `page_views`,
  first/last seen) from its remaining events, or deleted when none remain. Other users' sessions and other tenants' rows (even
  with the same `user_id`) are never touched; a re-run erases nothing. The step
  receipt is `records_impacted` = events + session rollups deleted and
  `artifacts_impacted` = rollups recomputed, with the job id as the audit
  pointer. The tenant's cached query results are then dropped and its query
  generation replaced; if that fails, the step is marked `failed` and the job
  retries.
- **DSR delete primitive:** `BaseRepository.delete_for_tenant_where(tenant_id,
  field, values)` hard-deletes the tenant's rows whose `field` equals any of
  `values` in one statement. `tenant_id = $1` is always part of the
  predicate, and an empty tenant or an invalid field name raises. JSONB tables
  match `data->>'field'`; explicit-column tables use the column, including
  `_column_renames`, or the `_payload_column` key. A retry deletes nothing. The
  `consent.erasure` completeness planes use it for the identity, Profile 360,
  Gold feature, connector and replay stores
  (`docs/privacy/dsr-erasure-coverage.md`).

## Data Lake Repositories

`repositories/lake.py` implements the Bronze / Silver / Gold medallion tiers using the same
`BaseRepository` pattern (in-memory locally, asyncpg in production).

**Domain instances** (Bronze + Silver + Gold for each):

| Domain | Gold instance | Purpose |
|--------|--------------|---------|
| `market` | `gold_market` | Market price + volume data |
| `onchain` | `gold_onchain` | On-chain events + wallet data |
| `social` | `gold_social` | Cross-platform social data |
| `identity` | `gold_identity` | Identity enrichment |
| `governance` | `gold_governance` | DAO governance records |
| `tradfi` | `gold_tradfi` | TradFi raw data |
| `sdk_events` | — | Bronze + Silver tiers for `POST /v1/batch` SDK event ingestion (no Gold; consumed by intelligence workers) |
| `connector_events` | — | Bronze-only tier for `ConnectorService.sync()` pulled events (`bronze_connectors` in `repositories/lake.py`); no Silver/Gold — same consumer path as `sdk_events` |
| `dune` | `DuneGoldRepository` | Bronze→Silver→Gold Dune API data with per-row SHA-256 provenance, quality scoring, and idempotent Gold materialization (`DuneBronzeRepository`, `DuneSilverRepository`, `DuneGoldRepository` in `repositories/repos.py`) |

**Intelligence surface repos** (Gold only, consumed by `IntelligenceAggregator`):

| Gold instance | Source (ETL) | Profile 360 endpoint |
|--------------|-------------|----------------------|
| `gold_entity_tiers` | Internal scorer | `/tier` |
| `gold_asset_composition` | Moralis | `/asset-composition` |
| `gold_entity_pnl` | CoinGecko + silver_web3_events | `/pnl` |
| `gold_trading_profile` | silver_web3_events | `/trading-profile` |
| `gold_location_history` | Analytics events | `/location-history` |
| `gold_temporal_heatmap` | Analytics events | `/temporal-heatmap` |
| `gold_social_intelligence` | Twitter, Farcaster, Lens, Discord, GitHub | `/social-intelligence` |
| `gold_journey_economics` | gold_ad_spend + journey chains | `/journey-economics`, `/funnel`, `/device-performance`, `/time-to-convert`, `/retarget-recommendations` |
| `gold_ad_spend` | Campaign tracking | (input to journey economics) |
| `gold_credit_signals` | Plaid | `/web2` (credit consent required) |
| `gold_tradfi_portfolio` | Plaid | `/web2` (credit consent required) |
| `gold_web3_daily_metrics` | DeFiLlama | `/protocol-metrics` |

`BronzeRepository.ingest()` returns `(record, is_new: bool)` — callers use the boolean to distinguish new inserts from duplicates without a separate read. Bronze records carry a provenance envelope: `provenance_status`, `license_status`, `terms_status`, `commercial_use_status`, `model_training_status`, `quarantine_status`, and `raw_payload_hash` (SHA-256 of raw payload). Records with `license_status="missing"` or `provenance_status` not equal to `VALID` are automatically set to `quarantine_status="quarantined"`. Cleared license statuses (`valid`, `public_api`, `open_license`, `enterprise_contract`) combined with cleared terms statuses (`approved`, `public_api`, `open_license`, `enterprise_contract`, `valid`) yield `provenance_status=VALID` and bypass quarantine.

`SilverRepository.upsert_record()` includes `tenant_id` in the `record_id` hash (`SHA256(tenant_id:entity_type:entity_id:source)[:24]`) to prevent cross-tenant data collisions. `SilverRepository.check_promotion_eligibility(bronze_record)` enforces the promotion gate: quarantined Bronze records cannot be promoted to Silver (returns `(False, reason)` with the blocking reason).

Gold records use `GoldRepository.materialize(metric_name, entity_id, value, dimensions)` with optional `lineage_id`, `source_manifest_ids`, and `model_training_eligible` parameters that attach enrichment lineage to Gold artifacts.
The `IntelligenceAggregator` queries via `get_metrics(entity_id)` and applies
`?window=30d|60d|90d|lifetime` filtering on the `materialized_at` timestamp.

## Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DATABASE_URL` | Yes (staging/prod) | — | PostgreSQL connection string |

## Connection Pool

`asyncpg.create_pool()` with:
- `min_size=2`, `max_size=20`
- `command_timeout=30`
- `statement_cache_size=100`

Pool is created once at startup via `get_pool()` and closed at shutdown via `close_pool()`.

## Health Check

Database health is probed via `SELECT 1` in `ResourceRegistry.health_check()`. Exposed as `database` in `GET /v1/health`.

## Failure Modes

- `DATABASE_URL` not set in production → `RuntimeError` at startup
- `asyncpg` not installed in production → `RuntimeError` at startup
- PostgreSQL unreachable in local → falls back to in-memory dicts

## Fraud Intelligence Repositories

Six repositories were added to `repositories/repos.py` for the fraud intelligence subsystem. All follow `BaseRepository` and use the same in-memory / DynamoDB / Postgres dispatch:

| Repository | Store Key | Primary Use |
|-----------|-----------|------------|
| `FraudNetworkRepository` | `fraud_networks` | Fraud network records indexed by `id` + `tenant_id` |
| `FraudNetworkMemberRepository` | `fraud_network_members` | Per-network member records with `entity_id`, `role`, `risk_score` |
| `FraudNetworkEdgeRepository` | `fraud_network_edges` | Transfer edges projected into fraud network graph |
| `FlowTraceRepository` | `flow_traces` | Flow trace execution records |
| `FlowTracePathRepository` | `flow_trace_paths` | Individual BFS paths discovered per trace |
| `RiskOverlaySnapshotRepository` | `risk_overlay_snapshots` | Cytoscape-ready overlay snapshots for graph rendering |

All stores are tenant-scoped: every `list_by_tenant` / `list_by_network` / `list_by_trace` query includes `tenant_id` in the filter. Cross-tenant queries at the repository level are not possible — `find_many(filters={"tenant_id": ...})` enforces isolation before any result is returned.
- Query timeout → `asyncpg.exceptions.QueryCanceledError` after 30s
