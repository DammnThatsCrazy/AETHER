---
title: Dune Access Modes
slug: architecture/dune-access-modes
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: draft
canonical_owner: data@aether
source_files:
  - Backend Architecture/aether-backend/services/provider_catalog/models.py
last_synced_commit: "pending"
estimated_read_minutes: 6
---

# Dune Access Modes

> Dune exposes three distinct access surfaces. Using the wrong mode for a given
> workload wastes credits, increases latency, or produces stale data. This doc
> specifies when each mode is appropriate, how it is configured, and what its
> operational limits are.

---

## Mode 1: dune_api

**Slug:** `dune_api`
**Best for:** Parameterized SQL queries, prototyping new extractions, per-wallet
on-demand enrichment at low to moderate volume.

### How it works

The Dune API accepts a query ID and a set of parameters. Aether submits a query
execution request, polls for completion, and retrieves results as JSON. Queries
are authored once in the Dune UI and referenced by ID in the catalog config.

### Appropriate workloads

- Analyst-authored research queries with parameters (`wallet_address`, `chain`,
  `start_date`) that vary per request.
- One-off extractions during feature development or data exploration.
- Enrichment for low-volume API paths where a few hundred wallet lookups per day
  are acceptable.

### Limits and constraints

- **Latency:** Query execution typically takes 3–60 seconds. Not suitable for
  synchronous API responses.
- **Cost:** Charged per credit consumed; heavy queries on large tables burn
  credits quickly. Monthly credit budgets must be tracked.
- **Concurrency:** The API enforces execution limits; parallel requests compete
  for slots. Bursting beyond ~10 concurrent executions risks throttling.
- **Result size:** Large result sets require pagination; the API returns a
  cursor for subsequent pages.

### Operational config

```yaml
mode: dune_api
query_id: "<integer>"
parameters:
  wallet_address: "{{wallet}}"
  chain: "ethereum"
poll_interval_ms: 2000
max_poll_attempts: 60
```

---

## Mode 2: dune_datashare

**Slug:** `dune_datashare`
**Best for:** Warehouse bootstrap, bulk historical extraction, T+1 analytics
workloads that tolerate data being one day old.

### How it works

Dune maintains a continuously refreshed dataset in Snowflake. Aether accesses
this via a Datashare arrangement: no data is moved at query time; the warehouse
layer can query Dune's tables directly using Snowflake SQL. For BigQuery and
Databricks environments, Dune periodically exports parquet files to shared
storage.

The Datashare path is a fixed subscription cost independent of query volume.
This makes it the economically preferred path for any extraction that can
tolerate next-day freshness.

### Appropriate workloads

- Initial lake bootstrap: populating historical transaction tables for a new
  chain or protocol.
- Batch feature pipelines that run nightly (wallet behavior profiles, protocol
  TVL snapshots, cross-chain bridge activity).
- Retroactive enrichment when a new model or feature requires historical signals
  that were not previously extracted.

### Limits and constraints

- **Freshness:** Data is typically T+1 (one full day behind real-time). Some
  spellbook tables update more frequently, but Aether should assume T+1.
- **Schema stability:** Dune may rename or restructure spellbook tables. Schema
  contracts must be pinned and monitored for breaking changes.
- **Coverage:** Not all raw tables are available via Datashare. Check coverage
  before relying on a specific table in a pipeline.

### Operational config

```yaml
mode: dune_datashare
warehouse: snowflake
database: DUNE_DATASHARE
schema: ethereum
table: transactions
freshness_sla_hours: 26
```

---

## Mode 3: dune_sim

**Slug:** `dune_sim`
**Best for:** Realtime wallet simulation, pending transaction enrichment, gas
estimation, and state-at-block queries.

### How it works

Dune Sim provides a simulation API that can evaluate the outcome of a transaction
or query wallet state without submitting to the chain. Aether uses this for
realtime wallet enrichment paths where the intelligence layer needs current token
balances, recent activity, or pending transaction context faster than finalized
block data allows.

### Appropriate workloads

- Enriching a wallet's current token balance at request time for intent scoring.
- Simulating a pending transaction to assess risk before it is mined.
- Hydrating the Profile 360 with a wallet's current DeFi positions in sub-second
  latency contexts.

### Limits and constraints

- **Cost:** Per-simulation credit consumption. Reserve for synchronous paths
  where freshness justifies the cost premium over `dune_api`.
- **Chain support:** Not all chains support simulation. Verify chain compatibility
  before routing production traffic.
- **State freshness:** Sim reflects the latest indexed block, which may still be
  seconds to a few blocks behind the true chain tip.

### Operational config

```yaml
mode: dune_sim
chain: ethereum
sim_type: wallet_state
target_block: latest
timeout_ms: 800
```

---

## Mode selection decision tree

```
Need data right now (< 1s)?
  YES -> dune_sim (if chain supported) or alchemy/moralis
  NO  ->
    High volume (> 10k wallets/day)?
      YES -> dune_datashare (if T+1 ok) or dune_api with credit budget
      NO  -> dune_api (parameterized query)
```

---

## Shared constraints across all modes

- Credentials are stored in the platform key vault, never in source code.
- All three modes emit `enrichment_lineage` records so data provenance can be
  traced and revoked.
- Rate-limit errors from any Dune mode are retried with exponential backoff
  capped at 3 attempts; after that, the enrichment step is skipped and flagged
  as unavailable in the output record.

---

## Related docs

- `DUNE_DATA_LAKE_STRATEGY.md` — Strategic rationale for Dune's role.
- `DUNE_CHAIN_EXTRACTION_PLAN.md` — Chain coverage priorities.
- `ENRICHMENT_LINEAGE.md` — Lineage model attached to all Dune outputs.
