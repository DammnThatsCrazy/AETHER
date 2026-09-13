---
title: API Authentication
slug: api/authentication
section: reference
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: 0.1.0
canonical_owner: platform@aether
estimated_read_minutes: 4
toc_depth: 3
---

# API Authentication

Every non-public `/v1` request is authenticated by the middleware and
resolved to a tenant context before any handler runs. Public paths (health,
metrics, docs, auth, provider webhooks) are the only exceptions.

## Credentials

Aether accepts three credential shapes:

- **API key** — `X-API-Key: <key>` (or `Authorization: Bearer <key>` — both
  headers resolve the same credential path). This is what SDKs, server
  integrations, and scripts use.
- **JWT** — `Authorization: Bearer <jwt>`, HS256 or RS256, for dashboard
  sessions and anything acting on behalf of a logged-in user.
- **Auth0 / OIDC** — the dashboard's own login flow, which exchanges for a
  session JWT; not something you'd use directly from an SDK or server
  integration.

## Key types

An API key is scoped to exactly one tenant and carries a permission set.
Think of keys in three broad tiers, even though the underlying permission
model is more granular than three flat roles:

| Key type | Typical permissions | Use it for |
|---|---|---|
| **Write key** | `write` (ingest) | SDKs and server integrations sending events (`POST /v1/batch`). Cannot read data back. |
| **Read key** | `read`, `analytics` | Querying profiles, journeys, campaigns, and reporting. Cannot ingest. |
| **Admin key** | `admin`, plus everything above | Managing other keys, webhooks, tenant settings, and billing. |

Permissions are additive and can be narrower than these three buckets — for
example `commerce:read`, `agent:manage`, `x402:write`, `approvals:write`,
and `entitlements:read` gate specific subsystems independently of the
coarse read/write/admin split. A key only carries the scopes it was minted
with; requesting an action outside its scope returns `403`.

Mint keys from **Settings → API Keys** or the activation flow
(`/activation`) when connecting your first source. A newly minted key's raw
value is shown exactly once — store it in a secret manager, not in source
control.

## Token refresh

JWTs used for dashboard sessions are short-lived and refreshed
transparently by the frontend session layer; API keys don't expire on a
schedule — they remain valid until explicitly revoked. Revoke a
compromised key immediately from **Settings → API Keys**; revocation takes
effect at the auth cache layer within seconds, not on the next deploy.

## Rate limits

Rate limits are enforced per tenant, per plan. See
[Ingestion](ingestion.md#rate-limits) for the specific headers and 429
behavior on the batch endpoint.

## Next steps

- [Ingestion API](ingestion.md) — the endpoint write keys are minted for.
- [Tenants](../concepts/tenants.md) — how tenant scoping and plans relate to
  key permissions.
