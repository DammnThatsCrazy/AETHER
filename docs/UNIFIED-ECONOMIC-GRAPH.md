---
title: Unified Economic Graph
slug: concepts/unified-economic-graph
section: concepts
visibility: P
audience: [dev-senior, architect]
status: stable
since_version: "8.9.0"
source_files:
  - packages/shared/economic-metrics.ts
  - packages/shared/graph-relationships.ts
related:
  - concepts/economic-value-framing
  - concepts/tvl-gmv-revenue-metrics
last_synced_commit: 236aa4e
---

# Aether — Unified Economic Graph

## Overview

Aether's economic intelligence layer connects economic activity across domains through a unified entity graph. Every metric — Web2 revenue, Web3 TVL, campaign spend, agent spend, x402 settlements — is attached to entities and connected through typed relationships.

## Entity-Economic Connections

```
human  → wallet       → protocol    → TVL
human  → agent        → x402        → settlement
human  → org          → revenue     → Web2 metrics
human  → campaign     → conversion  → attributed revenue
wallet → protocol     → positions   → protocol exposure
agent  → service      → spend       → agentic metrics
campaign → session    → conversion  → ROAS/CAC
campaign → wallet     → deposit     → influenced protocol activity
org    → customer     → payment     → GMV/TPV/revenue
tenant → all entities → all metrics → Total Value Observed
```

## Graph Edges

Economic edges preserve:
- **relationship_type** — e.g. PAYS_FOR, PURCHASES_EXECUTION_FROM, SETTLED_VIA
- **flow_ref** — Sequencing reference for multi-step economic flows
- **interaction_mode** — H2H, H2A, A2A, A2H
- **economic_involved** — Whether the edge carries monetary value
- **outcome** — Revenue, conversion, or latency metric
- **confidence** — Attribution confidence (0–1)
- **tenant_id** — Always scoped for tenant isolation

## Total Value Observed

The unified metric is always decomposable:

```
Total Value Observed
├── web2_revenue
├── web2_gmv
├── web2_tpv
├── web3_tvl (protocol-level only)
├── web3_protocol_exposure (entity-level)
├── web3_transaction_volume
├── agent_spend
├── x402_settlement_value
├── campaign_spend
└── attributed_revenue
```

## Implementation

- **Shared types**: `packages/shared/economic-metrics.ts`
- **Base economic layer**: `packages/shared/economic.ts`
- **Graph relationships**: `packages/shared/graph-relationships.ts`
- **Profile360 integration**: `packages/shared/profile360-contract.ts` (economic sub-resource)
- **Backend routes**: `Backend Architecture/aether-backend/services/economic/routes.py`
- **Aggregation**: Derived read state, never persisted as canonical write state

## Provenance

Every economic metric carries provenance:
- `source` — Which system produced the data
- `source_event_ids` — Original events
- `chain_id`, `block_number`, `transaction_hash` — On-chain provenance
- `pricing_source`, `price_timestamp` — Price data origin
- `attribution_model`, `confidence` — Attribution provenance
- `computed_at` — When the metric was derived

## Warnings

The system emits structured warnings:
- `MIXED_CURRENCY` — Multiple native currencies in a single aggregation
- `MISSING_PRICE` — No USD conversion available
- `STALE_PRICE` — Price data older than threshold
- `POSSIBLE_DOUBLE_COUNT` — Derivative and underlying both present
- `LOW_CONFIDENCE_ATTRIBUTION` — Attribution confidence below threshold
- `PARTIAL_SOURCE_COVERAGE` — Not all data sources connected
- `TENANT_SCOPE_FILTERED` — Data filtered by tenant isolation
