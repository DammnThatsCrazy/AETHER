---
title: Rate Limits & Bursts
slug: operations/rate-limits-and-bursts
section: operations
visibility: I
audience: [dev-senior, architect, ops]
status: stable
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Rate Limits & Bursts

Aether enforces three independent layers in the middleware stack
(`middleware/middleware.py`), all tenant-scoped and plan-aware.

## 1. Burst rate limit (RPM)

`shared/rate_limit/limiter.py` — per-tenant requests-per-minute, sliding window
(Redis Lua script in prod, in-memory locally). On exceed → `429` with
`Retry-After` and `X-RateLimit-*` headers.

| Plan | Burst RPM | Monthly quota |
| --- | --- | --- |
| P1 Hobbyist | 100 | 25,000 |
| P2 Professional | 500 | 100,000 |
| P3 Growth Intelligence | 1,200 | 250,000 |
| P4 Protocol Master | 3,000 | 500,000 |

## 2. Monthly quota (meter, never block)

`shared/rate_limit/quota.py` — atomic monthly counter per tenant. Requests are
**always allowed**; usage past the included quota is flagged as overage
(per-service) via `X-Quota-*` headers and metered for billing. Never returns a
hard block.

## 3. Feature gate (plan access)

`shared/rate_limit/feature_gate.py` — per-service access from the
`SERVICE_CATALOG` (`shared/plans/service_catalog.py`). Blocked services return
`403` with the minimum required plan. Public paths (`/v1/health`, `/v1/auth/*`,
webhook endpoints, `/openapi.json`) bypass auth and gating.

## Usage dimensions

Overage and billing are computed per usage dimension — see
[OODA & Outcome Usage Dimensions](OODA-USAGE-DIMENSIONS.md) and
[Outcome Pricing Dimensions](OUTCOME-PRICING-DIMENSIONS.md). Connector and
webhook ingestion paths are metered the same way as SDK ingestion.

See [Pricing Architecture](PRICING-ARCHITECTURE.md).
