---
title: PostgreSQL / Repository Subsystem
slug: data/postgres
section: architecture
visibility: P
audience: [dev-senior, architect, ops]
status: stable
since_version: 0.1.0
source_files:
  - services/api/repositories/repos.py
  - services/api/repositories/tenant_row_keys.py
  - services/api/repositories/lake.py
  - services/api/repositories/commerce_repos.py
  - services/api/actions/agent/user_agents.py
  - services/api/value/economic/ai_aggregation.py
  - services/api/intelligence/workflow/workflow360_provider.py
  - services/api/value/x402/commerce_store.py
  - services/api/intelligence/risk360/store.py
  - services/api/actions/agent_marketplace/identity_binding.py
  - services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py
  - services/api/alembic/versions/20261011_agent_delegated_to_namespace.py
  - services/api/alembic/versions/20261022_execution_approval_decisions.py
  - services/api/alembic/versions/20261022_risk_poisoning_evidence.py
canonical_owner: backend@aether
estimated_read_minutes: 5
toc_depth: 3
reviewed_source_commits:
  - {'commit': '54eaac5d', 'reason': 'Reviewed the staging first-admin bootstrap change; repository and database behavior remain unchanged.'}
  - {'commit': '30d10ccb6', 'reason': 'Reviewed CSV import rights-lineage persistence. The body now documents the additive Bronze metadata and silver_import_facts JSONB refs/record IDs; other repository and database dispatch behavior is unchanged.'}
source_hashes:
  "services/api/actions/agent/user_agents.py": "sha256:e00d936cb05ab3ba530c9208a98932e45dec4b1175330d8d24aa8d87a13cc81c"
  "services/api/actions/agent_marketplace/identity_binding.py": "sha256:0508f1094a8d369cd6c02004a18456c4b21b3b15f7160742d0ba6c9155aae352"
  "services/api/alembic/versions/20261011_agent_delegated_to_namespace.py": "sha256:446edfe924829cc75d627af169fb12c975f11f2ab13cf17b735ff14a8fed1c10"
  "services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py": "sha256:ab8553556c2c9d6e0e46fe55899132946dcfef9c432b8aed72d394da8e5a3269"
  "services/api/alembic/versions/20261022_execution_approval_decisions.py": "sha256:6f3c2ff0235a78fd144f0b26bb76a36556c23a1bc5a8285e58588608e9fa7fb6"
  "services/api/alembic/versions/20261022_risk_poisoning_evidence.py": "sha256:d158801954e2c76f088f9a367cabc4e507f1d4b2e456e989b6e95c04a9db6237"
  "services/api/intelligence/risk360/store.py": "sha256:447475ba55bc70319c134fcd9f8886d37d9913c27d7a7ae406c721159618b2db"
  "services/api/intelligence/workflow/workflow360_provider.py": "sha256:5a338c0e96e8af181e6e0cdbab061c7ded7333535bec55706cd8908de20bcbc9"
  "services/api/repositories/commerce_repos.py": "sha256:4402087f991786d8c2e67663f215fc3793694e2f0956bfba6fbe197386c7e518"
  "services/api/repositories/lake.py": "sha256:ba4cb42e94ad7934f9063111efbe670be93c48181deaed45f058fc3343fe0109"
  "services/api/repositories/repos.py": "sha256:1784df01b61c04f087c80397c3eab3b7167aef930bf199b7a82da4bfdc18dbf4"
  "services/api/repositories/tenant_row_keys.py": "sha256:e2da7b934edd8738e078817b9f01d52040624242f0f2d78c113bf76dc7fcf4e0"
  "services/api/value/economic/ai_aggregation.py": "sha256:1c9a65985225dc3c25bb5f628610390cde15271dc320c0af6e0a2bbedd98c82f"
  "services/api/value/x402/commerce_store.py": "sha256:9f6e098c5d2ad930d3d1cf090d10c9386e6bae0408ad39c5b21e22ff460c1a06"
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
`services/api/identity/identity/repository.py`. For these tables the repository reads the column
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
| `event_envelopes` | `EventEnvelopeRepository` (rows keyed `{tenant}:{envelope id}`) | Events service |
| `providers` | `ProvidersRepository` | BYOK vault — encrypted channel credentials |
| `notification_intelligence_events` | `NotificationIntelligenceRepository` | Notification intelligence pipeline |
| `tenant_notification_configs` | `TenantNotificationConfigRepository` | Per-tenant notification routing config |
| `operator_actions` | `OperatorActionRepository` | Operator approve/suppress/escalate/annotate audit |
| `user_notification_channels` | `UserNotificationChannelRepository` | End-user Slack/Discord/Telegram/Webhook registrations |
| `slack_oauth_states` | `SlackOAuthStateRepository` | Slack OAuth 2.0 CSRF state nonces (10-min TTL) |
| `agent_executions` | `AgentExecutionRepository` | Per-execution reasoning log, confidence, policy log, task decomposition, and optional exact workflow-run/invocation references |
| `commerce_approval_decisions` | `ApprovalDecisionsRepository` | Append-only tenant-scoped x402 decision history with exact execution references |
| `risk_poisoning_evidence` | `RiskPoisoningEvidenceRepository` | Typed tenant-scoped risk evidence and append-only lifecycle/restatement history |
| `delegations` | `DelegationRepository` | Scoped, time-bound, revocable entity-to-entity delegations (hot-path Redis-cached) |
| `payment_intents` | `PaymentIntentRepository` | Pre-execution economic decisions: quotes, retries, budget eval, authorizations, settlements — full intent-to-outcome chain, tenant-scoped; authorization and execution references are retained on the source row when explicitly supplied |
| `settlement_events` | `SettlementEventRepository` | Settlement attempts and terminal outcomes for PaymentIntent records, tenant-scoped |
| `economic_resources` | `EconomicResourceRepository` | Purchasable capabilities: inference, GPU compute, APIs, data, memory |
| `facilitators` | `FacilitatorRepository` | x402 facilitators, trust brokers, and authorization rails |
| `agent_economic_identities` | `AgentEconomicIdentityRepository` | Derived long-running economic identity per agent, keyed as `{tenant_id}:{agent_id}:economic_identity` |
| `agent_deployment_identity_bindings` | `AgentDeploymentIdentityBindingRepository` | Explicit tenant-admin binding from source namespace/reference to a same-tenant canonical Agent; uniquely scoped by tenant + namespace + source reference |

**Agent deployment identity bindings:** The additive
`20261011_agent_deployment_identity_bindings` migration creates the durable
binding store and its tenant/namespace/source-reference uniqueness guard. Each
binding records the canonical Agent ID and explicit `tenant_admin_explicit`
authority. The identity-binding service revalidates tenant ownership and the
current deployment source reference before returning a match; missing,
ambiguous, stale, or cross-tenant rows are unresolved. A follow-on migration adds the nullable
`delegated_to_namespace` column to `silver_agent_execution_facts`, so target
source references retain their own declared namespace and cannot inherit the
actor's namespace. These migration files are authored in the branch; this page
does not claim that either has been applied.

**Tenant isolation enforcement:** The following repository methods require an explicit `tenant_id` argument (no default) — callers must always pass the tenant from request context:
- `AgentExecutionRepository.list_for_agent(agent_id, tenant_id)`
- `PaymentIntentRepository.list_for_agent(agent_id, tenant_id)`
- `SettlementEventRepository.list_for_agent(agent_id, tenant_id)`
- `SettlementEventRepository.list_for_intent(intent_id, tenant_id)`
- `DelegationRepository.active_for(grantee_entity_id, tenant_id)`

`EntityRepository.find_many_for_tenant_entity_ids(tenant_id, entity_ids)` is a
bounded exact lookup used to resolve Agent360 delegation parties. It filters
by the requested tenant and exact canonical entity IDs; duplicate or
truncated results are not selected as canonical. `AgentExecutionRepository`
also retains the initiating principal ID supplied by the authenticated
server-side execution path so it remains distinct from the agent and source
actor claims. It persists `workflow_run_id` and `workflow_run_invocation_ids`
when canonical tenant-scoped invocation facts with the same agent and an exact
`action_id` equal to the stable execution ID resolve to one unambiguous run.
Workflow360 revalidates the tenant, run, agent, action, and invocation IDs
before exposing an execution as a workflow step; absent or ambiguous links stay
unknown. It also resolves a stored `triggered_by_event_id` only when the exact
tenant-scoped analytics event exists. This exposes the recorded reference with
event and execution evidence; it does not establish event-to-run causality or
complete trigger coverage. These fields use the existing JSONB record and
require no migration. Workflow360 additionally follows only `outcome_id`
references on the exact tenant/run invocation facts to
`OutcomeTruthStore.get(tenant_id, outcome_id)`. It validates the canonical
outcome scope and evidence, carries the invocation IDs as association lineage,
and does not infer run causality; the outcome store's feature flag gates the
read. Policy and freshness remain unknown.

### Analytics event store

`AnalyticsRepository` reads the `events` and `sessions` tables; the
`analytics_event_recorder` projector (`services/api/ingestion/ingestion/workers.py`, on the
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
  and accepts `canonical_entity_id` to resolve event IDs through identity
  observations and reverse merge lineage. This exposes anonymous history on
  the current canonical profile without rewriting the event row. It bounds
  `occurred_at` with `start_date` / `end_date` (inclusive; a
  date-only bound covers the whole day). `limit` is never a row predicate.
  Non-empty results are cached for up to 5 minutes under the tenant's query
  generation (`CacheKey.analytics_query_generation`), a token folded into every
  cached key. Each newly recorded event (and `record_event`) replaces the
  token after its write commits; the identity worker also retires the token
  after assigning event ownership. The next read misses and sees the event or
  updated identity mapping; old entries age out under their TTL. The replacement is
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
  (`docs/reference/privacy/dsr-erasure-coverage.md`). `DeletionPlan.execute`
  (`shared/privacy/retention.py`) uses it for `HARD_DELETE` and `EDGE_SEVER`
  steps whenever the store adapter provides it, so a plan only deletes its own
  tenant's rows; a plan with no tenant fails those steps instead of deleting
  unscoped. Adapters without it (the externalized Bronze adapter, which is bound
  to one tenant when it is built) keep `delete_by_entity`.

- **Conditional writes (JSONB-mode tables):** `BaseRepository.insert_if_absent`
  creates a tenant-owned row only when the id is free (`ON CONFLICT DO NOTHING`),
  and `replace_if_matches` replaces one only while its stored JSON still
  contains the caller's `expected` subset (for example `{"revision": 3}`), as a
  single `data @> expected` predicate inside the `UPDATE`. Both return `False`
  instead of writing when they lose, so a caller re-reads rather than
  overwriting a concurrent writer. `replace_if_matches` never rewrites the
  stored `created_at`. Explicit-column tables raise `NotImplementedError`.

- **Row ownership on write:** `BaseRepository.insert` and `update` read the
  record's tenant from `tenant_id` or `tenantId` and only replace a row whose
  `COALESCE(tenant_id, '')` column equals it (the predicate is part of the
  `ON CONFLICT ... DO UPDATE` / `UPDATE` statement, and the in-memory store
  applies the same rule). A write that would replace another tenant's row, or
  a row with no tenant when the record names one, changes nothing and raises
  `ConflictError` with the generic `Conflict` text, which neither names the
  owner nor says the id exists elsewhere, so a client-chosen id (such as a
  flows `wallet_id`) belongs to the first tenant that writes it. Repositories whose rows are not tenant-owned
  set `_tenant_guard = False`: `users` (an SSO re-invite moves a user to
  another tenant), `tenants`, `first_admin_bootstrap` and the Dune feed tables.
  Records whose natural id is unique only within a tenant use
  `tenant_record_id(tenant_id, natural_id)` (`{tenant}:{id}`) as the row id:
  `behavior_profiles` and `journey_chains` (`find_for_entity(tenant_id,
  entity_id)`), `profiles` (`IdentityRepository`, keyed by the SDK user id,
  which also stays in `user_id`), `behavioral_signals` written by
  `SignalRepository` (the signal id stays in `signal_id`; `get_signal(tenant_id,
  signal_id)` reads one), `event_envelopes` (the envelope id stays in
  `envelope_id`) and the x402 commerce collections. Migration
  `20261015_tenant_owned_row_keys` runs the idempotent steps in
  `repositories/tenant_row_keys.py`: it backfills empty tenant columns from the
  row JSON, re-keys existing rows of those tables, deletes `behavior_profiles` /
  `journey_chains` rows whose JSON tenant differs from the column (the profile
  workers recompute them), marks seeded Web3 registry rows with no tenant
  as `system`, and marks `chain:`, card catalog and derivatives venue/market
  graph vertices `platform` owned. `make tenant-row-keys` (or `python -m repositories.tenant_row_keys`
  in the API image) runs the same steps again after a rollout. Other rows with
  no tenant are left in place and stay unreadable to tenant-scoped reads.

- **Tenant-owned repositories:** `TenantOwnedRepository` (a `BaseRepository`
  subclass) is for registries whose ids come from the caller, such as the Web3
  and cross-domain registries, and for rows that routes read back by an id the
  caller supplies: expectation and behavioral signals and the RWA asset,
  policy, cashflow, exposure and holder stores. `upsert(record_id, data, tenant_id)` stamps the
  row with the tenant, merges into that tenant's own row (keeping `created_at`),
  and raises `ConflictError` rather than overwrite a row another tenant owns
  or adopt a row that has no tenant.
  Reads only work on a view bound with `for_tenant(tenant_id)`; an unbound
  instance raises. A repository may list `_shared_tenants` (the platform `system`
  tenant for seeded reference data such as chains and protocols), whose rows
  every tenant can read but none can overwrite.

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

The `provider_records` domain has an additional raw-retention boundary:
`RawProviderRecordStore` resolves a current tenant-lake rights decision before
the Bronze insert. An admitted row uses `provenance_status="valid"`,
`license_status="tenant_rights_granted"`, and `terms_status="active_grant"`;
these two status values record Aether's tenant grant decision and do not claim
that the provider's API or payload carries an external license. Missing or
revoked rights prevent the full payload from being written. In staging and
production the current in-memory grant authority also fails closed until a
durable grant store is available.

`BronzeRepository.update()` keeps `provider_records` immutable after insert.
The sole supported update appends nonempty, unique values to
`payload.metadata.confirmed_signal_ids` for commerce confirmation replay
detection. It cannot alter the provider payload, identity, rights evidence, or
provenance/quarantine markers. Other Bronze domains retain their existing
repository update behavior.

`SilverRepository.upsert_record()` includes `tenant_id` in the `record_id` hash (`SHA256(tenant_id:entity_type:entity_id:source)[:24]`) to prevent cross-tenant data collisions. `SilverRepository.check_promotion_eligibility(bronze_record)` enforces the promotion gate: quarantined Bronze records cannot be promoted to Silver (returns `(False, reason)` with the blocking reason).

CSV import commits preserve their Rights Authority lineage separately from the
raw payload. Commit-scoped Bronze rows retain `rights_decision_refs`, and the
`silver_import_facts` projection stores those decision references plus the
actual `bronze_record_id` for each projected fact. The additive
`20261011_import_rights_decision_refs` migration adds the JSONB column to the
Silver import-facts table; legacy non-import Bronze records omit the field.

Source-tag audit and rollback require a non-empty tenant ID and filter records
by both `tenant_id` and `source_tag`. The lake API supplies the authenticated
tenant. Bronze and Silver rollback refuse more than 10,000 matching rows before
deletion instead of silently truncating the selection. Rollback remains a hard
delete; it does not create a durable correction or erasure receipt.

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

## Agent lineage, handoff and fleet tables

- `20261022_agent_spawn_lineage` adds `parent_agent_ref`, `child_agent_ref`,
  `root_agent_ref`, `parent_run_id` and the MCP endpoint / object / trade columns
  the projector already emitted (`server_url`, `server_name`, `object_type`,
  `object_id`, `symbol`, `side`, `quantity`, `total_value`, `external_order_id`,
  `account_kind`) to `silver_agent_execution_facts`. The generic Silver writer
  drops row keys without a column, so those fields were not persisted before.
  Silver stores the event type in `source_event_type`; there is no `event_name`
  column.
- `20261022_journey_handoffs` creates `journey_handoffs` (token hash only,
  tenant/app/journey bound, single-use state), owned by
  `repositories/journey_handoff_repo.py` with DDL parity tested.
- `fleet_hypotheses` is a runtime-created `BaseRepository` table keyed
  `{tenant}:fleet_hyp:{hash}`. Each record carries a `revision`; every write
  after the first is a compare-and-set on it (the first is insert-if-absent), so
  concurrent reviews and rebuilds cannot overwrite one another.

These migrations are authored in the branch; this page does not claim they
have been applied.

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
