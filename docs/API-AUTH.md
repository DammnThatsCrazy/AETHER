---
title: API Authentication
slug: api/api-auth
section: api
visibility: I
audience: [dev-junior, dev-senior]
status: stable
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# API Authentication

Every non-public `/v1` request is authenticated by the middleware and resolved to
a tenant context.

## Credentials

- **API key**: `X-API-Key: <key>` — resolves tenant, plan tier, permissions.
- **JWT**: `Authorization: Bearer <jwt>` — HS256 (or RS256), claims → tenant.
- **Auth0 / OIDC**: frontends obtain a token; the backend validates it.

## Public paths (no auth)

`/v1/health`, `/v1/metrics`, `/docs`, `/openapi.json`, `/v1/auth/*` (register,
login, verify, recovery), `/v1/tenants`, and provider webhook endpoints
(signature-protected).

## Authorization

Tenant context carries role + permissions; routes enforce
`require_permission(...)`. Kyber operator routes use a fail-closed operator gate
(no Aether tenant may access Kyber) — see [Access Control](ACCESS-CONTROL.md).
Cross-tenant access is denied; aggregate Kyber views are tenant-anonymous.

See [API Rate Limits](API-RATE-LIMITS.md) and [API Errors](API-ERRORS.md).
