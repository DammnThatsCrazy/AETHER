---
title: Kyber Economic Observability
slug: concepts/kyber-economic-observability
section: kyber
visibility: I
audience: [dev-senior, ops]
status: stable
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/economic/routes.py
  - packages/shared/economic-metrics.ts
related:
  - concepts/economic-value-framing
  - concepts/unified-economic-graph
last_synced_commit: af65923
---

# Aether — Kyber Economic Observability

## Overview

The Kyber operator console surfaces economic observability for platform operators. This gives operators visibility into tenant economic health, data quality, attribution confidence, and system integrity.

## Operator Dashboard Sections

### Economic Flow
- Tenant-level Total Value Observed
- Web2 / Web3 / Agentic / Campaign domain split
- Trend over time windows (24h, 7d, 30d, 90d)

### Data Quality Warnings
- **Mixed Currency** — Aggregations spanning multiple native currencies
- **Stale Prices** — Token prices older than threshold (default: 1 hour)
- **Missing Prices** — Positions without USD conversion
- **Partial Source Coverage** — Not all data connectors active

### Attribution Confidence
- Campaign attribution model in use (first_touch, last_touch, linear, etc.)
- Average attribution confidence score
- Low-confidence attributions flagged for review
- Cross-domain attribution (campaign → Web3 activity)

### Protocol TVL Tracking
- Per-protocol TVL snapshots
- TVL by chain, token, contract
- Derivative / bridge double-counting risk flags

### x402 Settlement Health
- Settlement success rate
- Settlement failure rate
- Average settlement latency
- Abandoned settlements with reasons

### Agent Spend Monitoring
- Agent budget utilization
- Spend anomalies (sudden spikes, budget exhaustion)
- Per-agent ROI / ROAS
- Service dependency concentration

### Tenant Isolation Audit
- Cross-tenant query verification
- Tenant-scoped metric validation
- Isolation breach detection (should always be zero)

## API Endpoints

```
GET /v1/economic/overview                    → Tenant economic overview
GET /v1/economic/warnings                    → Tenant-wide warnings
GET /v1/profile/{id}/economic                → Entity economic breakdown
GET /v1/profile/{id}/economic/web2           → Web2 GMV / revenue / payment volume
GET /v1/profile/{id}/economic/web3           → Web3 TVL / protocol exposure
GET /v1/profile/{id}/economic/agentic        → Agentic/x402 spend, service calls, settlement success rate
GET /v1/profile/{id}/economic/campaigns      → Campaign-attributed value
GET /v1/profile/{id}/economic/warnings       → Entity-level data-quality warnings
```

The `/economic/agentic` breakdown is composed live from payment intents and
settlement events (`AgentProfile360EconomicComposer`); it returns an empty
envelope rather than failing when composition errors occur.

## Implementation

- Backend: `Backend Architecture/aether-backend/services/economic/routes.py`
- Shared types: `packages/shared/economic-metrics.ts`
- Profile360 integration: `packages/shared/profile360-contract.ts`

## Surface Visibility

- `kyber_internal` surface: Full unredacted economic data with warnings and provenance
- `end_user` surface: Tenant-scoped economic data with visibility controls
