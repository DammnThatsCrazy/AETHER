---
title: Campaign Registry Architecture
slug: campaign/campaign-registry-architecture
section: architecture
visibility: I
audience: [dev-senior, architect]
source_files:
  - Backend Architecture/aether-backend/services/campaign/registry.py
  - Backend Architecture/aether-backend/services/campaign/repository.py
  - Backend Architecture/aether-backend/alembic/versions/20260627_campaign_registry.py
last_synced_commit: "4e6fdad"
---

# Campaign Registry Architecture

## Database schema

### `campaigns`

Primary registry of all known campaigns. One row per canonical campaign regardless of how many external platforms reference it.

| Column | Type | Notes |
|---|---|---|
| `campaign_id` | UUID PK | Canonical Aether identifier — never a provider ID |
| `tenant_id` | TEXT | Tenant owner |
| `name` | TEXT | Display name (may change; UUID is stable) |
| `status` | TEXT | active / paused / archived |
| `channel` | TEXT | email / paid_search / paid_social / etc. |
| `origin` | TEXT | external / custom / discovered |
| `primary_platform` | TEXT | Canonical platform name |
| `source_connector_id` | TEXT | Originating connector |
| `sync_status` | TEXT | not_synced / synced / stale |
| `properties` | JSONB | Provider-specific metadata |

### `campaign_external_refs`

One row per (tenant, platform, account, external_campaign_id) tuple. The `UNIQUE` constraint guarantees idempotent upserts.

| Column | Type | Notes |
|---|---|---|
| `external_ref_id` | UUID PK | |
| `campaign_id` | UUID FK → campaigns | Canonical UUID |
| `platform` | TEXT | Normalized platform name |
| `external_account_id` | TEXT | Provider account/customer ID |
| `external_campaign_id` | TEXT | Provider campaign ID (never used as campaign_id) |
| `external_campaign_name` | TEXT | Name from provider API |
| `raw_metadata` | JSONB | Full provider campaign object snapshot |

### `campaign_aliases`

Maps lookup keys to canonical campaign UUIDs. Powers resolver priority steps 3–5.

| Column | Type | Notes |
|---|---|---|
| `alias_id` | UUID PK | |
| `campaign_id` | UUID FK → campaigns | |
| `alias_type` | TEXT | utm_id / utm_campaign / composite |
| `alias_value_normalized` | TEXT | Lowercased, URL-decoded |
| `valid_until` | TIMESTAMPTZ | NULL = active |

Unique constraint: `(tenant_id, alias_type, alias_value_normalized)` WHERE `valid_until IS NULL`. Ensures one active alias per value per type per tenant.

### `campaign_resolution_reviews`

Queue of unresolved/ambiguous evidence awaiting human mapping.

| Column | Type | Notes |
|---|---|---|
| `review_id` | UUID PK | |
| `status` | TEXT | open / resolved / ignored |
| `evidence` | JSONB | Raw resolution input |
| `evidence_hash` | TEXT | SHA-256 for deduplication |
| `observed_count` | INTEGER | Incremented on each recurrence |
| `resolved_campaign_id` | UUID FK → campaigns | Set when resolved |
| `resolved_by` | TEXT | Operator identity |

Unique constraint: `(tenant_id, evidence_hash, status='open')` prevents duplicate open reviews.

### Fact table additions

| Table | New columns |
|---|---|
| `spend_records` | `external_campaign_id`, `external_account_id`, `campaign_resolution_status`, `campaign_resolution_method`, `campaign_resolution_version` |
| `silver_campaign_touchpoint_facts` | Same + `campaign_resolution_confidence` (NUMERIC 5,4) |
| `attribution_credits` | `external_campaign_id`, `campaign_resolution_method` |

## Invariants

1. `campaign_id` in any resolved measurement fact is always a valid Aether UUID owned by the authenticated tenant.
2. `external_campaign_id` always stores the provider's text identifier separately.
3. The resolver never fuzzy-matches campaign names.
4. The resolver never resolves across tenants.
5. A canonical UUID from an external source is always validated against tenant ownership before use.
6. Production never uses in-memory fallback stores for registry or resolver. This is enforced in code, not convention: `_require_pool` in `services/campaign/repository.py` raises when no pool is available outside the pool-optional environments (`local`/`dev`/`test`), so a misconfigured production process fails at the read/write rather than silently minting transient campaign identity in memory. The check lives in the shared `_acquire_pool` path, so no repository method can reach a local store without passing it.
7. Raw evidence is never discarded after resolution failure.
8. Every manual mapping mutation is permission-gated and audited.
9. External campaign rename retains the Aether UUID.
10. External archive retains all historical measurement data.
