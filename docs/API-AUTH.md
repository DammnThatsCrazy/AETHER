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

## Destructive cleanup and rehearsal credentials

Administrative tenant cleanup is fail-closed. Durable API keys are revoked
before their rows are removed, then every corresponding Redis auth-cache entry
is evicted and read back to verify that a stale cache hit cannot authenticate.
Contained public-ingest identifiers are revoked before the tenant is deleted;
any repository or per-identifier failure aborts cleanup so an orphaned ingest
credential is never reported as removed. The deactivation fallback applies the
same credential invalidation contract but deliberately retains tenant data for
recovery.

The staging smoke harness uses two credentials with different boundaries. The
run-scoped tenant key is limited to data-plane checks. The encrypted
`STAGING_ADMIN_API_KEY` is supplied only to the diagnostics probes and the
run-scoped bootstrap/cleanup calls; it is never written to an artifact or used
as the tenant's application credential. A successful destructive cleanup must
return its complete erasure receipt, including consent/DSR, ingestion and
analytics records, profiles, and graph projection data. Billing and immutable
security-audit evidence remain retained under policy.

See [API Rate Limits](API-RATE-LIMITS.md) and [API Errors](API-ERRORS.md).
