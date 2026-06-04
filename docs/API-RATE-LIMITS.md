---
title: API Rate Limits
slug: api/api-rate-limits
section: api
visibility: I
audience: [dev-junior, dev-senior, ops]
status: stable
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 2
---

# API Rate Limits

Per-tenant, per-plan limits enforced in the middleware. Full detail in
[Rate Limits & Bursts](RATE-LIMITS-AND-BURSTS.md).

## Headers

On success: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`,
and quota headers `X-Quota-Limit`, `X-Quota-Used`, `X-Quota-Remaining`,
`X-Quota-Reset` (+ `X-Quota-Overage: true` past the monthly quota).

## 429

Burst exceed → `429` with `Retry-After` and an upgrade hint. Monthly quota is
**metered, never blocked** (overage flagged for billing). Feature-gated services
return `403` with the minimum required plan.

See [API Reference](API-REFERENCE.md) and [OODA & Outcome Usage Dimensions](OODA-USAGE-DIMENSIONS.md).
