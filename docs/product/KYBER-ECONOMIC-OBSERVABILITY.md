---
title: Kyber Economic Observability
slug: concepts/kyber-economic-observability
section: operations
visibility: I
audience: [dev-senior, ops]
status: stable
since_version: 0.1.0
source_files: [services/api/value/economic/routes.py, services/api/identity/profile/routes.py, packages/shared/economic-metrics.ts]
related: [concepts/economic-value-framing, concepts/unified-economic-graph]
source_hashes:
  "packages/shared/economic-metrics.ts": "sha256:035a58e18a5543feee432a5dec5efa8a4ec61be3a8dee6b9b2385f8dafedb7df"
  "services/api/identity/profile/routes.py": "sha256:db152bc22effffbb626e2de110e7b369c05be76efd543316045fabd54066b70a"
  "services/api/value/economic/routes.py": "sha256:b606e1038bf147686e2dc1a30575fb94132be5488ed146d4981a5f8030dc9897"
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
GET /v1/profile/{id}/economic                → Economic profile: financials and on-chain asset composition (profile service)
GET /v1/profile/{id}/economic/web2           → TradFi signals; requires `credit` consent, 403 without it (profile service)
GET /v1/profile/{id}/economic/web3           → Asset composition, PNL and trading profile (profile service)
GET /v1/profile/{id}/economic/agentic        → Agentic/x402 spend, service calls, settlement success rate
GET /v1/profile/{id}/economic/campaigns      → Campaign-attributed value
GET /v1/profile/{id}/economic/warnings       → Missing, stale and contradicting dimensions (profile service)
```

Every route requires the `read` permission. `/economic/agentic`, `/economic/campaigns`
and the two `/v1/economic` routes are served by `services/api/value/economic/routes.py`; the
other four profile routes are served by `services/api/identity/profile/routes.py`. Each URL has
exactly one handler (`tests/unit/test_route_conflicts.py`).

The `/economic/agentic` breakdown is composed live from payment intents and
settlement events (`AgentProfile360EconomicComposer`); it returns an empty
envelope rather than failing when composition errors occur.

## Implementation

- Backend: `services/api/value/economic/routes.py` and `services/api/identity/profile/routes.py`
- Shared types: `packages/shared/economic-metrics.ts`
- Profile360 integration: `packages/shared/profile360-contract.ts`

## Surface Visibility

- `kyber_internal` surface: Full unredacted economic data with warnings and provenance
- `end_user` surface: Tenant-scoped economic data with visibility controls
