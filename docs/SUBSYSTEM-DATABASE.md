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
last_synced_commit: 996aad2
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
| `webhooks` | `WebhookRepository` | Notification service |
| `alerts` | `AlertRepository` | Notification service |
| `tenants` | `AdminRepository` | Admin service |
| `users` | `UserRepository` | Auth (email+password signup, OTP, SSO via Auth0) |
| `api_keys` | `APIKeyRepository` | Admin service |
| `provider_usage` | `UsageMeter` | Provider gateway |
| `investigations` | `InvestigationRepository` | Investigation service |
| `governance_decisions` | `GovernanceRepository` | Governance service |
| `event_replay_jobs` | `EventReplayRepository` | Events replay worker |
| `event_envelopes` | `EventEnvelopeRepository` | Events service |

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
