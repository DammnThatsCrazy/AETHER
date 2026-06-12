---
title: PostgreSQL / Repository Subsystem
slug: data/postgres
section: data
visibility: P
audience: [dev-senior, architect, ops]
status: stable
since_version: "8.8.0"
source_files:
  - Backend Architecture/aether-backend/repositories/repos.py
  - Backend Architecture/aether-backend/repositories/lake.py
canonical_owner: backend@aether
estimated_read_minutes: 5
toc_depth: 3
last_synced_commit: 828e055
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

Tables are created automatically on first access. No migration tool is required for the JSONB model.

## Tables

| Table | Repository Class | Used By |
|-------|-----------------|---------|
| `profiles` | `IdentityRepository` | Identity service |
| `events` | `AnalyticsRepository` | Analytics service |
| `sessions` | `AnalyticsRepository` | Analytics service |
| `campaigns` | `CampaignRepository` | Campaign service |
| `consent_records` | `ConsentRepository` | Consent service |
| `webhooks` | `WebhookRepository` | Notification service (legacy) |
| `alerts` | `AlertRepository` | Notification service (legacy) |
| `tenants` | `AdminRepository` | Admin service |
| `users` | `UserRepository` | Auth (email+password signup, OTP, SSO via Auth0) |
| `api_keys` | `APIKeyRepository` | Admin service |
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

`BronzeRepository.ingest()` returns `(record, is_new: bool)` — callers use the boolean to distinguish new inserts from duplicates without a separate read. `SilverRepository.upsert_record()` includes `tenant_id` in the `record_id` hash (`SHA256(tenant_id:entity_type:entity_id:source)[:24]`) to prevent cross-tenant data collisions.

Gold records use `GoldRepository.materialize(metric_name, entity_id, value, dimensions)`.
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
- Query timeout → `asyncpg.exceptions.QueryCanceledError` after 30s
