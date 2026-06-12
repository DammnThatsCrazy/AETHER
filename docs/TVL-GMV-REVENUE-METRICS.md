---
title: TVL vs GMV vs Revenue Metrics
slug: concepts/tvl-gmv-revenue-metrics
section: concepts
visibility: P
audience: [dev-senior, architect]
status: stable
since_version: "8.9.0"
source_files:
  - packages/shared/economic-metrics.ts
related:
  - concepts/economic-value-framing
  - concepts/unified-economic-graph
last_synced_commit: d39a526
---

# Aether — TVL vs. GMV vs. Revenue Metric Guide

## Definitions

### TVL (Total Value Locked)
- **Domain**: Web3 only
- **Meaning**: Capital locked, supplied, staked, pooled, escrowed, deposited, or otherwise committed inside a Web3 protocol
- **Formula**: `Σ(current_token_balance_locked_by_protocol × token_price_usd)`
- **Applies to**: Protocols (DeFi, staking, lending, bridges, vaults)
- **Does NOT apply to**: Individual wallets, humans, organizations, campaigns, agents
- **Entity-level equivalent**: "Protocol Exposure" (never "TVL" for non-protocol entities)

### GMV (Gross Merchandise Value)
- **Domain**: Web2
- **Meaning**: Total value of goods/services sold through a platform
- **Applies to**: Marketplaces, e-commerce platforms
- **Note**: Includes seller proceeds — not the same as platform revenue

### TPV (Total Payment Volume)
- **Domain**: Web2
- **Meaning**: Total value processed through payment rails
- **Applies to**: Payment processors, fintech platforms
- **Note**: Includes pass-through value — not the same as revenue

### Revenue
- **Domain**: Web2
- **Meaning**: Money actually earned by the business
- **Derived metrics**: Net Revenue (after refunds/chargebacks), ARR, MRR, NRR

### Campaign Spend / Attributed Revenue
- **Domain**: Cross-domain (campaign)
- **Meaning**: Marketing spend and the revenue causally linked to it
- **Key metrics**: ROAS, CAC, LTV, attribution confidence
- **Note**: Campaign-influenced Web3 activity (wallet connects, protocol deposits) is tracked separately from attributed revenue

### Agent Spend / x402 Settlement
- **Domain**: Agentic
- **Meaning**: Economic value spent by autonomous agents or settled through x402
- **Key metrics**: Authorized budget, remaining budget, ROI, settlement success rate

## Why These Are Never Interchangeable

| Scenario | Wrong | Right |
|----------|-------|-------|
| E-commerce platform processes $1M in payments | "Platform TVL: $1M" | "TPV: $1M" |
| User has $12k in Aave | "User TVL: $12k" | "Protocol Exposure: $12k" |
| Campaign drives 150 wallet connections | "Campaign TVL" | "Influenced Wallet Connects: 150" |
| Agent spends $38 on API calls | "Agent TVL: $38" | "Agent Spend: $38" |
| Protocol holds $5M in smart contracts | — | "TVL: $5M" ✅ |

## Aether's Approach

Aether keeps metrics separate at the metric layer and unified at the entity graph layer. The "Total Value Observed" metric is always decomposable and never displayed without its breakdown.

See `packages/shared/economic-metrics.ts` for the canonical type definitions.
