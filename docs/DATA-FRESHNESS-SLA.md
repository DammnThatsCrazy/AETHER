---
title: Data Freshness SLA
slug: operations/data-freshness-sla
section: operations
visibility: P
audience: [exec, architect, ops, buyer]
status: stable
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
toc_depth: 2
---

# Data Freshness SLA

This document defines freshness guarantees for all data surfaced in Profile360,
the Aether intelligence graph, and provider-enriched fields.

---

## Freshness Labels

Every aggregated output in Aether carries a `computed_at` timestamp and a
machine-readable freshness label:

| Label | Threshold | Meaning |
|---|---|---|
| `live` | < 5 minutes old | Real-time data; safe to act on immediately |
| `recent` | 5–30 minutes old | Normal operating range; suitable for all decisions |
| `stale` | > 30 minutes old | Compute job lagging; alerting triggered |

These labels appear in Profile360 sub-resource envelopes as `freshness` fields,
and are queryable via `GET /v1/data-quality/freshness`.

---

## Gold Table Refresh Schedule

Gold tables are the aggregated ClickHouse materialized views that power Profile360.

| Layer | Refresh Cadence | SLA Target |
|---|---|---|
| Event ingestion (raw → bronze) | Near-real-time (streaming) | < 60 seconds from event receipt |
| Bronze → Silver enrichment | Continuous batch | < 5 minutes from bronze ingestion |
| Silver → Gold materialization | Every 15 minutes | ≤ 15 minutes end-to-end (receipt → Profile360 visible) |
| S3 Iceberg lifetime rollups | Nightly (00:00–02:00 UTC) | Available by 06:00 UTC |

**The 15-minute gold refresh is the primary freshness SLA** for all Profile360
queries. Operators and tenants can rely on data being at most 15 minutes old
during normal operations.

---

## Provider Adapter Sync Schedule

Provider adapters (BYOK integrations) pull external signals on a scheduled basis:

| Provider Category | Sync Frequency | On-Demand Trigger |
|---|---|---|
| Ad platforms (Meta, Google, LinkedIn, TikTok) | Nightly | `POST /v1/providers/sync` |
| Open banking (Plaid) | Nightly | `POST /v1/providers/sync` |
| Credit bureaus (Experian, Equifax, TransUnion) | Weekly | Not available (bureau rate limit) |
| Social platforms (Twitter, Instagram, YouTube, etc.) | Nightly | `POST /v1/providers/sync` |
| Brokerage accounts | Nightly | `POST /v1/providers/sync` |
| Market data | Real-time (streaming) | — |

> **Note:** Credit bureau sync is weekly due to bureau-imposed rate limits.
> Profile360 credit fields will show `computed_at` from the last successful pull.

---

## On-Demand Sync

Any provider that supports on-demand sync can be triggered via:

```bash
POST /v1/providers/sync
Authorization: Bearer <tenant_api_key>

{
  "provider_name": "meta_ads"    # omit to sync all configured providers
}
```

Response includes job ID; poll `GET /v1/providers/health` for completion status.

---

## Provider Health Visibility

Current health and last-sync status for all configured providers is available at:

```bash
GET /v1/providers/health
Authorization: Bearer <tenant_api_key>
```

Response fields per provider:

| Field | Description |
|---|---|
| `status` | `healthy` \| `degraded` \| `failed` \| `unconfigured` |
| `last_successful_sync` | ISO-8601 timestamp of last successful data pull |
| `error_count` | Number of consecutive sync failures |
| `staleness_label` | `live` \| `recent` \| `stale` based on `last_successful_sync` |
| `circuit_breaker` | `closed` (normal) \| `open` (paused after failures) \| `half_open` (recovering) |

Providers with `circuit_breaker: open` have been paused after repeated failures.
The Kyber operator console surfaces these in **Connectors → Health**.

---

## Alerting

Aether emits internal alerts when the following thresholds are breached:

| Condition | Alert Level | Notification |
|---|---|---|
| Gold table compute lags > 30 minutes | **Warning** | Ops Slack `#aether-alerts` |
| Gold table compute lags > 60 minutes | **Critical** | PagerDuty on-call |
| Any provider in `failed` state for > 2 hours | **Warning** | Ops Slack `#aether-alerts` |
| Bronze → Silver enrichment stops processing | **Critical** | PagerDuty on-call |

Tenants and customers can subscribe to data quality events via:
```
GET /v1/data-quality/freshness    # Current freshness scores per sub-resource
GET /v1/providers/health          # Provider-level health and last-sync
```

---

## What customers see on Day 1

| Action | Time to visible |
|---|---|
| First SDK event received | < 60 seconds in event lake |
| First entity appears in Profile360 | ≤ 15 minutes |
| Ad platform attribution appears (after BYOK key added) | ≤ 24 hours (next nightly sync) |
| Social signals appear (after BYOK key added) | ≤ 24 hours (next nightly sync) |
| Churn risk and LTV predictions update | On gold table refresh (≤ 15 min) |

---

## Exclusions and Caveats

- Freshness SLAs apply under normal load. During platform incidents, the
  [System Status page](https://app.aether.io/system-status) reflects current state.
- Credit bureau data is explicitly excluded from the 15-minute SLA (weekly cadence).
- On-demand sync is best-effort; it does not guarantee a specific completion time.
- S3 Iceberg lifetime rollups are advisory (trend analysis); they do not affect
  real-time Profile360 data.
