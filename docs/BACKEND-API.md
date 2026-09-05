---
title: Aether Backend API — Endpoint Specification
slug: api/backend-reference
section: api
visibility: P
audience: [dev-junior, dev-senior, architect]
status: stable
since_version: "8.8.0"
source_files:
  - Backend Architecture/aether-backend/services/
canonical_owner: backend@aether
estimated_read_minutes: 60
toc_depth: 3
last_synced_commit: "f3f42b38"

---
# Aether Backend API v8.12.0 — Endpoint Specification

## Overview

The thin-client architecture requires the backend to handle all processing that was previously done client-side. This document specifies all backend endpoints.

## Authentication

All endpoints require an API key passed as:
- Header: `Authorization: Bearer <api-key>`
- Or query parameter: `?apiKey=<api-key>`

Public paths (`/`, `/health`, `/v1/health`, `/v1/metrics`, `/docs`,
`/openapi.json`, `/redoc`) bypass authentication and rate limiting.

## Plans, Rate Limits & Quotas

Aether uses four self-serve plans (P1–P4). The legacy
`FREE`/`PRO`/`ENTERPRISE` tiers are retained only for backward-compatible
key validation and are mapped to plans automatically (FREE→P1, PRO→P2,
ENTERPRISE→P4).

| Plan | Display Name        | Burst RPM | Monthly Quota | Member Cap | Services |
|------|---------------------|-----------|---------------|------------|----------|
| P1   | Hobbyist            | 100       | 25,000        | 1          | 10       |
| P2   | Professional        | 500       | 100,000       | 3          | 19       |
| P3   | Growth Intelligence | 1,200     | 250,000       | 5          | 29       |
| P4   | Protocol Master     | 3,000     | 500,000       | 10         | 34       |

**Burst RPM** is enforced per-tenant on a sliding minute window. All API
keys belonging to one tenant share a single RPM pool.

**Monthly quota** is a single pooled counter across all services. It
never blocks: requests beyond the quota are flagged as overage and
metered per-service for billing (see `OverageCalculator`).

**Feature gating** rejects requests for services outside the tenant's
plan with HTTP 403 and a structured `required_plan` upgrade message.

### Administrative tenant cleanup

`DELETE /v1/admin/tenants/{tenant_id}` is a fail-closed destructive operation.
It revokes durable API keys before deleting rows, verifies auth-cache eviction,
revokes contained public-ingest identifiers, and removes tenant-scoped
rehearsal data from consent/DSR, ingestion, analytics, profile, and graph
projection stores before removing the tenant row. A successful response
includes a `cleanup_complete` receipt; a partial cleanup raises an error so the
caller can retry without mistaking an orphaned credential or projection for a
completed deletion. Billing and immutable security-audit evidence are retained
under policy. The deactivation endpoint uses the same credential invalidation
order but retains data for recovery.

### Response Headers

Every successful response carries:

| Header                | Description                                      |
|-----------------------|--------------------------------------------------|
| `X-RateLimit-Limit`   | Burst RPM limit for the tenant's plan            |
| `X-RateLimit-Remaining` | RPM tokens remaining in the current minute     |
| `X-RateLimit-Reset`   | Unix timestamp when the burst window resets      |
| `X-Quota-Limit`       | Plan's monthly request quota                     |
| `X-Quota-Used`        | Requests consumed in the current billing period  |
| `X-Quota-Remaining`   | Requests remaining before overage starts         |
| `X-Quota-Reset`       | ISO 8601 timestamp of next billing period start  |
| `X-Quota-Overage`     | Present (`true`) only when the tenant is in overage |
| `X-Access-Tier`       | Plan-specific access tier label for the matched service |

### Error Envelopes

| Status | `error` Code               | Source layer        |
|--------|----------------------------|---------------------|
| 401    | `unauthorized`             | Auth                |
| 403    | `service_not_available`    | Feature gate        |
| 429    | `rate_limit_exceeded`      | Burst RPM           |

Example 429:
```json
{
  "error": "rate_limit_exceeded",
  "message": "Burst rate limit exceeded. Limit: 500 RPM.",
  "retry_after_seconds": 12,
  "plan_tier": "P2",
  "upgrade_url": "/v1/admin/billing/upgrade"
}
```

Example 403:
```json
{
  "error": "service_not_available",
  "message": "The Autonomy service requires Growth Intelligence (P3) or higher.",
  "current_plan": "P1: Hobbyist",
  "required_plan": "P3: Growth Intelligence",
  "upgrade_url": "/v1/admin/billing/upgrade",
  "service": "Autonomy",
  "endpoint": "/v1/agent/tasks"
}
```

## Customer-Facing Sign-Up, Auth, and Self-Service

This section separates unauthenticated signup/auth flows from tenant-scoped
self-service APIs. The public endpoints below intentionally bypass API-key auth
so prospective customers can register without one. The Stripe webhook is also
HTTP-unauthenticated but verifies a Stripe-signed payload. Operators should
ensure IP-rate-limiting is active on these paths and alert on
signature-verification failures.

### Public signup/auth/webhook endpoints (no API key required)

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/tenants` | POST | Public tenant sign-up (programmatic / legacy path) |
| `/v1/auth/register` | POST | Email sign-up step 1 — send OTP to the supplied email |
| `/v1/auth/verify-email` | POST | Email sign-up step 2 — verify OTP, create tenant + first API key |
| `/v1/auth/resend-verification` | POST | Resend the OTP if the first email was lost |
| `/v1/auth/login` | POST | Email + password → API key (creates a new key per login) |
| `/v1/auth/sso/callback` | POST | Auth0 JWT → API key (SSO finish) |
| `/v1/auth/sso/providers` | GET | List configured SSO providers (no auth) |
| `/v1/auth/recover` | POST | Recover lost API key via signed email |
| `/v1/billing/plans` | GET | Public plan catalog for signup and upgrade discovery |
| `/v1/admin/billing/stripe/webhook` | POST | Stripe-signed webhook (subscription + invoice events) |

### Self-service caller endpoints (`/v1/me/*`, API key required)

The "me" surface lets a customer manage their own API keys without admin
intervention. Every endpoint scopes to the caller's API key tenant; no
permission gate beyond authentication.

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/me` | GET | Caller profile + plan summary |
| `/v1/me/api-keys` | GET | List caller's API keys (paginated; honours `limit` + `cursor`) |
| `/v1/me/api-keys` | POST | Create a new API key (self-service) |
| `/v1/me/api-keys/{key_id}` | PATCH | Rename an existing API key |
| `/v1/me/api-keys/{key_id}` | DELETE | Revoke an API key |
| `/v1/me/account` | DELETE | Self-service account deletion (GDPR Article 17) |

### Contact & enterprise inquiries (`/v1/contact/*`, API key required)

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/contact/enterprise` | POST | Submit an enterprise inquiry. Persists the inquiry as the durable record (source of truth), then best-effort emails `ENTERPRISE_INQUIRY_EMAIL`. A persistence failure fails the request (never a fake success); an email-delivery failure is non-fatal and the inquiry is retained with a `status` marker. Inquiry PII (name/email/company/message) is written only to the database, never to application logs. |

### Self-service billing (`/v1/billing/*`)

`/v1/billing/plans` is public for signup and upgrade discovery. The remaining
self-service billing endpoints require an authenticated tenant API key and scope
all returned data to the caller's tenant. Checkout and portal creation remain
Stripe-mediated: they create real Stripe sessions when Stripe billing is enabled
and fully configured, return mocked URLs only in local mock mode, and fail closed
when configuration is incomplete outside local development.

The tenant-facing payment-status endpoint and the Kyber provider-readiness
surface use the provider-safe billing abstraction. That abstraction defaults to
`internal_only` and supports `stripe`, `manual_invoice`, and
`enterprise_contract` behind explicit external-billing flags; no provider secrets
are returned in customer or operator responses.

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/v1/billing/plans` | GET | Public | Plan catalog for self-service signup and upgrades |
| `/v1/billing/checkout` | POST | API key | Create a Stripe Checkout session, or a local mocked URL in local mock mode |
| `/v1/billing/portal` | POST | API key | Create a Stripe Billing Portal session, or a local mocked URL in local mock mode |
| `/v1/billing/invoices` | GET | API key | List invoices for the caller's tenant |
| `/v1/billing/invoices/{invoice_id}` | GET | API key | Get one invoice's full payload for the caller's tenant |
| `/v1/billing/plan` | GET | API key | Caller-safe contract profile and enabled billing modules |
| `/v1/billing/entitlements` | GET | API key | Caller-safe tenant entitlements |
| `/v1/billing/usage` | GET | API key | Caller tenant usage events for a requested or current billing window |
| `/v1/billing/usage/summary` | GET | API key | Caller tenant billable-usage summary |
| `/v1/billing/invoice-previews` | GET | API key | Caller-safe invoice previews with internal pricing notes removed |
| `/v1/billing/value-created` | GET | API key | Caller-safe value-created events for value-based billing review |
| `/v1/billing/payment-status` | GET | API key | Caller-safe payment status and active provider mode |

### Kyber revenue-operations billing (`/v1/admin/kyber/revops/*`, admin permission required)

These operator endpoints expose revenue-operations state without returning
billing-provider secrets or customer-hidden pricing rationale. Provider readiness
endpoints are safe to run in internal/offline mode and summarize external billing
configuration only as booleans, provider mode, invoice export mode, and product
mapping status.

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/admin/kyber/revops/overview` | GET | Revenue-operations summary, including billing-model mix |
| `/v1/admin/kyber/revops/contracts` | GET | List tenant contract profiles |
| `/v1/admin/kyber/revops/contracts/{tenant_id}` | GET/POST/PATCH | Read, create, or update one tenant contract profile |
| `/v1/admin/kyber/revops/entitlements/{tenant_id}` | GET/POST | List or create tenant entitlements |
| `/v1/admin/kyber/revops/entitlements/{entitlement_id}` | PATCH | Update one tenant entitlement |
| `/v1/admin/kyber/revops/usage` | GET | List all metered usage events |
| `/v1/admin/kyber/revops/usage/{tenant_id}` | GET | List one tenant's metered usage events for a requested or current billing window |
| `/v1/admin/kyber/revops/metering-events` | POST | Record a metered usage event |
| `/v1/admin/kyber/revops/invoice-previews` | GET | List invoice previews |
| `/v1/admin/kyber/revops/invoice-previews/{tenant_id}/generate` | POST | Generate an invoice preview for a billing window |
| `/v1/admin/kyber/revops/invoice-previews/{invoice_preview_id}` | PATCH | Move an invoice preview through `draft`, `review_ready`, `approved`, or `exported` |
| `/v1/admin/kyber/revops/value-created` | GET | List value-created events |
| `/v1/admin/kyber/revops/revenue-leakage` | GET | List or recalculate revenue leakage signals |
| `/v1/admin/kyber/revops/expansion-billing-opportunities` | GET | List expansion billing opportunities |
| `/v1/admin/kyber/revops/provider-status` | GET | Provider mode, health, sync flags, invoice export mode, and mapping status without secrets |
| `/v1/admin/kyber/revops/product-mappings` | GET | Product/price mapping catalog and mapping completeness without secrets |

### Admin tenant lifecycle (admin permission required)

Deactivation and hard deletion revoke every active credential owned by the
tenant, including durable API-key rows and contained `public_ingest_identifier`
records created by the registration path. Deactivation marks durable API keys
revoked before evicting their Redis entries or marking the tenant inactive; the
validator also refuses to rehydrate a revoked row after a cache miss. Hard
deletion revokes those identifiers before removing the tenant row; deactivation
performs the same revocation even when the tenant is already inactive. Both
responses report the number of API keys and public-ingest identifiers revoked so
operators can verify cleanup.

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/admin/tenants/{tenant_id}/deactivate` | POST | Soft-deactivate tenant (suspends new requests; preserves data) |
| `/v1/admin/tenants/{tenant_id}` | DELETE | Hard-delete tenant (GDPR; cascading) |

### SDK utilities (`/sdk/*`, API key required)

| Endpoint | Method | Purpose |
|---|---|---|
| `/sdk/identity/resolve` | POST | Cross-device wallet identity resolution. SDKs call this on init when `autoResumeJourney: true` and fire `onJourneyResumed` with the returned `ResolvedIdentity` if the backend matches a prior session. |

## Billing Endpoints

### Admin billing operations

These endpoints are operator/admin surfaces and are not part of tenant
self-service billing. The overage cycle also runs from the backend lifespan cron.

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/v1/admin/billing/overage-cycle` | POST | Admin | Trigger the monthly overage invoice cycle |

### Kyber revenue-operations billing (`/v1/admin/kyber/revops/*`, admin permission required)

These operator endpoints expose revenue-operations state without returning
billing-provider secrets or customer-hidden pricing rationale. Provider readiness
endpoints are safe to run in internal/offline mode and summarize external billing
configuration only as booleans, provider mode, invoice export mode, and product
mapping status.

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/admin/kyber/revops/overview` | GET | Revenue-operations summary, including billing-model mix |
| `/v1/admin/kyber/revops/contracts` | GET | List tenant contract profiles |
| `/v1/admin/kyber/revops/contracts/{tenant_id}` | GET/POST/PATCH | Read, create, or update one tenant contract profile |
| `/v1/admin/kyber/revops/entitlements/{tenant_id}` | GET/POST | List or create tenant entitlements |
| `/v1/admin/kyber/revops/entitlements/{entitlement_id}` | PATCH | Update one tenant entitlement |
| `/v1/admin/kyber/revops/usage` | GET | List all metered usage events |
| `/v1/admin/kyber/revops/usage/{tenant_id}` | GET | List one tenant's metered usage events for a requested or current billing window |
| `/v1/admin/kyber/revops/metering-events` | POST | Record a metered usage event |
| `/v1/admin/kyber/revops/invoice-previews` | GET | List invoice previews |
| `/v1/admin/kyber/revops/invoice-previews/{tenant_id}/generate` | POST | Generate an invoice preview for a billing window |
| `/v1/admin/kyber/revops/invoice-previews/{invoice_preview_id}` | PATCH | Move an invoice preview through `draft`, `review_ready`, `approved`, or `exported` |
| `/v1/admin/kyber/revops/value-created` | GET | List value-created events |
| `/v1/admin/kyber/revops/revenue-leakage` | GET | List or recalculate revenue leakage signals |
| `/v1/admin/kyber/revops/expansion-billing-opportunities` | GET | List expansion billing opportunities |
| `/v1/admin/kyber/revops/provider-status` | GET | Provider mode, health, sync flags, invoice export mode, and mapping status without secrets |
| `/v1/admin/kyber/revops/product-mappings` | GET | Product/price mapping catalog and mapping completeness without secrets |


The following admin tenant billing endpoints require the `billing` permission.

### GET /v1/admin/tenants/{tenant_id}/billing

Returns the current plan, monthly usage, overage line items, and
projected period total. Pricing reflects the active `PRICING_OPTION`
(`A` Market Entry, `B` Ideal/Fair, `C` Premium). Default: `B`.

```json
{
  "tenant_id": "acme-corp",
  "plan": {
    "plan_id": "P2",
    "display_name": "Professional",
    "monthly_quota": 100000,
    "burst_rpm": 500,
    "member_cap": 3,
    "service_count": 19,
    "subscription_fee": "829",
    "pricing_option": "B"
  },
  "usage": {
    "billing_period": "2026-04",
    "total_requests": 118000,
    "included_quota": 100000,
    "remaining": 0,
    "overage_requests": 18000
  },
  "overage": {
    "line_items": [
      {
        "service_name": "Unification",
        "endpoint_pattern": "/v1/identity/*",
        "overage_requests": 4500,
        "price_per_1k": "1.00",
        "pricing_option": "B",
        "line_total": "4.50"
      }
    ],
    "total": "6.04"
  },
  "projected_period_total": "835.04"
}
```

### GET /v1/admin/tenants/{tenant_id}/billing/usage

Returns a per-service usage breakdown for the current billing period
including total requests, remaining included requests, and per-service
overage counts.

## Activation (self-serve onboarding, flag-gated)

Mounted at `/v1/activation` only when `AETHER_ACTIVATION_ENABLED=true` (default
OFF). Drives a new tenant from plan selection to first proven value; additive to
the CS-driven onboarding subsystem. Tenant scope comes from the authenticated API
key. GETs require `read`; state-changing POSTs require `write`. Full behavior:
`docs/source-of-truth/ACTIVATION.md`.

| Method | Path | Permission | Notes |
|---|---|---|---|
| `GET`  | `/v1/activation/status` | read | Current activation record + derived billing state. |
| `POST` | `/v1/activation/select-plan` | write | Body `{ "plan_tier": "P1".."P4" }`. Records the tier; does not start checkout. |
| `POST` | `/v1/activation/sdk-selection` | write | Body `{ "platforms": ["web", …] }`. |
| `POST` | `/v1/activation/create-sdk-keys` | write | Body `{ "count": 1, "label": "…" }`. Returns raw key(s) **once**. |
| `POST` | `/v1/activation/test-event` | write | Sends a canonical event through `/v1/batch`; per-event `accepted \| duplicate \| rejected`. |
| `GET`  | `/v1/activation/first-value` | read | `{ "state", "ready", "evidence" }` from real Bronze rows. |
| `POST` | `/v1/activation/complete` | write | `409` unless state is `first_value_ready`. |

## Command Center (read-only tenant aggregate, flag-gated)

Mounted at `/v1/command-center` only when `AETHER_COMMAND_CENTER_ENABLED=true`
(default OFF). A read-only aggregator that composes nine existing tenant-scoped
reads in-process into one envelope-per-section view; it owns no state and adds
no table. Each section carries the underlying sub-service payload verbatim plus
an honest state (`live | no_data | not_configured | unavailable | error`) — a
failed or timed-out read degrades to `unavailable`/`error` with `data=null`, and
an empty tenant degrades to `no_data`, never a fabricated value. Tenant scope
comes from the authenticated API key. It forwards only `tenant_id` downstream and
imports no operator-only service, so no operator field can leak into a tenant view.

| Method | Path | Permission | Notes |
|---|---|---|---|
| `GET` | `/v1/command-center` | read | Aggregated view. Sections: `activation`, `value_strip`, `ops_feed`, `graph_snapshot`, `campaign_movement`, `data_confidence`, `integration_health`, `outcomes`, `next_best_actions`. |

## Event Ingestion

### POST /v1/events

Receives batched raw events from the Web SDK.

**Request:**
```json
{
  "batch": [
    {
      "id": "uuid-v4",
      "type": "track|screen|identify|conversion|wallet|transaction|consent",
      "event": "button_clicked",
      "timestamp": "2026-03-05T12:00:00.000Z",
      "sessionId": "uuid-v4",
      "anonymousId": "uuid-v4",
      "userId": "user-123",
      "properties": { "buttonId": "cta-hero" },
      "context": {
        "library": { "name": "@aether/sdk", "version": "8.7.1" },
        "fingerprint": { "id": "sha256-hash" },
        "locale": "en-US",
        "timezone": "America/New_York"
      }
    }
  ],
  "sentAt": "2026-03-05T12:00:05.000Z"
}
```

**Response:** `200 OK`
```json
{ "success": true, "accepted": 10 }
```

### POST /v1/batch

Receives batched raw events from iOS and Android SDKs. Same schema as `/v1/events`.

**Backend Processing (applies to both endpoints):**
- IP enrichment via MaxMind GeoLite2 (country, region, city, ASN, VPN/proxy detection)
- Identity resolution (deterministic + probabilistic cross-device matching)
- Device info derived from User-Agent headers
- Traffic source classification from UTM/referrer data
- Funnel step matching against server definitions
- ML scoring (intent prediction, bot detection)
- Heatmap grid building from coordinate events
- Rage click and dead click detection

---

### GET /v1/config

Returns SDK initialization configuration. Called once on `init()`.

**Query Parameters:**
- `apiKey` (required)
- `platform` (optional): `web|ios|android|react-native`

**Response:**
```json
{
  "featureFlags": {
    "dark-mode": true,
    "upload-limit": 50,
    "new-checkout": { "enabled": true, "variant": "treatment" }
  },
  "funnels": [
    {
      "id": "onboarding",
      "steps": ["signup_started", "email_verified", "profile_completed"]
    }
  ],
  "surveys": [
    {
      "id": "nps-q1",
      "type": "nps",
      "trigger": { "event": "purchase_completed", "delay": 5000 },
      "questions": [
        { "id": "q1", "text": "How likely are you to recommend us?", "type": "rating", "min": 0, "max": 10 }
      ]
    }
  ],
  "settings": {
    "batchSize": 10,
    "flushInterval": 5000,
    "samplingRate": 1.0
  }
}
```

---

## Ledger Chain Verification (integrity)

Operator-gated read surface over the append-only hash chains that Bronze
(`bronze_sdk_events`) and the transactional outbox (`event_outbox`) carry
(`prev_hash`/`integrity_hash`, per tenant). A scheduled `ledger_chain_verifier`
worker (supervised, **gated off by default** via
`LEDGER_CHAIN_VERIFIER_ENABLED`) re-walks each tenant's chain with
`shared/integrity/hash_chain.verify_chain` and records a P1
`ledger_chain_integrity` operator alert on any break.

### GET /v1/security/ledger/chain-verification

**Permission**: operator (mounted under the sensitive `/v1/security` prefix);
`tenant_id` must match the authenticated tenant.

- No query params → dashboard aggregate: counts of tenants **verified** vs.
  with **verification_failures**, plus failing-tenant detail.
- `?tenant_id=<id>` → a live verification of that tenant's chain (does not page;
  the scheduled worker is the alerting authority).

**Response 200**: `{ "verified": <int>, "verification_failures": <int>, "failing_tenants": [...] }` (aggregate) or a single-tenant `ChainVerifierResult` (`verified`, `rows_scanned`, `chains_verified`, `broken_record_ids`, `break_location`).

---

## Transaction & Chain Endpoints

### POST /v1/tx/enrich

Classifies and enriches raw blockchain transaction data.

**Request:**
```json
{
  "txHash": "0xabc123...",
  "chainId": 1,
  "vm": "evm",
  "from": "0x1234...",
  "to": "0x5678...",
  "value": "1500000000000000000",
  "input": "0xa9059cbb000000...",
  "gasUsed": "21000",
  "gasPrice": "30000000000"
}
```

**Response:**
```json
{
  "txHash": "0xabc123...",
  "classification": {
    "type": "swap",
    "protocol": "Uniswap V3",
    "defiCategory": "dex",
    "methodName": "exactInputSingle"
  },
  "gasAnalytics": {
    "gasCostETH": "0.00063000",
    "gasCostUSD": 1.89
  },
  "walletLabels": {
    "from": { "label": "User Wallet", "type": "hot_wallet", "risk": "low" },
    "to": { "label": "Uniswap V3 Router", "type": "smart_contract", "risk": "low" }
  }
}
```

### GET /v1/chains/{chainId}

Returns chain metadata on demand.

**Response:**
```json
{
  "chainId": 1,
  "name": "Ethereum Mainnet",
  "vm": "evm",
  "nativeCurrency": { "name": "Ether", "symbol": "ETH", "decimals": 18 },
  "blockExplorer": "https://etherscan.io",
  "testnet": false
}
```

### GET /v1/protocols/{address}

Identifies a smart contract / protocol by address.

**Query Parameters:** `chainId` (required)

**Response:**
```json
{
  "address": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
  "name": "Uniswap V2 Router",
  "protocol": "uniswap",
  "category": "dex",
  "version": "v2",
  "verified": true
}
```

---

## ML & Classification

### POST /v1/predict

ML inference endpoint (replaces client-side edge-ml).

**Request:**
```json
{
  "type": "intent|bot|session_score|identity|journey|churn|ltv|anomaly|attribution",
  "signals": {
    "scrollDepth": 0.75,
    "timeOnPage": 45,
    "clickCount": 12,
    "formInteractions": 3,
    "pagesViewed": 5,
    "sessionDuration": 180
  }
}
```

**Response:**
```json
{
  "type": "intent",
  "prediction": {
    "primaryIntent": "purchase",
    "confidence": 0.87,
    "signals": ["high_scroll_depth", "form_interaction", "product_views"]
  }
}
```

### POST /v1/classify-source

Classifies a traffic source from raw attribution data.

**Request:**
```json
{
  "referrer": "https://google.com/search?q=aether",
  "utmSource": "google",
  "utmMedium": "cpc",
  "utmCampaign": "brand-q1",
  "clickIds": { "gclid": "abc123" },
  "landingPage": "https://app.aether.io/pricing"
}
```

**Response:**
```json
{
  "channel": "paid_search",
  "source": "google",
  "medium": "cpc",
  "campaign": "brand-q1",
  "attribution": {
    "model": "last_click",
    "touchpoints": [
      { "source": "google", "medium": "cpc", "timestamp": "2026-03-05T11:55:00Z" }
    ]
  }
}
```

### Canonical Traffic Source Classification

SDKs ship raw referrer, UTM, click-ID, landing, user-agent, and optional
`aether_ref` evidence. The server-side `SourceClassifier` classifies that
evidence before the existing Silver touchpoint, campaign resolver, journey
compiler, and attribution engine consume it. Clients must not infer an AI
provider, actor, verification level, or canonical campaign.

**Classification Priority Chain:**

| Priority | Signal | Confidence | Example |
|----------|--------|------------|---------|
| 1 | Machine user agent | 0.98 | `GPTBot` → crawler discovery, attribution-ineligible |
| 2 | Verified referral link | 1.0 | controlled agent placement → verified provider/product evidence |
| 3 | Click IDs | 1.0 | `gclid=abc` → google / cpc / Paid Search |
| 4 | UTM params | 0.95 | `utm_source=newsletter` → newsletter / email / Email |
| 5 | Referrer domain | up to 0.96 | `chatgpt.com` → OpenAI / ChatGPT / AI Referral |
| 6 | No signals | 0.5 | → (direct) / (none) / Direct |

**Supported Click IDs (12):** `gclid`, `msclkid`, `fbclid`, `ttclid`, `twclid`, `li_fat_id`, `rdt_cid`, `scid`, `dclid`, `epik`, `irclickid`, `aff_id`

**Channel Categories:** Paid Search, Paid Social, Organic Search, Organic Social,
Email, Display, Affiliate, Partner, Referral, AI Referral, Agent Referral,
AI Crawler, Machine Referral, Video, Audio, SMS, Push, Direct, Other

Canonical touchpoints preserve `source`, `medium`, and `channel` and add
`source_class`, `referral_mediation_type`, `ai_provider`, `ai_product`,
`actor_type`, `journey_role`, `evidence_confidence`, `verification_level`,
`source_classifier_version`, `attribution_eligible`, and optional verified-link
lineage. Raw referrer query strings, fragments, and referral tokens are not
stored in Bronze or Silver.

**Verified referral link routes:**

| Method | Path | Access |
|---|---|---|
| `POST` | `/v1/referral-links` | admin/editor/service or `referral_links:write` |
| `GET` | `/v1/referral-links` | admin/editor/service or referral-link read/write permission |
| `POST` | `/v1/referral-links/{id}/revoke` | admin/editor/service or `referral_links:write` |

The create response discloses the opaque token once. Only its SHA-256 digest is
persisted, and replayed source events do not increment link usage twice.

**Kyber source-classification routes:**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/kyber/measurement/source-classification/health` | Inspect tenant-scoped classifier coverage and exclusions |
| `POST` | `/v1/kyber/measurement/source-classification/reclassify` | Enqueue bounded historical repair through the existing durable jobs platform |

The repair operation appends touchpoint revisions, creates new journey and
attribution versions, and restates affected measurement windows. It never
edits completed attribution history in place.

**Tenant referral-performance rollup:**

`GET /v1/attribution/referral-performance` returns economic performance from
the tenant's active attribution runs, grouped by source class, referral
mediation, AI provider/product, actor, journey role, and verification level.
Optional `start_at` (inclusive), `end_at` (exclusive), `campaign_id`,
`ai_provider`, `ai_product`, `referral_mediation_type`, and `source_class`
filters constrain the rollup; `limit` is bounded to 1–1000. The response
includes the applied filters, grouped rows, and attributed conversion, gross
revenue, net revenue, and contribution-value totals. It does not recompute or
mutate attribution history.

**Legacy SourceInfo response shape remains compatible:**
```json
{
  "source": "google",
  "medium": "cpc",
  "traffic_type": "Paid Search",
  "confidence": 1.0,
  "referrer_domain": "google.com",
  "click_ids": { "gclid": "abc123" }
}
```

### GET /v1/wallet-label/{address}

Returns risk assessment and label for a wallet address.

**Query Parameters:** `chainId` (optional)

**Response:**
```json
{
  "address": "0x1234...",
  "label": "Binance Hot Wallet",
  "type": "exchange",
  "risk": "low",
  "tags": ["cex", "high_volume", "verified"],
  "firstSeen": "2020-01-15",
  "transactionCount": 1500000
}
```

---

## Rewards (A6: Attribution-Verified Reward Enablement)

Aether **verifies reward eligibility** and **produces reward action payloads**. Tenants execute rewards through their own configured rails. Aether does not hold, transfer, or distribute rewards. See `docs/source-of-truth/REWARD_NO_CUSTODY_MODEL.md`.

### POST /v1/rewards/evaluate

Evaluate a single event for reward eligibility. Returns an eligibility decision and, if eligible, a reward action payload for the tenant's configured rail.

**Request:**
```json
{
  "event_type": "conversion",
  "tenant_id": "tenant_acme",
  "user_id": "user_123",
  "wallet_address": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
  "properties": { "channel": "organic", "value": 49.99 },
  "attribution_result_id": "attr_abc",
  "fraud_decision_id": "fraud_xyz",
  "consent_snapshot_id": "cs_001",
  "idempotency_key": "evt_session_123_conversion"
}
```

**Response:**
```json
{
  "data": {
    "eligible": true,
    "decision": "eligible",
    "decision_reason": "All gates passed",
    "execution_mode": "recommend_only",
    "rail": "recommend_only",
    "campaign_id": "camp_uuid",
    "rule_id": "rule_uuid",
    "decision_id": "dec_uuid",
    "action_payload": {
      "rail": "recommend_only",
      "status": "ready",
      "reward_amount": 25.0,
      "reward_unit": "USD",
      "campaign_id": "camp_uuid",
      "rule_id": "rule_uuid",
      "decision_id": "dec_uuid"
    }
  }
}
```

Decision values: `eligible` | `ineligible` | `needs_review` | `blocked_fraud` | `blocked_consent` | `blocked_identity` | `blocked_wallet_binding` | `blocked_cooldown` | `blocked_cap` | `blocked_budget` | `pending_approval`.

### POST /v1/rewards/evaluate/batch

Evaluate up to 50 events in a single request. Returns an array of decision results with count.

**Request:** Array of evaluate request objects (max 50). Returns HTTP 422 if over limit.

### GET /v1/rewards/decisions

List eligibility decisions for the authenticated tenant. Supports `?decision=eligible&limit=50&offset=0` filters.

### GET /v1/rewards/decisions/{id}

Get a single eligibility decision by ID.

### POST /v1/rewards/campaigns

Create a reward campaign. Campaigns define the scope, attribution model, and budget policy for reward eligibility evaluation.

For `onchain_claim` campaigns, supply `contract_address` and `chain_id` explicitly. Outside `local`/`test` both are **required** on the campaign — the registry gate no longer falls back to `EVM_CHAIN_ID` / `EVM_CONTRACT_ADDRESS`, and the Anvil default contract is rejected — so a campaign missing them is refused (HTTP 422) before any decision is persisted (env fallbacks remain only in local/test). The gate also checks the tenant's active `reward_signer` address against the contract registry's verified `oracle_signer_address`: after a signer rotation that the contract has not been re-verified for, proof generation is refused (HTTP 409) with instruction to re-register the contract, rather than emitting a proof the on-chain contract would reject.

**Request:**
```json
{
  "name": "Q2 Conversion Campaign",
  "description": "Reward verified conversions from organic channels",
  "default_rail": "recommend_only",
  "default_execution_mode": "recommend_only",
  "attribution_model": "last_touch",
  "budget_policy": { "observational_limit_usd": 10000 }
}
```

### GET /v1/rewards/campaigns

List campaigns for the authenticated tenant.

### GET /v1/rewards/campaigns/{id}

Get a single campaign.

### PATCH /v1/rewards/campaigns/{id}

Update campaign fields. Supports updating name, description, status, budget_policy, attribution_model.

### POST /v1/rewards/campaigns/{id}/pause

Pause a campaign. Paused campaigns produce `ineligible` decisions.

### POST /v1/rewards/campaigns/{id}/resume

Resume a paused campaign.

### POST /v1/rewards/campaigns/{id}/archive

Archive a campaign. Archived campaigns cannot be resumed.

### POST /v1/rewards/campaigns/{id}/rules

Add a reward rule to a campaign. Rules define eligibility criteria, reward metadata, and delivery rail.

**Request:**
```json
{
  "name": "Organic Conversion Reward",
  "event_types": ["conversion"],
  "min_attribution_weight": 0.3,
  "max_fraud_score": 40.0,
  "reward_amount": 25.0,
  "reward_unit": "USD",
  "execution_mode": "recommend_only",
  "rail": "recommend_only",
  "cooldown_seconds": 86400,
  "max_per_user": 1,
  "priority": 0
}
```

### GET /v1/rewards/campaigns/{id}/rules

List rules for a campaign.

### GET /v1/rewards/rules/{id}

Get a single rule.

### PATCH /v1/rewards/rules/{id}

Update a rule. Supports updating thresholds, reward amount, execution_mode, rail, cooldown.

### POST /v1/rewards/rules/{id}/enable

Enable a disabled rule.

### POST /v1/rewards/rules/{id}/disable

Disable an active rule without deleting it.

### GET /v1/rewards/actions

List reward action payloads. Supports `?status=pending_approval&limit=50` filters.

### GET /v1/rewards/actions/{id}

Get a single action payload.

### POST /v1/rewards/actions/{id}/approve

Approve a `pending_approval` action. Transitions status to `approved`. Used with the `manual_approval` rail.

### POST /v1/rewards/actions/{id}/reject

Reject a `pending_approval` action. Transitions status to `rejected`.

### POST /v1/rewards/actions/{id}/deliver

Trigger delivery of a ready action payload (for manual or webhook rails).

### POST /v1/rewards/actions/{id}/cancel

Cancel a pending or ready action.

### GET /v1/rewards/proofs

List on-chain claim proofs for the authenticated tenant.

### GET /v1/rewards/proofs/{id}

Get a single proof including signature, message_hash, nonce, expiry, and proof_format.

### POST /v1/rewards/proofs/{id}/revoke

Revoke a proof before it is used. Records revocation reason in audit log.

### POST /v1/rewards/proofs/verify

Verify a proof server-side. Checks signature, expiry, and chain_id. Does not mark as used.

**Request:**
```json
{
  "proof_id": "proof_uuid",
  "user": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
  "signature": "0x...",
  "message_hash": "0x...",
  "chain_id": 1
}
```

### POST /v1/rewards/receipts

Record an execution receipt after a tenant has executed a reward. Aether stores the receipt for audit and attribution credit.

**Request:**
```json
{
  "decision_id": "dec_uuid",
  "rail": "onchain_claim",
  "execution_mode": "onchain_claim",
  "external_execution_id": "tx_abc",
  "tx_hash": "0x...",
  "chain_id": 1,
  "status": "confirmed",
  "receipt_payload": {}
}
```

### GET /v1/rewards/receipts

List execution receipts for the authenticated tenant.

### GET /v1/rewards/receipts/{id}

Get a single execution receipt.

### POST /v1/rewards/rails

Configure a reward delivery rail for the authenticated tenant.

**Request:**
```json
{
  "rail": "tenant_webhook",
  "enabled": true,
  "config": { "timeout_ms": 5000 },
  "webhook_url": "https://example.com/aether-reward",
  "secret_ref": "vault://rewards/webhook-secret"
}
```

Rails (see `docs/_generated/reward-rail-matrix.json` for the canonical tiers):
- Production: `recommend_only` | `manual_approval` | `manual_export` | `tenant_webhook` | `onchain_claim` | `internal_credit`.
- Sandbox: `stripe_credit` (Stripe test mode; live key external). Explicit beta: `x402_credit` (sandbox-only).
- Intentionally unsupported (configuring is refused, HTTP 422): `loyalty_points` | `coupon`.
`internal_credit` / `stripe_credit` / `x402_credit` deliver through the same durable outbox as `tenant_webhook`.

For `tenant_webhook`, a submitted `signing_secret` is **dual-written into the
credential authority** (provider `tenant_webhook`, slot `webhook_signing_secret`)
and replaced by a `secret_ref` before the config is persisted — plaintext never
reaches the stored row, the durable outbox job, an audit record, or any
response. The secret is resolved at the narrow send site with active+previous
rotation overlap. For other rails, secret material under `config` (e.g.
`api_key`) is **write-only**: responses and audit state return `<redacted>` plus
a `has_<key>` marker and a short non-reversible fingerprint — never the value.

### GET /v1/rewards/rails

List configured rails for the authenticated tenant (secrets redacted).

### GET /v1/rewards/rails/{id}

Get a single rail configuration.

### PATCH /v1/rewards/rails/{id}

Update a rail configuration. A rotated `tenant_webhook` `signing_secret`
submitted here is dual-written into the credential authority and replaced by a
`secret_ref` before persistence — identical handling to create, so a PATCH can
never reintroduce plaintext into the stored row.

### POST /v1/rewards/rails/{id}/verify

Trigger verification of a rail configuration (e.g., send a test webhook, verify contract address).

### POST /v1/rewards/rails/{id}/disable

Disable a rail without deleting its configuration.

### POST /v1/rewards/contracts

Register a smart contract for `onchain_claim` proof generation. A verified registry entry is required before any onchain proof can be issued in non-local environments.

Re-registering an existing `(tenant_id, chain_id, contract_address)` updates `oracle_signer_address`, `allowed_campaign_ids`, and `contract_name` and resets `verification_status` to `pending` — a new operator verification is required before proof generation resumes.

`oracle_signer_address` is **required** — set it to the Ethereum address derived from the tenant's `reward_signer` credential (`Account.from_key(key).address`). The `/verify` endpoint rejects registrations where this field does not match the tenant's resolved reward signer.

**Request:**
```json
{
  "chain_id": 1,
  "contract_address": "0xYourContract",
  "contract_name": "AetherRewardEnabler",
  "oracle_signer_address": "0xOracleAddress",
  "vm_type": "evm",
  "allowed_campaign_ids": ["camp_abc"]
}
```

### GET /v1/rewards/contracts

List all registered contracts for the authenticated tenant.

### GET /v1/rewards/contracts/{id}

Get a single registered contract by ID.

### POST /v1/rewards/contracts/{id}/verify

**Requires `rewards:admin` (Aether operator only).** Tenants cannot self-verify — an operator must confirm contract ownership before approving. Validates that `oracle_signer_address` matches the tenant's **resolved reward signer** (`services/rewards/signing.py`, credential-authority backed) — returns 422 if they diverge, 422 if no signer resolves, and 503 if `eth_account` is unavailable (fail-closed; never passes unverified). After successful verification the contract satisfies the registry gate in `POST /v1/rewards/evaluate` for `onchain_claim` rails.

### Kyber operator reward pages (`/v1/admin/kyber`, `require_kyber_operator`)

Read-only operator surfaces consumed by the Kyber UI (fail-closed: non-operator
requests are rejected). All are GET-only and never mutate reward state:

- `GET /v1/admin/kyber/rewards/health` — operator reward-subsystem health summary.
- `GET /v1/admin/kyber/tenants/{tenant_id}/campaigns` — a tenant's campaigns.
- `GET /v1/admin/kyber/tenants/{tenant_id}/decisions` — a tenant's eligibility decisions.
- `GET /v1/admin/kyber/tenants/{tenant_id}/actions` — a tenant's action payloads.
- `GET /v1/admin/kyber/tenants/{tenant_id}/audit` — a tenant's reward audit entries.

---

## Identity Resolution

### GET /v1/resolution/cluster/{user_id}

Get the full identity cluster for a user — all merged profiles, linked devices, IPs, wallets, and emails.

**Response:**
```json
{
  "cluster_id": "clust-abc",
  "canonical_user_id": "user-123",
  "confidence": 1.0,
  "member_count": 3,
  "resolution_status": "auto_merged",
  "members": [
    { "user_id": "user-123", "role": "primary", "joined_at": "2026-01-15T..." },
    { "user_id": "anon-456", "role": "merged", "joined_at": "2026-02-01T..." },
    { "user_id": "anon-789", "role": "merged", "joined_at": "2026-03-01T..." }
  ],
  "linked_devices": [
    { "fingerprint_id": "a1b2c3...", "first_seen": "2026-01-15T...", "observations": 47 },
    { "fingerprint_id": "d4e5f6...", "first_seen": "2026-02-01T...", "observations": 23 }
  ],
  "linked_ips": [
    { "ip_hash": "abc123...", "ip_range": "192.168.1.0/24", "observations": 120 }
  ],
  "linked_wallets": [
    { "address": "0x1234...abcd", "vm": "evm", "ens": "user.eth" },
    { "address": "7nY4...Kx3p", "vm": "svm" }
  ],
  "linked_emails": [
    { "email_hash": "def456...", "domain": "gmail.com" }
  ]
}
```

### GET /v1/resolution/pending

List pending resolution decisions awaiting admin review.

**Query Parameters:** `limit` (optional, default: 50)

**Response:**
```json
{
  "data": [
    {
      "decision_id": "dec-123",
      "profile_a_id": "user-123",
      "profile_b_id": "anon-456",
      "composite_confidence": 0.82,
      "deterministic_match": false,
      "signals": { "fingerprint": 0.85, "ip_cluster": 0.78, "location": 0.6 },
      "created_at": "2026-03-05T12:00:00Z"
    }
  ]
}
```

### POST /v1/resolution/pending/{id}/approve

Admin approves a pending identity merge.

### POST /v1/resolution/pending/{id}/reject

Admin rejects a pending identity merge.

### GET /v1/resolution/audit/{decision_id}

Get the full audit trail for a resolution decision — includes all signal snapshots at decision time.

### GET /v1/resolution/config

Get the current resolution engine configuration.

**Response:**
```json
{
  "auto_merge_threshold": 0.95,
  "review_threshold": 0.70,
  "max_cluster_size": 50,
  "cooldown_hours": 24,
  "require_deterministic_for_auto": true,
  "allow_probabilistic_auto_merge": false
}
```

### PUT /v1/resolution/config

Update resolution engine configuration thresholds.

**Request:**
```json
{
  "auto_merge_threshold": 0.90,
  "review_threshold": 0.65,
  "max_cluster_size": 100
}
```

### POST /v1/resolution/batch

Trigger a batch probabilistic matching job for the tenant.

---

## Intelligence Graph Endpoints (Feature-Flagged)

Three service groups are available when Intelligence Graph feature flags are enabled. All endpoints below return `403 FEATURE_DISABLED` unless the corresponding env var is set to `true`.

> **Required env vars:** `IG_COMMERCE_LAYER=true`, `IG_ONCHAIN_LAYER=true`, `IG_X402_LAYER=true`

### Commerce Service (L3a)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/commerce/payments` | Record payment + create `PAYS` edge in graph |
| POST | `/v1/commerce/hires` | Record agent hire + create `HIRED` edge |
| GET | `/v1/commerce/fees/report` | Fee elimination report for tenant |
| GET | `/v1/commerce/agent/{id}/spend` | Agent spend history |
| GET | `/v1/commerce/agents/{id}/economics` | Full economic profile: budget usage, delegation policy, economic identity |
| GET | `/v1/commerce/revenue/{service_id}` | Service revenue over a time window (settled payments attributed to service) |
| GET | `/v1/commerce/cluster/{id}/spend` | Cluster spend analytics: settled volume and unique agents |
| GET | `/v1/commerce/treasury` | Treasury balance, preferred rails, and spend runway estimate (`commerce:admin`) |
| GET | `/v1/commerce/facilitators/performance` | Per-facilitator performance matrix: volume, success rate, transaction count |

### On-Chain Service (L0)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/onchain/actions` | Record an on-chain action |
| GET | `/v1/onchain/actions/{agent_id}` | List agent's on-chain actions |
| GET | `/v1/onchain/contracts/{address}` | Contract details + call graph |
| POST | `/v1/onchain/listener/configure` | Configure chain event listener |
| GET | `/v1/onchain/rpc/health` | RPC gateway health check |

### x402 Service (L3b)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/x402/capture` | Ingest captured x402 payment |
| GET | `/v1/x402/graph` | Economic graph snapshot |
| GET | `/v1/x402/agent/{id}` | Agent x402 history |
| POST | `/v1/x402/graph/snapshot` | Trigger graph snapshot rebuild |

### Approvals Control Plane (`/v1/approvals`)

Kyber operator review queue for the x402 commerce control plane. All endpoints require `approvals:read` (GET) or `approvals:write` / `commerce:approve` (POST).

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/approvals` | List approval queue — filterable by `status`, `assigned_to` |
| GET | `/v1/approvals/{id}` | Get single approval request with full audit trail |
| POST | `/v1/approvals/{id}/assign` | Assign approval to a reviewer (`assignee_id`, `assigned_by`) |
| POST | `/v1/approvals/{id}/decide` | Apply decision: `approve`, `reject`, or `escalate` with `reason` and optional `is_override` |
| POST | `/v1/approvals/{id}/escalate` | Shorthand escalate — calls decide with `action=escalate` |
| POST | `/v1/approvals/{id}/revoke` | Revoke a previously approved request (`revoked_by`, `reason`) |
| GET | `/v1/approvals/{id}/evidence` | Evidence bundle: approval audit trail, policy decisions, graph impact |
| GET | `/v1/approvals/{id}/preview` | Deterministic preview of graph mutations if approved (read-only, no side effects) |

### Agent Extensions (added to /v1/agent/)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/agent/register` | Register agent in the Intelligence Graph |
| POST | `/v1/agent/tasks/{id}/lifecycle` | Update task lifecycle state |
| POST | `/v1/agent/tasks/{id}/decision` | Record an agent decision |
| POST | `/v1/agent/tasks/{id}/feedback` | Submit feedback on task outcome |
| GET | `/v1/agent/{id}/graph` | Agent's full graph neighborhood |
| GET | `/v1/agent/{id}/trust` | Agent trust score + history |
| POST | `/v1/agent/{id}/a2h` | Record agent-to-human interaction (notification, recommendation, delivery, escalation) |

### Diagnostics Service (Admin Only)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/diagnostics/health` | Quick health check (healthy/degraded/critical) |
| GET | `/v1/diagnostics/errors` | List tracked errors with filters |
| GET | `/v1/diagnostics/report` | Full diagnostics report with breakdowns |
| POST | `/v1/diagnostics/errors/{fingerprint}/resolve` | Mark error as resolved |
| POST | `/v1/diagnostics/errors/{fingerprint}/suppress` | Suppress alerts for known error |
| GET | `/v1/diagnostics/circuit-breakers` | List all circuit breaker states |
| GET | `/v1/diagnostics/commerce/verification-failures` | Recent payment verification failures with reason and tx_hash (`commerce:read`) |
| GET | `/v1/diagnostics/commerce/settlement-timeouts` | Settlements stuck in pending/verifying beyond timeout (`commerce:read`) |
| GET | `/v1/diagnostics/commerce/approval-expirations` | Approval requests expired without a decision (`commerce:read`) |
| GET | `/v1/diagnostics/commerce/duplicate-payments` | Potential duplicate payment attempts within a time window (`commerce:read`) |
| GET | `/v1/diagnostics/commerce/reconciliation-drift` | Payment intents with no corresponding settlement event (`commerce:read`) |

All general diagnostics endpoints require `admin` permission. Commerce diagnostics require `commerce:read`.

**x402 environment & credential-only verification.** Every authorization,
receipt, and settlement carries a credential `environment` (`sandbox` | `live`)
resolved server-side from the tenant's x402 capability activation state — never
from the client. Verification resolves the tenant's own RPC endpoint+key pair
from the credential authority (atomic `{url, api_key, auth_mode}`); a deployed
environment with no configured pair yields the `verification_unavailable`
verdict (fail-closed). `GET /v1/x402/commerce/health` derives its status from
real facilitator health + settlement backlog (never a hardcoded healthy).
Provision RPC/facilitator credentials via the credential API (providers
`rpc_evm_base` / `rpc_svm_mainnet` / … slot `rpc_endpoint_pair`; facilitator
providers slot `facilitator_api_key`).

**Query Parameters (GET /errors):**
- `service` (optional) — filter by service name
- `category` (optional) — filter by error category
- `severity` (optional) — filter by severity level
- `resolved` (optional) — filter by resolution status

### Provider Gateway (BYOK)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/providers/keys` | Store or update an encrypted BYOK API key |
| GET | `/v1/providers/keys` | List tenant's stored BYOK keys (masked) |
| DELETE | `/v1/providers/keys/{provider}` | Remove a BYOK key for a provider |
| GET | `/v1/providers/usage` | Provider usage statistics with optional category/provider filters |
| GET | `/v1/providers/usage/summary` | Tenant-wide usage summary across all providers |
| GET | `/v1/providers/health` | All providers with health status, circuit breaker states, last_successful_sync, error_count, and staleness_label (live/recent/stale) |
| GET | `/v1/providers/categories` | List all provider categories and supported provider names |
| POST | `/v1/providers/test` | Test a provider call (verifies BYOK key works) |

**Permissions:**
- Key management endpoints (`POST/GET/DELETE /keys`) require `admin` permission
- Usage endpoints (`GET /usage`, `GET /usage/summary`) require `billing` permission
- Health and categories endpoints require `admin` permission
- Test endpoint requires `admin` permission

---

### Capability Discovery Service

```
GET /v1/capabilities
```

Returns which Profile360 sub-resources, provider integrations, consent purposes,
and feature flags are active for the calling tenant. Designed for SDK integration-time
discovery — callers can determine available capabilities without trial-and-error.

| Field | Description |
|---|---|
| `profile_sub_resources` | List of available Profile360 sub-resource names (e.g. `social`, `financial`, `attribution`) |
| `providers` | Configured providers with `status`, `last_successful_sync`, `error_count`, `staleness_label`, `circuit_breaker` |
| `consent_purposes_granted` | Consent purposes the tenant has enabled |
| `consent_purposes_all` | Full list of supported consent purposes |
| `feature_flags` | Active flag values: `suggestions_enabled`, `connectors_enabled`, `data_quality_enabled`, etc. |
| `evaluated_at` | ISO-8601 timestamp of the capability snapshot |

**Permissions:** `read` (any authenticated tenant call)
**No feature flag required** — always available once auth passes.

**Provider Categories:**
- `blockchain_rpc` — QuickNode, Alchemy, Infura, Custom RPC
- `block_explorer` — Etherscan, Moralis
- `social_api` — Twitter, Reddit
- `analytics_data` — Dune Analytics

**Priority Chain (every provider call):**
1. Tenant BYOK key → 2. System default provider → 3. Fallback provider(s) → 4. ServiceUnavailableError

Feature flag: `PROVIDER_GATEWAY_ENABLED=false` (default). Zero impact until activated.

### Capability Activation Lifecycle

Persisted, machine-enforced per-(tenant, provider, environment, capability)
lifecycle along the canonical `CredentialReadiness` ladder
(`packages/shared/contracts/readiness-vocabulary.json`). Every transition
records actor, reason, evidence references, and the credential version it is
bound to; promotions are fail-closed (no rung skipping, evidence must resolve,
credential slot must be ACTIVE, entitlement must approve).

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/capabilities/activation` | Current lifecycle state of every capability for the tenant (`read`) |
| GET | `/v1/capabilities/activation/{provider}/{capability}?environment=` | Current state + full promotion/demotion history (`read`) |
| POST | `/v1/capabilities/activation/{provider}/{capability}/promote` | Promote toward `target_state` with `evidence_refs` (`admin`; 400 on illegal/unproven moves) |
| POST | `/v1/capabilities/activation/{provider}/{capability}/suspend` | Reversible suspension (`admin`) |
| POST | `/v1/capabilities/activation/{provider}/{capability}/resume` | Resume to the interrupted certified level (`admin`) |
| GET | `/v1/kyber/capabilities/activation` | Cross-tenant current states (Kyber operator) |
| POST | `/v1/kyber/capabilities/activation/{tenant_id}/{provider}/{capability}/suspend` | Audited operator emergency suspend (kill switch) |

---

### Data Lake Service (v8.5.0)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/lake/ingest` | Ingest provider data into Bronze tier (batch, source-tagged) |
| POST | `/v1/lake/rollback` | Rollback records by source_tag across specified tiers |
| GET | `/v1/lake/audit/{domain}/{source_tag}` | Query audit trail for a source_tag |
| POST | `/v1/lake/materialize` | Write Gold metric/feature/highlight |
| GET | `/v1/lake/gold/{domain}/{entity_id}` | Query Gold metrics for an entity |
| GET | `/v1/lake/quality/{domain}` | Run data quality checks on a domain's Bronze tier |
| POST | `/v1/lake/promote` | Promote a source_tag's Silver records into Gold (`admin`) |
| GET | `/v1/lake/status` | Record counts per domain per tier |

**Domains:** `market`, `onchain`, `social`, `identity`, `governance`, `tradfi`

**Required fields for ingest:** `domain`, `source`, `source_tag`, `records[]`

**Permissions:** `write` for ingest/materialize, `read` for queries, `admin` for rollback/quality

---

### Intelligence Service (v8.5.0)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/intelligence/wallet/{address}/risk` | Composite wallet risk score (trust scorer + graph + features) |
| GET | `/v1/intelligence/protocol/{id}/analytics` | Protocol-level analytics from Gold tier |
| GET | `/v1/intelligence/entity/{id}/cluster` | Identity cluster via graph relationships |
| GET | `/v1/intelligence/alerts` | Anomaly alerts from Gold tier |
| GET | `/v1/intelligence/wallet/{address}/profile` | Full wallet intelligence profile |
| GET | `/v1/intelligence/commerce/lifecycle/{challenge_id}` | Full payment lifecycle trace: requirement → policy → approval → settlement → entitlement (`x402:read`) |

**Permissions:** `read` for intelligence endpoints; `x402:read` for commerce lifecycle trace.

---

### Analytics Service Commerce KPI

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/analytics/commerce/kpi` | Commerce KPI summary: spend rate, approval latency, settlement degradation, entitlement reuse rate (`commerce:read`) |

**Query Parameters:** `period` — `"7d"`, `"30d"`, `"90d"`, `"all"` (default: `"30d"`)

---

### Identity Service (v8.9.0)

Core identity resolution and entity management endpoints.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/identity/resolve` | Resolve cross-device/cross-wallet identity from a set of signals — returns canonical entity_id + confidence |
| GET | `/v1/identity/entities/{entity_id}` | Get full entity record with all linked identifiers |
| GET | `/v1/identity/entities/{entity_id}/aliases` | List all aliases (wallets, emails, devices, sessions) for an entity |
| GET | `/v1/identity/entities/{entity_id}/graph` | Entity subgraph (neighbors, edges, relationship types) |
| GET | `/v1/identity/entities/{entity_id}/audit` | Full audit trail for this entity — merges, splits, signal additions |
| GET | `/v1/identity/conflicts` | List entities with unresolved identity conflicts (`admin`) |
| POST | `/v1/identity/merge` | Merge two entities into a single canonical entity (`admin`) |
| POST | `/v1/identity/split` | Split a merged entity back into its source components (`admin`) |
| POST | `/v1/identity/recompute` | Trigger a full confidence recomputation for one or all entities (`admin`) |
| GET | `/v1/identity/health` | Identity resolution subsystem health — DB ping, total entities, open conflicts, queue depth |
| POST | `/v1/identity/suppress` | Suppress an identifier hash — revokes matching aliases and blocks future resolution (`write`) |
| DELETE | `/v1/identity/suppress/{suppression_id}` | Revoke an active suppression rule (`write`) |
| GET | `/v1/identity/suppressions` | List active suppression rules for the authenticated tenant (`read`) |
| GET | `/v1/identity/profiles/{user_id}` | Get stored profile for a user/entity |
| PUT | `/v1/identity/profiles/{user_id}` | Upsert profile record for a user/entity |
| GET | `/v1/identity/profiles/{user_id}/graph` | Profile-scoped graph view (bounded to 50 neighbors) |

**Permissions:** `read` for GET queries; `write` for resolve/profiles; `admin` for merge/split/recompute/conflicts.

---

### Identity Service — SIWX Session Binding

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/identity/siwx/bind` | Bind a SIWX session to an identity for entitlement reuse (`write`) |
| GET | `/v1/identity/siwx/status/{session_id}` | Check SIWX session binding status |
| DELETE | `/v1/identity/siwx/{session_id}` | Revoke a SIWX session binding (`write`) |

SIWX (Sign-In With X) session bindings allow the entitlement service to reuse active payment entitlements for a wallet session without requiring a new payment challenge.

---

### Profile 360 Service (v8.5.0)

Holistic user/entity omniview — composes data from all Aether subsystems into one canonical profile view. Does not duplicate data; aggregates from identity, analytics, consent, graph, intelligence, and lake subsystems.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/profile/{user_id}` | Full holistic profile (identity + identifiers + consent + timeline + graph + intelligence + lake + provenance) |
| GET | `/v1/profile/{user_id}/timeline` | Paginated event timeline with optional `event_type` filter |
| GET | `/v1/profile/{user_id}/graph` | Graph relationships (bounded to 50 neighbors) |
| GET | `/v1/profile/{user_id}/intelligence` | Risk scores + Gold-tier features + model outputs |
| GET | `/v1/profile/{user_id}/identifiers` | All linked wallets, emails, devices, sessions, social handles |
| GET | `/v1/profile/{user_id}/provenance` | Source attribution across identity, onchain, social data |
| GET | `/v1/profile/resolve` | Resolve any identifier to canonical profile_id (query params: `wallet`, `email`, `device`, `session`, `social`, `customer`) |
| GET | `/v1/profile/{user_id}/lake/{domain}` | Domain-specific Gold data (identity, market, onchain, social) |
| GET | `/v1/profile/{user_id}/campaigns` | Campaign attribution derived from analytics event stream |
| GET | `/v1/profile/{user_id}/tier` | Entity tier (Whale/Shark/Dolphin/Fish/Shrimp) + percentile rank |
| GET | `/v1/profile/{user_id}/asset-composition` | On-chain portfolio composition by asset category |
| GET | `/v1/profile/{user_id}/pnl` | Realized + unrealized PNL, TVL delta |
| GET | `/v1/profile/{user_id}/trading-profile` | On-chain trading behavior (pairs, protocol loyalty, gas) |
| GET | `/v1/profile/{user_id}/location-history` | City-level location history with classification |
| GET | `/v1/profile/{user_id}/temporal-heatmap` | 24×7 activity density matrix + streaks |
| GET | `/v1/profile/{user_id}/social-intelligence` | Cross-platform social aggregation |
| GET | `/v1/profile/{user_id}/journey-economics` | Per-journey ROAS, CPA, LTV, retarget score |
| GET | `/v1/profile/{user_id}/device-performance` | Conversion rate per device type |
| GET | `/v1/profile/{user_id}/funnel` | Staged conversion funnel (Impression→Swap→LP) |
| GET | `/v1/profile/{user_id}/time-to-convert` | Median time between funnel stage transitions |
| GET | `/v1/profile/{user_id}/retarget-recommendations` | Analyst-review retargeting recommendations |
| GET | `/v1/profile/{user_id}/web2` | TradFi + credit signals (requires `credit` consent) |
| GET | `/v1/profile/{user_id}/protocol-metrics` | Protocol TVL/volume/fees (DAO/DEX entities) |
| GET | `/v1/profile/{user_id}/governance-activity` | Governance proposals + votes (DAO entities) |

**Query params:** `include_timeline`, `include_graph`, `include_intelligence`, `include_lake` (all default true), `timeline_limit` (1–500). Intelligence extension endpoints also accept `?window=30d|60d|90d|lifetime`.

**Permissions:** `read` for all profile endpoints

---

### Economic Value Service (v8.9.0)

Unified economic observability across Web2, Web3, agentic (x402), and campaign rails. Entity-scoped breakdowns plus tenant-level rollups. The agentic breakdown is composed from `PaymentIntentRepository` and `SettlementEventRepository` via `AgentProfile360EconomicComposer` (spend by currency normalized to USD, service call counts, settlement reliability) and degrades to an empty response on composer errors.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/profile/{entity_id}/economic` | Full economic breakdown for an entity (Web2 + Web3 + agentic + campaign) |
| GET | `/v1/profile/{entity_id}/economic/web2` | Web2 GMV / revenue / payment volume |
| GET | `/v1/profile/{entity_id}/economic/web3` | Web3 TVL / protocol exposure |
| GET | `/v1/profile/{entity_id}/economic/agentic` | Agentic / x402 spend, service calls, settlement success rate |
| GET | `/v1/profile/{entity_id}/economic/campaigns` | Campaign-attributed economic value |
| GET | `/v1/profile/{entity_id}/economic/warnings` | Entity-level data-quality warnings (mixed currency, stale prices) |
| GET | `/v1/economic/overview` | Tenant economic overview (Total Value Observed, domain split) |
| GET | `/v1/economic/warnings` | Tenant-wide economic data-quality warnings |

**Query params:** entity endpoints accept `?window=realtime|24h|7d|30d|90d|lifetime` (default `lifetime`; tenant overview defaults to `30d`).

**Permissions:** `read` for all economic endpoints

---

### Intelligence Projection Plane (v8.12.0)

A **360** is an intelligence projection over canonical Aether truth — never a
competing system of record. The plane is a fail-isolated `ProviderRegistry` of
`IntelligenceProjectionProvider`s over the shared
`ProjectionRequest`/`ProjectionContext`/`ProjectionResult` contracts (TS +
Python). Nine 360s are implemented native providers (`outcome360`,
`economic360`, `infrastructure360`, `communication360`, `risk360`, `fraud360`,
`temporal360`, `population360`, `geographic360`); the rest are `in_flight`.
`implementationState` is repo metadata, **not** readiness. `infrastructure360`
was the first projection to expose a classified public route, and
`communication360` follows the same read-only route template (every route a GET,
tenant-scoped from the authenticated tenant, capability-gated on
`infrastructure360.read` / `communication360.read`); `risk360` and `fraud360`
expose the same pattern behind their convergence flags (below):

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/infrastructure/{subject_kind}/{subject_id}` | Run the infrastructure360 projection for the requesting tenant (summary / state / deployments / evidence / findings sections; `subject_kind` ∈ `deployment` \| `infrastructure`) |
| GET | `/v1/infrastructure/health` | Plane probe: provider registered + contract-compatible (`availability()` only) |
| GET | `/v1/communication360/{subject_kind}/{subject_id}` | Run the communication360 projection for the requesting tenant (information-fidelity / knowledge / authority / resolution engines over the comms canonical facts; read-only) |
| GET | `/v1/communication360/health` | Plane probe: provider registered + contract-compatible (`availability()` only) |

**Permissions:** `read` + the projection's `infrastructure360.read` / `communication360.read`
capability key (fail-closed). The infrastructure360 provider reads the
`infrastructure_facts` / `infrastructure_state` / `deployments` authorities; the
communication360 provider reads the `communication360_facts` store over the comms
silver path and the ratified information / knowledge / participant authorities.
Both projections are `graphMutationPolicy: read_only` — there is no write path.

`risk360` and `fraud360` expose the same classified read-only projection surface
pattern — each is an `implemented` native provider with
`legacyBindings.migrationMode: converged` (repo metadata, **not** readiness),
`graphMutationPolicy: read_only`, and `ownsCanonicalTruth: false`. The routes are
wired in `main.py` behind the convergence flags `AETHER_RISK360_ENABLED` /
`AETHER_FRAUD360_ENABLED` (both default OFF — when a flag is off the router is
not mounted, so the surface answers 404). Each
mirrors the infrastructure360 surface pattern (every route a GET, tenant-scoped,
no write path) under its own prefix, capability-gated on `risk360.read` /
`fraud360.read`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/risk360/{subject_kind}/{subject_id}` | Run the risk360 projection for the requesting tenant (`subject_kind` ∈ `entity` \| `relationship` \| `cluster` \| `population`); 404 for an unserved kind, 503 when the provider is unregistered |
| GET | `/v1/risk360/health` | Plane probe: risk360 provider registered + contract-compatible (`availability()` only) |
| GET | `/v1/fraud360/{subject_kind}/{subject_id}` | Run the fraud360 projection for the requesting tenant (`subject_kind` ∈ `entity` \| `relationship` \| `agent`); 404 for an unserved kind, 503 when the provider is unregistered |
| GET | `/v1/fraud360/health` | Plane probe: fraud360 provider registered + contract-compatible (`availability()` only) |

---

### Exploration Fabric — Sessions & Operations (v8.12.0)

The Exploration Fabric (`/v1/explore`) is the context-preserving
query/filter/presentation workbench over every analytical surface. Its
validate/query/facets/views/links endpoints and the per-surface adapter model
are documented in `docs/source-of-truth/EXPLORATION_FABRIC.md`; this section
covers the **sessions + operations** surface, added over the S1 projection
engine. An `ExplorationSession` persists one tenant-scoped exploration —
surface, seed `ExplorationContextV1`, op history, and current context — and
every submitted filter stays accounted for (no silent drops). Flag-gated inside
every handler via `AETHER_EXPLORATION_ENABLED` (default OFF): when the flag is
off the surface answers 404, indistinguishable from an unmounted route.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/explore/sessions` | Create a session from a seed `ExplorationContextV1` (optional client-supplied `session_id`); returns the persisted `ExplorationSession` |
| GET | `/v1/explore/sessions` | List the tenant's sessions (`limit` ≤ 500, `offset` pagination) |
| GET | `/v1/explore/sessions/{session_id}` | Load one session (404 when absent) |
| DELETE | `/v1/explore/sessions/{session_id}` | Delete one session (404 when absent) |
| POST | `/v1/explore/sessions/{session_id}/operations` | Apply one operation to the session; returns `{result, session}` — `result` carries the post-op context, op status (`applied` \| `rejected` \| `degraded`), and, for projection surfaces, the S1 engine composition summary |

**Operation vocabulary:** `OPEN` \| `PIVOT` \| `EXPAND` \| `COLLAPSE` \|
`FILTER_ADD` \| `FILTER_REMOVE` \| `LENS_ADD` \| `TIME_TRAVEL` \| `DRILL_DOWN`
\| `RESET` \| `SAVE` \| `LOAD`. Operations are PURE context transforms over the
session's `current_context` (which may carry a lens set / engine temporal
mode); `SAVE`/`LOAD` are session-repository operations handled by the service
layer.

**Permissions:** `write` for create/delete/apply-operation, `read` for
list/load — both behind the feature flag. All session ids are
tenant-qualified: a caller can only reach its own tenant's sessions.

---

### Population Intelligence Service (v8.5.0)

Macro-to-micro group intelligence. Supports segments, cohorts, clusters, communities, batches, archetypes, anomaly groups, lookalike groups, risk groups, and lifecycle groups.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/population/summary` | Population overview: total groups, type distribution, top groups |
| GET | `/v1/population/groups` | List all groups with optional `population_type` filter |
| GET | `/v1/population/trends` | Group creation over time |
| POST | `/v1/population/groups` | Create a new group (segment, cohort, cluster, community, etc.) |
| GET | `/v1/population/groups/{id}` | Group details with member count |
| GET | `/v1/population/groups/{id}/members` | Paginated members with `min_confidence` filter |
| POST | `/v1/population/groups/{id}/members` | Add members with basis, confidence, reason, source_tag |
| GET | `/v1/population/groups/{id}/intelligence` | Group intelligence summary (basis distribution, avg confidence) |
| GET | `/v1/population/compare` | Compare two groups: overlap, unique counts (`group_a`, `group_b` query params) |
| GET | `/v1/population/entity/{id}/memberships` | All groups an entity belongs to (enriched with names/types) |
| GET | `/v1/population/entity/{id}/explain/{pop_id}` | Explain why an entity is in a specific group |

**Group types:** `segment`, `cohort`, `cluster`, `community`, `batch`, `archetype`, `anomaly`, `lookalike`, `risk`, `lifecycle`

**Membership basis:** `rule`, `graph`, `ml_model`, `similarity`, `manual`, `inferred`

**Permissions:** `write` for create/add members, `read` for queries

---

### Expectation Engine Service (v8.5.0)

Negative-space intelligence: what should have happened but did not. Detects absence, contradiction, and source silence across macro/meso/micro levels.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/expectations/summary` | Population-wide expected vs actual summary |
| GET | `/v1/expectations/contradictions` | Top contradictions across the population |
| GET | `/v1/expectations/silence` | Source silence vs real behavior change (explicitly separated) |
| GET | `/v1/expectations/group/{pop_id}` | Group expectation view |
| GET | `/v1/expectations/group/{pop_id}/gaps` | Missing expected behaviors for a group |
| GET | `/v1/expectations/entity/{id}` | Full expectation scan for an entity (runs all detectors) |
| GET | `/v1/expectations/entity/{id}/signals` | Signals filtered by `signal_type` |
| GET | `/v1/expectations/entity/{id}/explain` | Why this entity is unusual — top signals with explanations |
| POST | `/v1/expectations/scan/{id}` | Trigger full expectation scan for an entity |
| GET | `/v1/expectations/signal/{id}` | Signal detail with full provenance |

**Signal types (ranked by business priority):** `identity_contradiction`, `relationship_contradiction`, `broken_sequence`, `missing_expected_action`, `missing_expected_edge`, `peer_deviation`, `self_deviation`, `cohort_anomaly`, `source_silence`, `temporal_contradiction`, `model_contradiction`, `graph_contradiction`

**Every signal includes:** `expected`, `observed`, `baseline_source`, `confidence`, `explanation`, `is_source_silence`, `severity`, `source_tag`

**Permissions:** `read` for queries, `write` for triggering scans

---

### Behavioral Continuity & Friction Service (v8.6.0)

Derived signals from data Aether already collects. 10 signal families detecting intent residue, wallet friction, identity deltas, sequence scars, source shadow, and more.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/behavioral/entity/{id}` | Full behavioral scan (all 10 engines) |
| GET | `/v1/behavioral/entity/{id}/signals` | Persisted signals filtered by `family` |
| POST | `/v1/behavioral/scan/{id}` | Trigger full behavioral scan |
| GET | `/v1/behavioral/summary` | Population behavioral signal distribution |
| GET | `/v1/behavioral/registry` | Signal definitions and output contracts |

**Signal families:** `intent_residue`, `wallet_friction`, `identity_delta`, `pre_post_continuity`, `sequence_scar`, `source_shadow`, `reward_near_miss`, `social_chain_lag`, `cex_dex_transition`, `behavioral_twin`

**Permissions:** `read` for queries, `write` for triggering scans

---

### RWA Intelligence Graph Service (v8.6.0)

Tokenized real-world asset observation, analysis, and scoring. Aether does NOT issue RWAs — this is intelligence only.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/rwa/assets` | Register an RWA asset as intelligence object |
| GET | `/v1/rwa/assets` | List assets with `asset_class` and `chain` filters |
| GET | `/v1/rwa/assets/{id}` | Full asset details |
| POST | `/v1/rwa/policies` | Register compliance/transfer-restriction policy |
| GET | `/v1/rwa/assets/{id}/policies` | Policies for an asset |
| POST | `/v1/rwa/simulate-transfer` | Simulate transfer policy check (whitelist, jurisdiction, holder cap, lockup, accreditation) |
| POST | `/v1/rwa/cashflows` | Record cashflow event (coupon, dividend, redemption, NAV update, attestation, etc.) |
| GET | `/v1/rwa/assets/{id}/cashflows` | Cashflow history filtered by `cashflow_type` |
| GET | `/v1/rwa/exposure/{entity_id}` | RWA exposure for wallet/entity (direct + inferred + concentration) |
| GET | `/v1/rwa/assets/{id}/reserve-credibility` | Reserve credibility score (attestation cadence + NAV freshness) |
| GET | `/v1/rwa/assets/{id}/redemption-pressure` | Redemption pressure score |
| POST | `/v1/rwa/holders` | Register holder record |
| GET | `/v1/rwa/assets/{id}/holders` | Asset holder list |

**Asset classes:** `tokenized_treasury`, `money_market_fund`, `private_credit`, `fund_interest`, `structured_credit`, `tokenized_deposit`, `real_estate`, `invoice_receivable`, `trade_finance`, `commodity`, `carbon_credit`, `tokenized_equity`, `tokenized_etf`

**Policy types:** `whitelist`, `accreditation`, `jurisdiction`, `lockup`, `holder_cap`, `secondary_transfer`, `aml_kyc`

**Permissions:** `write` for asset/policy/cashflow/holder creation, `read` for queries

---

All intelligence outputs are sourced from persisted lake data, graph relationships, and ML model scoring. No mock or synthetic data is returned.

---

### Web3 Coverage Service (v8.7.0)

Registry-first Web3 intelligence system with canonical chain/protocol/app/domain/token registries, contract classification, migration tracking, and graph-native coverage spine.

**Chain Registry**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/chains` | Register a chain |
| `GET` | `/v1/web3/chains` | List chains (filter: `vm_family`) |
| `GET` | `/v1/web3/chains/{chain_id}` | Get chain details |

**Protocol Registry**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/protocols` | Register a protocol |
| `GET` | `/v1/web3/protocols` | List protocols (filter: `family`, `chain`, search: `q`) |
| `GET` | `/v1/web3/protocols/{protocol_id}` | Get protocol details |

**Contract Registry**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/contracts` | Register a contract instance |
| `GET` | `/v1/web3/contracts/{chain_id}/{address}` | Get contract details |
| `GET` | `/v1/web3/contracts/unclassified` | List unclassified contracts |
| `POST` | `/v1/web3/contracts/{chain_id}/{address}/reclassify` | Reclassify a contract |

**Token Registry**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/tokens` | Register a token |
| `GET` | `/v1/web3/tokens` | List tokens (filter: `chain_id`, `stablecoins`) |

**App / Domain Registry**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/apps` | Register an app/dApp |
| `GET` | `/v1/web3/apps` | List apps |
| `POST` | `/v1/web3/domains` | Register a frontend domain |
| `GET` | `/v1/web3/domains/{domain}` | Get domain attribution |

**Governance Registry**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/governance/spaces` | Register a governance space |
| `GET` | `/v1/web3/governance/spaces` | List governance spaces |

**Classification**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/classify/contract` | Classify a contract address |
| `POST` | `/v1/web3/classify/method` | Map method selector to canonical action |
| `POST` | `/v1/web3/classify/domain` | Attribute a frontend domain |
| `POST` | `/v1/web3/classify/observation` | Classify a full Web3 observation |

**Observation Ingestion**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/observations/batch` | Bulk ingest Web3 observations (up to 500/batch) |

**Migration Tracking**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/web3/migrations` | Record a protocol migration |
| `GET` | `/v1/web3/migrations/{protocol_id}` | List migrations for a protocol |
| `POST` | `/v1/web3/migrations/detect` | Detect if a new contract is a migration |

**Coverage & Administration**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/web3/coverage/status` | Aggregated coverage status across all registries |
| `GET` | `/v1/web3/coverage/health` | Quick health check (seeded/unseeded) |
| `POST` | `/v1/web3/seed` | Seed registries with initial data (admin) |

---

### Cross-Domain TradFi/Web2 Intelligence Service (v8.7.0)

Unified cross-domain business, TradFi, and Web intelligence graph with financial accounts, instruments, trade lifecycle, compliance, and identity fusion.

**Institutions**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/crossdomain/institutions` | Register an institution |
| `GET` | `/v1/crossdomain/institutions` | List institutions (filter: `institution_type`, search: `q`) |
| `GET` | `/v1/crossdomain/institutions/{institution_id}` | Get institution details |

**Accounts**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/crossdomain/accounts` | Register a financial account |
| `GET` | `/v1/crossdomain/accounts` | List accounts (filter: `owner`, `institution`, `account_type`) |
| `GET` | `/v1/crossdomain/accounts/{account_id}` | Get account details |
| `GET` | `/v1/crossdomain/accounts/{account_id}/positions` | List account positions |

**Instruments**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/crossdomain/instruments` | Register a market instrument |
| `GET` | `/v1/crossdomain/instruments` | List instruments (filter: `instrument_type`, `issuer`, search: `q`) |
| `GET` | `/v1/crossdomain/instruments/{instrument_id}` | Get instrument details |
| `GET` | `/v1/crossdomain/instruments/symbol/{symbol}` | Get instrument by ticker symbol |

**Positions / Orders / Executions / Balances / Cash**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/crossdomain/positions` | Record a position snapshot |
| `GET` | `/v1/crossdomain/positions/instrument/{instrument_id}` | List positions by instrument |
| `POST` | `/v1/crossdomain/orders` | Record a trade order |
| `GET` | `/v1/crossdomain/orders/{account_id}` | List orders by account |
| `POST` | `/v1/crossdomain/executions` | Record a trade execution |
| `GET` | `/v1/crossdomain/executions/order/{order_id}` | List executions by order |
| `GET` | `/v1/crossdomain/executions/account/{account_id}` | List executions by account |
| `POST` | `/v1/crossdomain/balances` | Record a balance snapshot |
| `GET` | `/v1/crossdomain/balances/{account_id}/latest` | Get latest balance |
| `POST` | `/v1/crossdomain/cash-movements` | Record a cash movement |
| `GET` | `/v1/crossdomain/cash-movements/{account_id}` | List cash movements |

**Compliance / Business Events**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/crossdomain/compliance/actions` | Record a compliance action |
| `GET` | `/v1/crossdomain/compliance/actions/{entity_id}` | List compliance actions for entity |
| `POST` | `/v1/crossdomain/events` | Record a business application event |
| `GET` | `/v1/crossdomain/events/entity/{entity_id}` | List events by entity |
| `GET` | `/v1/crossdomain/events/instrument/{instrument_id}` | List events by instrument |

**Cross-Domain Identity Links**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/crossdomain/links` | Create a cross-domain identity link |
| `GET` | `/v1/crossdomain/links/{entity_id}` | List identity links for entity |
| `GET` | `/v1/crossdomain/links/high-confidence` | List high-confidence cross-domain links |

**Fusion / Intelligence**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/crossdomain/fusion/exposure/{entity_id}` | Cross-domain exposure graph |
| `GET` | `/v1/crossdomain/fusion/profile/{entity_id}` | Unified cross-domain profile |
| `GET` | `/v1/crossdomain/coverage/status` | Coverage status across registries |
| `GET` | `/v1/crossdomain/coverage/health` | Quick health check |

---

### Event Replay Service (v8.8.0)

Replay Bronze-tier events back through the pipeline and ingest individual `EventPipelineEnvelope` records.

#### POST /v1/events/replay

Submit a new event replay job sourced from a Bronze-tier `sourceTag`. Returns immediately with status `queued`.

**Permissions:** `write`

**Request:**
```json
{
  "tenantId": "acme-corp",
  "sourceTag": "onchain-2026-03",
  "fromTime": "2026-03-01T00:00:00Z",
  "toTime": "2026-03-31T23:59:59Z",
  "eventTypes": ["wallet.transfer", "wallet.swap"],
  "dryRun": false
}
```

**Response:** `200 OK`
```json
{
  "id": "job-uuid-v4",
  "tenantId": "acme-corp",
  "sourceTag": "onchain-2026-03",
  "fromTime": "2026-03-01T00:00:00Z",
  "toTime": "2026-03-31T23:59:59Z",
  "eventTypes": ["wallet.transfer", "wallet.swap"],
  "dryRun": false,
  "status": "queued",
  "cursor": null,
  "submittedAt": "2026-05-17T10:00:00.000Z",
  "completedAt": null,
  "totalReplayed": 0
}
```

**`status` values:** `queued` | `running` | `completed` | `failed` | `cancelled`

#### GET /v1/events/replay

List all replay jobs for the authenticated tenant.

**Permissions:** `read`

**Query Parameters:**
- `tenantId` (required)
- `limit` (optional, default: 50, max: 500)

**Response:** `200 OK` — array of `ReplayJobResponse` objects (same shape as POST response above).

#### GET /v1/events/replay/{job_id}

Get the current status and progress of a specific replay job.

**Permissions:** `read`

**Query Parameters:** `tenantId` (required)

**Response:** `200 OK` — single `ReplayJobResponse` object.

#### POST /v1/events/replay/{job_id}/cancel

Cancel a queued or running replay job. Sets `status` to `cancelled` and records `completedAt`.

**Permissions:** `write`

**Query Parameters:** `tenantId` (required)

**Response:** `200 OK` — updated `ReplayJobResponse` with `status: "cancelled"`.

#### POST /v1/events/ingest

Ingest a single `EventPipelineEnvelope` (used by the replay feed to re-introduce events into the processing pipeline). Enforces tenant isolation before accepting.

**Permissions:** `write`

**Request:** Full `EventPipelineEnvelope` object:
```json
{
  "id": "evt-uuid-v4",
  "type": "entity.updated",
  "tenantId": "acme-corp",
  "orgId": "org-1",
  "occurredAt": "2026-03-15T08:30:00Z",
  "ingestedAt": "2026-03-15T08:30:01Z",
  "schemaVersion": "1.0.0",
  "source": "replay-feed",
  "subject": { "id": "entity-123", "kind": "wallet" },
  "correlationId": "corr-abc",
  "causationId": null,
  "replayable": true,
  "payload": {}
}
```

**Response:** `200 OK`
```json
{ "ingested": true, "id": "evt-uuid-v4" }
```

---

### Governance Service (v8.8.0)

Policy decision evaluation and audit trail for `GovernanceDecision` records.

#### POST /v1/governance/decisions/evaluate

Evaluate a policy decision for the given principal, action, and resource. The decision is stored for audit purposes and returned immediately.

**Permissions:** `write`

**Request:**
```json
{
  "tenantId": "acme-corp",
  "principal": { "id": "user-123", "kind": "individual" },
  "action": "transfer.approve",
  "resource": { "id": "asset-456", "kind": "rwa_asset" },
  "context": { "jurisdiction": "US", "amount": 50000 },
  "policyIds": ["policy-kyc-us", "policy-aml-threshold"]
}
```

**Response:** `200 OK`
```json
{
  "id": "decision-uuid-v4",
  "tenantId": "acme-corp",
  "principal": { "id": "user-123", "kind": "individual" },
  "action": "transfer.approve",
  "resource": { "id": "asset-456", "kind": "rwa_asset" },
  "allowed": true,
  "policies": ["policy-kyc-us", "policy-aml-threshold"],
  "obligations": null,
  "explanation": {
    "summary": "Policies evaluated: policy-kyc-us, policy-aml-threshold",
    "features": null,
    "evidence": [],
    "lineageEventIds": null,
    "policyIds": ["policy-kyc-us", "policy-aml-threshold"]
  },
  "evaluatedAt": "2026-05-17T10:00:00.000Z"
}
```

To force a deny, include `"deny": true` in `context`.

#### GET /v1/governance/decisions

List governance decisions for the authenticated tenant with optional filters.

**Permissions:** `read`

**Query Parameters:**
- `tenantId` (required)
- `principal_id` (optional) — filter by principal entity ID
- `allowed` (optional, boolean) — filter by outcome
- `limit` (optional, default: 50, max: 500)

**Response:** `200 OK` — array of `GovernanceDecision` objects.

#### GET /v1/governance/decisions/{decision_id}

Retrieve a specific governance decision by ID.

**Permissions:** `read`

**Query Parameters:** `tenantId` (required)

**Response:** `200 OK` — single `GovernanceDecision` object.

#### GET /v1/governance/audit

Return the full audit trail of governance decisions for the authenticated tenant. Ordered by `evaluatedAt` descending.

**Permissions:** `read`

**Query Parameters:**
- `tenantId` (required)
- `principal_id` (optional) — filter by principal entity ID
- `limit` (optional, default: 100, max: 500)

**Response:** `200 OK` — array of `GovernanceDecision` objects (same shape as above).

---

### Investigations Service (v8.8.0)

Case management for `InvestigationCase` records, including evidence and annotation workflows.

**`status` values:** `open` | `triage` | `active` | `escalated` | `closed`

#### POST /v1/investigations

Create a new investigation case. Initial status is always `open`.

**Permissions:** `write`

**Request:**
```json
{
  "tenantId": "acme-corp",
  "title": "Suspicious wallet cluster — March 2026",
  "subjects": [
    { "id": "wallet-0x1234", "kind": "wallet" },
    { "id": "wallet-0x5678", "kind": "wallet" }
  ],
  "createdBy": "analyst-user-id"
}
```

**Response:** `200 OK`
```json
{
  "id": "case-uuid-v4",
  "tenantId": "acme-corp",
  "title": "Suspicious wallet cluster — March 2026",
  "status": "open",
  "subjects": [
    { "id": "wallet-0x1234", "kind": "wallet" },
    { "id": "wallet-0x5678", "kind": "wallet" }
  ],
  "graphStateId": null,
  "evidence": [],
  "annotations": [],
  "createdBy": "analyst-user-id",
  "createdAt": "2026-05-17T10:00:00.000Z",
  "updatedAt": "2026-05-17T10:00:00.000Z"
}
```

#### GET /v1/investigations

List investigation cases for the authenticated tenant, optionally filtered by status.

**Permissions:** `read`

**Query Parameters:**
- `tenantId` (required)
- `status` (optional) — filter by case status
- `limit` (optional, default: 50, max: 500)

**Response:** `200 OK` — array of `InvestigationCase` objects.

#### GET /v1/investigations/{case_id}

Retrieve a single investigation case by ID.

**Permissions:** `read`

**Query Parameters:** `tenantId` (required)

**Response:** `200 OK` — single `InvestigationCase` object (same shape as POST response above).

#### PATCH /v1/investigations/{case_id}/status

Transition an investigation case to a new status. Any → any transitions are permitted for MVP.

**Permissions:** `write`

**Request:**
```json
{
  "tenantId": "acme-corp",
  "status": "active",
  "reason": "Escalated after graph traversal confirmed link to known fraud ring"
}
```

**Response:** `200 OK` — updated `InvestigationCase` object with new `status` and `updatedAt`.

#### POST /v1/investigations/{case_id}/evidence

Append one or more `EvidenceRef` entries to an investigation case.

**Permissions:** `write`

**Request:**
```json
{
  "tenantId": "acme-corp",
  "evidence": [
    {
      "id": "ev-uuid-1",
      "type": "transaction",
      "source": "onchain-indexer",
      "observedAt": "2026-03-15T08:00:00Z",
      "confidence": 0.95,
      "uri": "https://etherscan.io/tx/0xabc..."
    }
  ]
}
```

**`EvidenceRef.type` values:** `event` | `entity` | `relationship` | `document` | `transaction` | `model_output` | `annotation`

**Response:** `200 OK` — updated `InvestigationCase` with the new evidence appended to `evidence[]`.

#### POST /v1/investigations/{case_id}/annotations

Add a new annotation to an investigation case.

**Permissions:** `write`

**Request:**
```json
{
  "tenantId": "acme-corp",
  "authorId": "analyst-user-id",
  "body": "Confirmed entity cluster overlaps with the March 2026 RWA fraud pattern.",
  "entityRefs": [{ "id": "wallet-0x1234", "kind": "wallet" }],
  "evidenceRefs": [{ "id": "ev-uuid-1", "type": "transaction", "source": "onchain-indexer" }]
}
```

**Response:** `200 OK` — updated `InvestigationCase` with the new annotation appended to `annotations[]`.

**`InvestigationAnnotation` shape:**
```json
{
  "id": "annotation-uuid-v4",
  "authorId": "analyst-user-id",
  "body": "Confirmed entity cluster overlaps with the March 2026 RWA fraud pattern.",
  "entityRefs": [{ "id": "wallet-0x1234", "kind": "wallet" }],
  "evidenceRefs": [{ "id": "ev-uuid-1", "type": "transaction", "source": "onchain-indexer" }],
  "createdAt": "2026-05-17T10:05:00.000Z"
}
```

---

### Realtime WebSocket — Channel Protocol (v8.8.0)

**`WS /v1/realtime/ws/subscribe`**

Multi-channel WebSocket endpoint implementing the full `RealtimeSubscribeMessage` contract from `packages/shared/operational-intelligence.ts`. Authentication is enforced via the upstream middleware; `read` permission is required.

#### Connection

Connect with no query parameters. The server does **not** send a hello frame — the client must send a `subscribe` message to begin receiving events.

#### Client → Server Messages

**Subscribe**
```json
{
  "action": "subscribe",
  "requestId": "req-uuid-1",
  "tenantId": "acme-corp",
  "channels": ["entity.profile", "investigation.workspace", "governance.audit"],
  "filters": {
    "entityIds": ["wallet-0x1234"],
    "investigationIds": ["case-uuid-v4"]
  },
  "cursor": "1747476000000:42"
}
```

- `requestId` — caller-generated; echoed back in the `ack`.
- `channels` — one or more `RealtimeChannel` values (see list below).
- `filters` — optional; narrows events delivered on subscribed channels.
- `cursor` — optional; opaque cursor from a previous session for forward-compat resume (server accepts and acks; replay is deferred).

**Unsubscribe**
```json
{
  "action": "unsubscribe",
  "requestId": "req-uuid-2",
  "channels": ["governance.audit"]
}
```

#### Server → Client Messages

**Ack** (sent immediately after each `subscribe` or on validation failure)
```json
{
  "action": "ack",
  "requestId": "req-uuid-1",
  "accepted": true,
  "cursor": "1747476000000:42"
}
```

On failure:
```json
{
  "action": "ack",
  "requestId": "req-uuid-1",
  "accepted": false,
  "error": {
    "code": "forbidden",
    "message": "tenantId mismatch",
    "requestId": "req-uuid-1"
  }
}
```

**Event** (one frame per qualifying event)
```json
{
  "action": "event",
  "channel": "entity.profile",
  "cursor": "1747476300000:1",
  "event": {
    "id": "evt-uuid-v4",
    "type": "entity.updated",
    "tenantId": "acme-corp",
    "occurredAt": "2026-05-17T10:05:00Z",
    "ingestedAt": "2026-05-17T10:05:00.050Z",
    "schemaVersion": "1.0.0",
    "source": "intelligence-engine",
    "subject": { "id": "wallet-0x1234", "kind": "wallet" },
    "replayable": true,
    "payload": {}
  }
}
```

**Heartbeat** (sent every ~15 seconds when no event is available)
```json
{
  "action": "heartbeat",
  "serverTime": "2026-05-17T10:05:15.000Z"
}
```

#### Cursor Format

Cursors are monotonic strings in the format `<wall-clock-ms>:<sequence>` (e.g. `"1747476000000:42"`). Pass the last received cursor in a subsequent `subscribe` message to signal resume intent. Server-side replay is deferred; the cursor is accepted and echoed in the ack for forward compatibility.

#### Available Channels

| Channel | Description |
|---------|-------------|
| `tenant.events` | All events for the tenant |
| `tenant.graph` | Graph mutation events |
| `tenant.alerts` | Anomaly and risk alerts |
| `entity.profile` | Entity profile updates |
| `entity.relationships` | Relationship change events |
| `journey.timeline` | Journey state and timeline updates |
| `cluster.membership` | Cluster membership changes |
| `investigation.workspace` | Investigation case updates |
| `governance.audit` | Governance decision evaluations |
| `agent.coordination` | Agent coordination events |
| `web3.wallets` | Web3 wallet events |

#### Close Codes

| Code | Reason |
|------|--------|
| `4401` | Unauthenticated — no tenant context on the connection |
| `4403` | Forbidden — tenant lacks `read` permission |

### Campaign Management Service (v8.8.0)

Multi-channel campaign management with attribution and touchpoint tracking.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/campaigns` | List campaigns for the tenant |
| POST | `/v1/campaigns` | Create a campaign |
| GET | `/v1/campaigns/{id}` | Get campaign details |
| PATCH | `/v1/campaigns/{id}` | Update campaign fields |
| DELETE | `/v1/campaigns/{id}` | Delete a campaign |
| GET | `/v1/campaigns/{id}/attribution` | Multi-touch attribution for a campaign |
| POST | `/v1/campaigns/{id}/touchpoints` | Record a campaign touchpoint (publishes `aether.campaign.touchpoint.recorded`) |
| GET | `/v1/campaigns/{id}/journeys` | List current journey versions that include steps from this campaign (keyset-paginated by `started_at`) |

**Permissions:** `campaign:manage` for create/update/delete, `campaign:read` for queries

---

### Canonical Journey API (v8.12.0)

Unified cross-rail journey compilation — Web2, Web3, agent, x402, and campaign activity interleaved in a single deterministic timeline.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/journeys` | List current journey versions for the tenant (filterable by `profile_id`, `journey_state`) |
| GET | `/v1/journeys/{id}` | Get the current journey version for a journey |
| GET | `/v1/journeys/{id}/versions` | List all versions of a journey, newest first |
| GET | `/v1/journeys/{id}/steps` | Paginated journey steps (filterable by `family`, `status`, `session_id`, `wallet_id`, `chain_id`, `campaign_id`) |
| GET | `/v1/journeys/{id}/steps/{step_id}` | Single step with full activity detail |
| GET | `/v1/journeys/{id}/transitions` | Transition type summary between steps |
| GET | `/v1/journeys/{id}/explain` | Identity evidence and confidence explanation |
| POST | `/v1/journeys/{id}/rebuild` | Trigger a manual journey recompile |
| GET | `/v1/profiles/{profile_id}/unified-journey` | Current journey for a profile (Profile360 integration) |
| POST | `/v1/web3/status-change` | Receive a Web3 tx status update from the chain indexer; updates `canonical_activity` and triggers journey rebuilds |

**Permissions:** `read` for GET endpoints; `write` required for `/v1/web3/status-change` and `/v1/journeys/{id}/rebuild`

---

### Entity Intelligence Service (v8.8.0)

Deep entity profiling — aggregates identity, graph, temporal, financial, and behavioral dimensions into a unified entity profile.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/entities/profile` | Build a full multi-dimensional entity profile (identity, device, geo, wallet, behavior dimensions) |
| POST | `/v1/entities/timeline/query` | Query temporal event timeline for an entity with filters and pagination |
| POST | `/v1/entities/relationships/query` | Query graph relationships for an entity (H2H, H2A, A2H, A2A layers) |

**Permissions:** `read`

---

### Entities CRUD Service (v8.8.0)

Core entity management — create, resolve, and manage entity records and cluster membership.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/entities` | Create a new entity record |
| GET | `/v1/entities` | List entities with optional filters |
| GET | `/v1/entities/{id}` | Get entity details |
| PATCH | `/v1/entities/{id}` | Update entity fields |
| POST | `/v1/entities/{id}/identifiers` | Add identifiers (email, phone, wallet, device) to an entity |
| DELETE | `/v1/entities/{id}/identifiers/{cluster_id}` | Remove an identifier from an entity |
| GET | `/v1/entities/{id}/identifiers` | List all identifiers linked to an entity |
| POST | `/v1/entities/{id}/membership` | Add an entity to a population group |

**Permissions:** `write` for mutations, `read` for queries

---

### Operational Intelligence / Graph Service (v8.8.0)

Graph traversal, overlay, and analytics over the unified Neptune-backed intelligence graph.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/graph/traverse` | BFS traversal from a root vertex with depth and edge-type filters |
| POST | `/v1/graph/path` | Shortest-path query between two vertices |
| POST | `/v1/graph/temporal` | Temporal BFS — traverse graph edges within a time window |
| POST | `/v1/graph/overlay` | Fetch all vertices filtered by type, tenant, and optional property predicates |
| POST | `/v1/graph/filter` | Filter vertices by risk level, relationship type, or custom property |
| GET | `/v1/graph/contracts` | List active smart-contract vertices in the graph |

**Permissions:** `read`. Neptune-backed in staging/production; in-memory backend in local mode.

---

### Delegation Service (v8.8.0)

Human → Agent delegation records — tracks what each agent is authorized to do and on whose behalf.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/delegations` | Record a new delegation grant (grantor, grantee, scope, optional time bounds) |
| GET | `/v1/delegations` | List delegation records; filter by `grantor`, `grantee`, `active` |
| GET | `/v1/delegations/{id}` | Get delegation details |
| POST | `/v1/delegations/{id}/revoke` | Revoke a delegation (publishes `aether.delegation.revoked`) |
| POST | `/v1/delegations/validate` | Validate whether a delegation is currently active and in-scope |

**Permissions:** `write` for grants/revoke/validate, `read` for queries

---

### Flows Service (v8.8.0)

Value-flow primitives — asset transfers between entities, wallet links, and asset registry. Writes graph edges (`TRANSFERRED`, `OWNS`) and publishes flow events.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/flows/transfers` | Record an asset transfer between two entities (projects `TRANSFERRED` edge to graph) |
| GET | `/v1/flows/transfers` | List transfers for an entity (`entity_id` query param required) |
| POST | `/v1/flows/wallets` | Link a wallet address to an owner entity (projects `OWNS` edge to graph) |
| GET | `/v1/flows/wallets` | List wallets linked to an entity (`entity_id` query param required) |
| POST | `/v1/flows/assets` | Register a new trackable asset |
| GET | `/v1/flows/assets/{asset_id}` | Get asset details |

**Permissions:** `write` for record/link/register, `read` for list/get

---

### Behavior Service (v8.8.0)

Read-side behavioral profile output computed by the `BehaviorScorer` Profile 360 worker. Snapshots are written by the worker; this service exposes them for query.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/behavior/{entity_id}` | Latest behavior snapshot for an entity (session patterns, anomaly flags, risk signals) |
| GET | `/v1/behavior/{entity_id}/history` | Historical behavior snapshots; `window` (e.g. `7d`) and `limit` query params |

**Permissions:** `read`

---

## Relationship Intelligence Service (v8.12.0)

Read-only relationship-fidelity surface over the Social360 / relationship spine,
mounted at `/v1/relationships/{source_entity_id}/{target_entity_id}/*`. Every
route is flag-gated (`AETHER_SOCIAL360_ENABLED`, default OFF) and, when the flag
is ON, consent-gated for the read subject (the source entity). In the OFF state
each route returns the same content-free `feature_disabled` degraded envelope the
Social360 projection adapter uses; a consent-denied read returns a content-free
`403`. Absent data is never a zero vector — every envelope keeps unavailable
dimensions `null` and reports `available` / `degraded` state. Tenant scope comes
from the authenticated API key; the routes require the `read` permission and
never fabricate a fidelity or influence figure.

| Method | Path | Permission | Notes |
|---|---|---|---|
| `GET` | `/v1/relationships/{source}/{target}/fidelity` | read | Latest persisted fidelity-vector surface for the directed pair. Degrades `no_persisted_fidelity_run` when no run exists (fidelity unknown, never 0). |
| `GET` | `/v1/relationships/{source}/{target}/explain` | read | Honest explain basis: registered predicate semantics + latest fidelity + degraded sections. |
| `GET` | `/v1/relationships/{source}/{target}/influence` | read | Nine-way influence-propagation decomposition (optional `as_of`). Skeleton read: without caller-supplied path edges it honestly reports `insufficient_data` — never a synthesized influence figure. |

Relationship refs and fidelity runs persist on the Computation Substrate (one run
slot per relationship); see `docs/source-of-truth/COMPUTATION_SUBSTRATE.md`.

---

## Error Responses

All endpoints return standard error format:

```json
{
  "error": {
    "code": "INVALID_API_KEY",
    "message": "The provided API key is invalid or expired",
    "status": 401
  }
}
```

Common error codes:
- `400` — `INVALID_REQUEST` — Malformed request body
- `400` — `FEATURE_DISABLED` — Intelligence Graph feature flag not enabled
- `401` — `INVALID_API_KEY` — Missing or invalid API key
- `403` — `FORBIDDEN` — API key lacks required permissions
- `404` — `NOT_FOUND` — Resource not found
- `429` — `RATE_LIMITED` — Too many requests
- `403` — `EXTRACTION_BLOCKED` — Extraction defense triggered (canary or risk score)
- `500` — `INTERNAL_ERROR` — Server error
- `503` — `CIRCUIT_OPEN` — Circuit breaker is open for the requested operation

---

## Model Extraction Defense (v8.3.1)

The extraction defense layer protects ML inference endpoints against model extraction and knowledge distillation attacks. Enabled via `ENABLE_EXTRACTION_DEFENSE=true`.

### Middleware Behavior

When enabled, all `/v1/predict/*` (ML serving API) and `/v1/ml/predict` (backend gateway) requests pass through the defense middleware:

1. **Rate limiting** — dual-axis sliding window (per-API-key + per-IP) with minute/hour/day windows. Exceeding limits returns `429`.
2. **Canary detection** — secret-seed trap inputs detect systematic input-space exploration. Triggers cooldown (`403`).
3. **Pattern analysis** — detects feature sweeps, similarity clustering, uniform probing, bot-like timing.
4. **Risk scoring** — EMA-smoothed score in `[0, 1]` drives response degradation across four tiers.

### Response Perturbation

Responses are modified based on the client's risk tier:

| Tier | Risk Score | Noise Multiplier | Effect |
|------|-----------|-------------------|--------|
| Normal | 0.0 – 0.3 | 1x | Minimal noise, near-original outputs |
| Elevated | 0.3 – 0.6 | 3x | Moderate noise added to probabilities |
| High | 0.6 – 0.8 | 8x | Aggressive noise, top-k clipping |
| Critical | 0.8 – 1.0 | 15x | Maximum degradation, may block |

### Defense Monitoring Endpoints (ML Serving API)

#### `GET /v1/defense/status`

Returns defense layer configuration and state.

```json
{
  "enabled": true,
  "output_noise": true,
  "watermark": true,
  "query_analysis": true,
  "canary_count": 50,
  "tracked_clients": 12
}
```

#### `GET /v1/defense/metrics`

Returns operational metrics snapshot including request counts, block reasons, risk tier distribution, and recent canary triggers.

#### `GET /v1/defense/risk-scores`

Returns current EMA risk scores for all tracked API keys.

#### `GET /v1/defense/canary-triggers`

Returns the last 50 canary detection events with API key (masked), IP, canary ID, and timestamp.

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_EXTRACTION_DEFENSE` | `false` | Master switch |
| `ENABLE_OUTPUT_NOISE` | `true` | Enable output perturbation |
| `ENABLE_WATERMARK` | `true` | Enable probabilistic watermarking |
| `ENABLE_QUERY_ANALYSIS` | `true` | Enable pattern detection and risk scoring |
| `WATERMARK_SECRET_KEY` | (default) | Secret for watermark generation (change in production) |
| `CANARY_SECRET_SEED` | (default) | Seed for canary input generation (change in production) |

## Notification Intelligence Service (v8.8.0)

Event-driven multi-channel operator notification pipeline. Ingests intelligence signals from Kafka (anomaly detection, CIS quarantine, agent escalation, ML extraction, governance, commerce approvals), routes them to Slack/Discord/Telegram/Webhook + mobile push (APNs/FCM), and surfaces an operator review queue with RBAC-gated approve/suppress/escalate/annotate actions. Mobile push delivery carries only a redacted projection (decision-log D11) built at notification creation: `push_title`/`push_body`/`push_summary` with amounts and PII replaced by `[redacted]`, plus a routing-only `push_deep_link_class` — raw payload never ships on a push.

### Intelligence Notifications

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/notifications/intelligence` | Emit a new intelligence notification |
| GET | `/v1/notifications/intelligence` | List notifications (filter: `state`, `severity`, `source_topic`) |
| GET | `/v1/notifications/intelligence/{id}` | Get single notification with audit trail |
| GET | `/v1/notifications/intelligence/{id}/audit` | Full append-only audit log |
| PATCH | `/v1/notifications/intelligence/{id}/approve` | Operator approve (propagates to graph) |
| PATCH | `/v1/notifications/intelligence/{id}/suppress` | Operator suppress |
| PATCH | `/v1/notifications/intelligence/{id}/escalate` | Operator escalate |
| PATCH | `/v1/notifications/intelligence/{id}/annotate` | Add annotation |
| POST | `/v1/notifications/intelligence/{id}/replay` | Re-deliver to all active channels |
| GET | `/v1/notifications/coverage` | Producer-coverage report (honest states; never "healthy" without a declared baseline) |

### Tenant Configuration

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/notifications/config` | Get tenant notification config |
| PUT | `/v1/notifications/config` | Update config (Slack token stored via vault) |

Config carries delivery preferences alongside channel wiring: `quiet_hours` (`{start, end, timezone}`), `timezone` (delivery timezone), and `digest` (`{enabled, frequency, send_time}`) are optional and updated via the same `PUT /v1/notifications/config` surface.

### Inbox & Notification Center

Tenant-scoped notification inbox for the operator console. Reads and archives are idempotent; archived notifications drop out of the unread count.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/notifications/inbox` | List inbox notifications (filters: `unread`, `include_archived`, `limit`, `offset`) |
| GET | `/v1/notifications/inbox/unread-count` | Unread count for the tenant (`{unread: n}`) |
| POST | `/v1/notifications/inbox/read-all` | Mark all notifications read (`{read: n}`) |
| POST | `/v1/notifications/inbox/{notification_id}/read` | Mark a single notification read |
| POST | `/v1/notifications/inbox/{notification_id}/archive` | Archive a notification |

`GET /v1/notifications/inbox` excludes archived rows by default; pass `include_archived=true` to include them.

---

## Kyber ML Admin (v8.9.0)

Operator command center for ML model registry, artifact management, feature contracts, drift monitoring, and readiness gating. All endpoints require `admin` permission.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/admin/kyber/ml/overview` | ML subsystem health summary — registry status, drift alerts, prediction volume, security posture |
| GET | `/v1/admin/kyber/ml/models` | List all registered ML models with version, status, and metadata |
| GET | `/v1/admin/kyber/ml/models/{model_id}` | Full model record — feature contracts, artifact lineage, serving config |
| GET | `/v1/admin/kyber/ml/artifacts` | List all training artifacts across all models |
| GET | `/v1/admin/kyber/ml/artifacts/{model_id}` | Artifacts for a specific model |
| GET | `/v1/admin/kyber/ml/features` | Feature contract registry — schema, validation rules, drift thresholds |
| GET | `/v1/admin/kyber/ml/drift` | Drift report — PSI scores, feature-level alerts, trend window |
| GET | `/v1/admin/kyber/ml/predictions/summary` | Prediction volume, latency, error rate, top model usage |
| GET | `/v1/admin/kyber/ml/security` | ML extraction defense status — watermark state, canary alerts, adversarial risk |
| GET | `/v1/admin/kyber/ml/readiness` | Production readiness gate — registry coverage, drift gates, security gates |
| GET | `/v1/admin/kyber/ml/alerts` | Active ML alert conditions derived from live monitoring state (block rate, freshness, model load) |
| GET | `/v1/admin/kyber/ml/audit` | Promotion and rollback audit trail; reads `promotion_audit.jsonl`, falls back to artifact metadata |
| GET | `/v1/admin/kyber/ml/models/{model_id}/rollback-eligibility` | Check whether a model can be rolled back and to which prior artifact version |
| GET | `/v1/admin/kyber/ml/models/{model_id}/training-history` | Training run history derived from artifact metadata |

---

## Dune Feeder Admin — Scheduled Polling (v8.9.0)

Manage automated Dune query polling schedules per tenant. All endpoints require `admin` permission.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/admin/dune-feeder/schedule` | Create a new scheduled Dune query polling config |
| GET | `/v1/admin/dune-feeder/schedule` | List all schedules for the tenant |
| GET | `/v1/admin/dune-feeder/schedule/{schedule_id}` | Get a single schedule config |
| DELETE | `/v1/admin/dune-feeder/schedule/{schedule_id}` | Delete a schedule |
| POST | `/v1/admin/dune-feeder/schedule/{schedule_id}/run` | Trigger an immediate manual run of a schedule |

**Required fields for create:** `query_id`, `query_name`, `source_tag`, `domain`, `cron_expression`

**Domains:** `onchain`, `governance`, `market`, `social`, `identity`, `tradfi`

**Required env var:**

| Env var | Description | Values |
|---------|-------------|--------|
| `DUNE_BACKEND` | Activates the Dune polling scheduler. When unset or empty the worker runs in no-op mode (logs intent, no external API calls). Set in staging/prod. | `s3` \| `postgres` \| `clickhouse` |
| `DUNE_API_KEY` | Dune Analytics API key. Required for live pulls. | string |

---

## Suggestion Intelligence (v8.10.0)

Proactive AI-driven suggestions for operators and tenants — surfaces actionable insights from graph health, data quality, governance, profile 360, SDK health/drift, and notification patterns. Suggestions have a full lifecycle (created → approved/rejected/executed → outcome), RBAC-gated approve/suppress/execute actions, and a Kyber cross-tenant operator view.

### Tenant Suggestion Routes (`/v1/suggestions`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/suggestions` | List suggestions for the authenticated tenant (filter: `status`, `category`, `severity`) |
| POST | `/v1/suggestions` | Create a suggestion (operator-only) |
| POST | `/v1/suggestions/query` | Advanced query with dimension and category filters |
| GET | `/v1/suggestions/summary` | Summary counts by status, category, and severity |
| GET | `/v1/suggestions/review-queue` | Suggestions awaiting operator review (`pending` status, sorted by priority) |
| GET | `/v1/suggestions/{suggestion_id}` | Get a single suggestion with full context |
| GET | `/v1/suggestions/{suggestion_id}/audit` | Append-only audit log for a suggestion |
| POST | `/v1/suggestions/{suggestion_id}/approve` | Approve a suggestion (requires `suggestions:approve`) |
| POST | `/v1/suggestions/{suggestion_id}/reject` | Reject with reason |
| POST | `/v1/suggestions/{suggestion_id}/suppress` | Suppress (mute) a suggestion type for this tenant |
| POST | `/v1/suggestions/{suggestion_id}/execute` | Execute the suggested action directly |
| POST | `/v1/suggestions/{suggestion_id}/deliver` | Deliver via notification channel |
| POST | `/v1/suggestions/{suggestion_id}/outcome` | Record observed outcome after execution |

### Kyber Admin Routes (`/v1/admin/kyber/suggestions`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/admin/kyber/suggestions` | Cross-tenant suggestion list (filter: `tenant_id`, `status`, `category`) |
| GET | `/v1/admin/kyber/suggestions/summary` | Platform-wide suggestion summary with top-active tenants |
| GET | `/v1/admin/kyber/suggestions/review-queue` | Global review queue across all tenants |
| GET | `/v1/admin/kyber/suggestions/quality` | Suggestion quality report — acceptance rates, suppression rates, outcome tracking |
| GET | `/v1/admin/kyber/suggestions/outcomes` | Outcome ledger — suggestions with confirmed outcomes |

### Tenant Feed Routes (`/v1/aether/suggestions`)

Redacted tenant-safe feed — no internal scoring or suppression metadata exposed.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v1/aether/suggestions` | List suggestions visible to the tenant (redacted) |
| GET | `/v1/aether/suggestions/{suggestion_id}` | Get a single suggestion (redacted) |
| POST | `/v1/aether/suggestions/{suggestion_id}/feedback` | Submit tenant feedback on a suggestion |

### Required Permissions

- `suggestions:read` — list and view suggestions
- `suggestions:approve` — approve, reject, suppress, execute
- `suggestions:write` — create suggestions (operator-only)

---

### Channel Management (End-User Self-Service)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/notifications/channels` | List connected channels |
| POST | `/v1/notifications/channels` | Register Discord/Telegram/Webhook channel |
| PATCH | `/v1/notifications/channels/{id}` | Update severity filter or name |
| DELETE | `/v1/notifications/channels/{id}` | Remove channel |
| POST | `/v1/notifications/channels/{id}/test` | Send test message; sets `verified_at` on success |
| GET | `/v1/notifications/channels/slack/connect` | Initiate Slack OAuth (returns redirect URL) |
| GET | `/v1/notifications/channels/slack/callback` | Slack OAuth callback |

### Webhook Endpoint Configuration

Tenant-managed outbound webhook delivery endpoints. Aether signs each delivery with an HMAC-SHA256 signature in the `X-Aether-Signature` header.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/notifications/webhooks` | List all registered webhook endpoints for the tenant |
| POST | `/v1/notifications/webhooks` | Register a new endpoint (`url`, `events`, optional `secret`) |
| DELETE | `/v1/notifications/webhooks/{webhook_id}` | Remove a webhook endpoint |
| POST | `/v1/notifications/webhooks/{webhook_id}/test` | Ping the endpoint to verify reachability; returns `success`, `status_code`, and `latency_ms` |

### Interactive Callbacks

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/notifications/slack/callback` | Slack Block Kit action handler (HMAC-verified) |
| POST | `/v1/notifications/telegram/callback` | Telegram inline keyboard handler |

### Required Permissions

- `notifications:approve` — operator approve/suppress/escalate
- `notifications:manage` — config management
- `notifications:channels:write` — channel registration/removal

---

## Agentic Observability Layer

> **Invariant: AETHER observes. AETHER does not execute.**
>
> All routes in this section receive inbound observation payloads and record them for
> graph-tracking and intelligence. They never originate, sign, execute, settle, or
> facilitate payments, trades, emails, or other actions. Any payload where
> `execution_by_aether = true` is rejected with **HTTP 422**.
>
> All observation responses return:
> ```json
> { "observation_id": "<uuid>", "received_at": "<ISO8601>", "graph_mutations_queued": <persisted_count>, "tenant_id": "<str>", "graph_mutations_built": <built_count>, "graph_mutations_persisted": <persisted_count>, "graph_projection_status": "persisted|partial|failed|not_applicable" }
> ```

### Feature flags and tenant boundary

Agentic observability routers are mounted only when `AGENTIC_OBSERVABILITY_ENABLED=true` (default true for local compatibility). Subsystems are separately controlled by `AGENTIC_MCP_OBSERVABILITY_ENABLED`, `AGENTIC_EXTERNAL_ACCOUNTS_ENABLED`, `AGENTIC_PROVIDER_VERIFICATION_ENABLED`, `AGENTIC_COMMUNICATION_OBSERVABILITY_ENABLED`, `AGENTIC_PROTOCOL_OBSERVABILITY_ENABLED`, and `KYBER_AGENTIC_OBSERVABILITY_ENABLED`. Authenticated tenant context is authoritative: request-body `tenant_id`/`tenantId` may not override it, and mismatches return HTTP 403.

Graph projection is currently best-effort until the durable outbox ships. Responses distinguish mutations built from mutations actually persisted; `graph_mutations_queued` is retained for compatibility and equals the persisted count, not a fake queued count.

### Agentic Account / MCP / Tool Observability

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/observability/agent/events` | Observe a generic agent activity event (MCP tool call, activity record, risk signal) |
| POST | `/v1/observability/agent/accounts` | Observe an external agentic account linkage |
| POST | `/v1/observability/agent/tools` | Observe an agent tool invocation |
| POST | `/v1/observability/agent/mcp` | Observe an MCP server connection |
| POST | `/v1/observability/agent/risk-signals` | Record an agent risk signal |

**Request fields (agent events):** `tenant_id`, `event_name`, `source.provider`, `actor.actor_type`, `object.object_type`, `action.name`, `action.status`, `provenance.raw_event_hash`, `provenance.normalized_by`, `provenance.schema_version`. Optional: `agent`, `economics` (`is_execution_by_aether` always false).

**Event names (agentic family):** `agentic_account_observed`, `agentic_account_connected_observed`, `agentic_account_disconnected_observed`, `agent_budget_observed`, `agent_budget_changed_observed`, `agent_permission_observed`, `agent_mcp_connection_observed`, `agent_tool_observed`, `agent_tool_invocation_observed`, `agent_activity_observed`, `agent_risk_signal_observed`, `agent_notification_observed`

### x402 Protocol Observability

All x402 endpoints observe external x402 protocol interactions. AETHER never signs, submits, or settles x402 payments.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/observability/x402/interactions` | Observe an x402 interaction (resource request → challenge lifecycle) |
| POST | `/v1/observability/x402/challenges` | Observe an x402 HTTP 402 challenge received by an external agent |
| POST | `/v1/observability/x402/requirements` | Observe an x402 payment requirement record |
| POST | `/v1/observability/x402/signatures` | Observe an externally-signed x402 payment (`signed_by_external=true`, `execution_by_aether=false`) |
| POST | `/v1/observability/x402/verifications` | Observe an x402 payment verification result |
| POST | `/v1/observability/x402/settlements` | Observe an externally-executed x402 settlement (`settlement_by_external=true`, `execution_by_aether=false`) |
| POST | `/v1/observability/x402/resource-access` | Observe an x402 resource access outcome (granted/denied) |

**Event names (x402 observability family):** `x402_resource_request_observed`, `x402_challenge_observed`, `x402_payment_requirement_observed`, `x402_signature_observed`, `x402_verification_observed`, `x402_settlement_observed`, `x402_resource_access_observed`, `x402_resource_access_denied_observed`, `x402_failure_observed`, `x402_replay_risk_observed`, `x402_provider_observed`

### Agent Communication Observability

Observe agent inboxes, messages, attachments, and extracted entities. AETHER never sends or replies to messages.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/observability/agent-comm/inboxes` | Observe an agent inbox from an external communication provider |
| POST | `/v1/observability/agent-comm/messages` | Observe an inbound or outbound agent message |
| POST | `/v1/observability/agent-comm/attachments` | Observe a message attachment |
| POST | `/v1/observability/agent-comm/extractions` | Observe an extracted entity (OTP, invoice, receipt, calendar intent, support case) |

**Entity types for extractions:** `otp`, `invoice`, `receipt`, `calendar_intent`, `support_case`, `payment_reference`, `amount`, `other`

**Event names (agent-comm family):** `agent_inbox_observed`, `agent_email_address_observed`, `agent_thread_observed`, `agent_message_received_observed`, `agent_message_sent_observed`, `agent_reply_observed`, `agent_attachment_observed`, `agent_attachment_parsed_observed`, `agent_otp_detected_observed`, `agent_invoice_detected_observed`, `agent_receipt_detected_observed`, `agent_calendar_intent_observed`, `agent_support_route_observed`, `agent_semantic_search_observed`, `agent_data_extraction_observed`

### External Account Observability (Robinhood-style)

Observe external brokerage accounts, trade intents, order fills, portfolio snapshots, and budgets. AETHER never places, modifies, or cancels orders.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/observability/external-accounts` | Observe an external agentic account linkage |
| POST | `/v1/observability/external-accounts/brokerage` | Observe an external brokerage account |
| POST | `/v1/observability/external-accounts/portfolio-snapshots` | Observe a portfolio snapshot |
| POST | `/v1/observability/external-accounts/order-observations` | Observe a trade order (executed externally, `execution_by_aether=false`) |
| POST | `/v1/observability/external-accounts/budget-observations` | Observe an agent budget state |

**Event names (Robinhood-style family):** `agent_strategy_observed`, `agent_trade_intent_observed`, `agent_trade_order_observed`, `agent_trade_fill_observed`, `agent_trade_rejection_observed`, `agent_position_observed`, `agent_portfolio_snapshot_observed`, `agent_performance_snapshot_observed`, `agent_disconnect_observed`

### Kyber Admin — Agentic Observability

Operator-only read routes. Require `admin` permission.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/admin/kyber/agentic-observability/overview` | Agentic observability overview across all tenants |
| GET | `/v1/admin/kyber/agentic-observability/agents/{agent_id}` | Single agent observability view |
| GET | `/v1/admin/kyber/agentic-observability/risk` | Risk signals overview |
| GET | `/v1/admin/kyber/agentic-observability/x402` | x402 protocol observability overview |
| GET | `/v1/admin/kyber/agentic-observability/replay` | x402 replay risk signals |
| GET | `/v1/admin/kyber/agentic-observability/inboxes` | Agent inbox observability overview |
| GET | `/v1/admin/kyber/agentic-observability/external-accounts` | External account observability overview |

### No-Execution Invariant

Every observability route enforces `execution_by_aether = false`. Violations return HTTP 422:
```json
{ "detail": "execution_by_aether must be false. AETHER does not execute." }
```

Fields enforced at both the Pydantic model layer (`Literal[False]`) and the route layer (`_check_no_execution()`).

---

## Provider Corpus + Data Lake Routes

### Tenant — Data Rights (`/v1/integrations/data-rights/*`)

Feature-flagged (`AETHER_CONNECTOR_DATA_RIGHTS_ENABLED`). Tenant API key required.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/integrations/data-rights` | List data rights grants for caller's tenant |
| POST | `/v1/integrations/data-rights/grants` | Create a new data rights grant |
| GET | `/v1/integrations/data-rights/grants/{grant_id}` | Get one grant |
| POST | `/v1/integrations/data-rights/grants/{grant_id}/revoke` | Revoke a grant (immediate denial) |
| POST | `/v1/integrations/data-rights/policy-check` | Run a named policy check against a grant |

All policy checks are fail-closed: absent an explicit grant, all use (Olympus baseline, model training, cross-tenant aggregate) is denied.

### Tenant — BYOK Key Rotate / Revoke / Verify (`/v1/providers/keys/*`)

Feature-flagged (`AETHER_CONNECTOR_BYOK_ENABLED`). Tenant API key required.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/providers/keys/{provider}/rotate` | Re-encrypt credential with a new API key |
| POST | `/v1/providers/keys/{provider}/revoke` | Disable credential (retains audit record) |
| POST | `/v1/providers/keys/{provider}/verify` | Return safe key metadata without exposing the raw key |

Responses include `masked_identifier` only (`****{hash_suffix}`). Raw keys are never returned. BYOK credential does not confer lake ingestion rights, Olympus baseline use, model training, or aggregate use — those require a separate `DataRightsGrant`.

### Kyber Admin — Provider Source Catalog (`/v1/admin/kyber/providers/*`)

Feature-flagged (`KYBER_PROVIDER_SOURCE_CATALOG_ENABLED`). Operator permission required.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/admin/kyber/providers/catalog` | All 30+ Olympus provider entries |
| GET | `/v1/admin/kyber/providers/overview` | Summary stats by phase and implementation status |
| GET | `/v1/admin/kyber/providers/{provider_id}` | Single provider detail |
| GET | `/v1/admin/kyber/providers/{provider_id}/cost` | Cost profile |
| GET | `/v1/admin/kyber/providers/{provider_id}/rate-limits` | Rate limit profile |
| GET | `/v1/admin/kyber/providers/{provider_id}/provenance` | Provenance status |
| GET | `/v1/admin/kyber/providers/{provider_id}/lake-manifest` | Source manifest |
| POST | `/v1/admin/kyber/providers/{provider_id}/sync` | Trigger sync (credential-gated) |
| POST | `/v1/admin/kyber/providers/{provider_id}/validate-policy` | Validate against policy gates |

### Kyber Admin — Dune Data Lake (`/v1/admin/kyber/dune/*`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/admin/kyber/dune/access-modes` | Three Dune access modes (API, Datashare, Sim) with implementation status |
| GET | `/v1/admin/kyber/dune/chains` | P0/P1/P2 chain extraction plans |
| GET | `/v1/admin/kyber/dune/extraction-products` | 10 extraction product specs |

### Kyber Admin — Lake Observability (`/v1/admin/kyber/lake/*`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/admin/kyber/lake/source-manifests` | All source manifests |
| GET | `/v1/admin/kyber/lake/capacity` | Estimated vs actual capacity by lake layer |
| GET | `/v1/admin/kyber/lake/coverage` | Source coverage by layer |
| GET | `/v1/admin/kyber/lake/quarantine` | Quarantined Bronze records summary |

### Kyber Admin — Feature Intelligence (`/v1/admin/kyber/features/*`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/admin/kyber/features/source-model-matrix` | Provider → ML model mapping |
| GET | `/v1/admin/kyber/features/unique-signal-backlog` | 5 unique cross-source signal feature status |

### Kyber Admin — Anti-Distillation (`/v1/admin/kyber/intelligence/*`)

Feature-flagged (`KYBER_ANTI_DISTILLATION_ENABLED`). Operator permission required.

Anti-distillation enforcement on intelligence query endpoints is activated by `AETHER_ANTI_DISTILLATION_ENABLED=true`. When enabled, wallet risk and profile endpoints run pattern detection (rapid diverse-query, honeypot wallet, sequential enumeration) on every request and emit audit events on suspicious activity. Honeypot wallet queries return `403 Forbidden`. Score precision is binned by plan tier (`P1_HOBBYIST=0.1`, `P2_PROFESSIONAL=0.05`, `P3_GROWTH=0.01`, `P4_PROTOCOL=0.001`).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/admin/kyber/intelligence/anti-distillation` | Suspicious query patterns, alerts, honeypot queries, and score-binning stats |

### Kyber Admin — Data Rights (`/v1/admin/kyber/data-rights/*`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/admin/kyber/data-rights` | All data rights grants (operator-scoped view) |

---

## Fraud Intelligence APIs

These endpoints are gated by feature flags (`FEATURE_FRAUD_NETWORKS`, `FEATURE_FLOW_TRACE`, `FEATURE_RISK_OVERLAYS`). Disabled flags return 404.

### Fraud Networks (`/v1/fraud/networks/*`)

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| POST | `/v1/fraud/networks/build` | `fraud:write` | Build a fraud network from anchor entities |
| GET | `/v1/fraud/networks` | `fraud:read` | List networks for tenant (filter by status) |
| GET | `/v1/fraud/networks/{network_id}` | `fraud:read` | Get network detail |
| GET | `/v1/fraud/networks/{network_id}/graph` | `fraud:read` | Cytoscape-ready graph payload |
| GET | `/v1/fraud/networks/{network_id}/members` | `fraud:read` | Member list with roles and risk scores |
| GET | `/v1/fraud/networks/{network_id}/evidence` | `fraud:read` | Evidence references |
| POST | `/v1/fraud/networks/{network_id}/refresh` | `fraud:write` | Re-run detection pipeline |
| POST | `/v1/fraud/networks/{network_id}/open-investigation` | `fraud:write` | Create investigation case and link network |
| POST | `/v1/fraud/networks/{network_id}/annotate` | `fraud:write` | Add annotation |
| POST | `/v1/fraud/networks/{network_id}/suppress` | `fraud:write` | Suppress network |
| POST | `/v1/fraud/networks/{network_id}/escalate` | `fraud:write` | Escalate network |
| POST | `/v1/fraud/networks/{network_id}/takedown` | `fraud:evaluate` | Close network + invalidate the attribution it produced (re-attribution, retains evidence); returns a `reattribution` summary |

### Flow Trace (`/v1/flow-trace/*`)

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| POST | `/v1/flow-trace/trace` | `fraud:write` | Execute BFS traversal from anchor entity |
| GET | `/v1/flow-trace` | `fraud:read` | List traces for tenant |
| GET | `/v1/flow-trace/{trace_id}` | `fraud:read` | Get trace detail |
| GET | `/v1/flow-trace/{trace_id}/paths` | `fraud:read` | All discovered paths with pattern tags |
| GET | `/v1/flow-trace/{trace_id}/sources` | `fraud:read` | Source nodes |
| GET | `/v1/flow-trace/{trace_id}/sinks` | `fraud:read` | Sink nodes |
| GET | `/v1/flow-trace/{trace_id}/cycles` | `fraud:read` | Detected cycle nodes |

### Risk Overlay (`/v1/risk-overlay/*`)

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| POST | `/v1/risk-overlay/fraud` | `fraud:write` | Build risk overlay from fraud network |
| POST | `/v1/risk-overlay/flow` | `fraud:write` | Build risk overlay from flow trace |
| GET | `/v1/risk-overlay` | `fraud:read` | List overlay snapshots |
| GET | `/v1/risk-overlay/{overlay_id}` | `fraud:read` | Get overlay snapshot |
| POST | `/v1/admin/kyber/data-rights/grants/{grant_id}/revoke` | Operator-initiated revocation |


### Delivery Management (`/v1/delivery/*`)

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| GET | `/v1/delivery/intents` | `delivery:read` | List DeliveryIntent records for tenant |
| GET | `/v1/delivery/jobs` | `delivery:read` | List DeliveryJob records for tenant |
| GET | `/v1/delivery/jobs/{id}/attempts` | `delivery:read` | List DeliveryAttempt records for job |
| GET | `/v1/delivery/jobs/{id}/receipt` | `delivery:read` | Get ProviderReceipt for job |
| POST | `/v1/delivery/jobs/{id}/replay` | `kyber:operator` | Re-queue dead-letter job (Kyber only) |
| GET | `/v1/delivery/links` | `delivery:read` | List ExternalResourceLink records for tenant |

### Inbound Webhooks (`/v1/webhooks/*`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/v1/webhooks/slack/interactive` | Slack signing secret | Slack interactive action callback; written to WebhookInbox before processing |
| POST | `/v1/webhooks/linear/events` | Linear-Signature HMAC | Linear issue/event webhook; persisted to WebhookInbox and processed async |
| POST | `/v1/webhooks/jira/events` | X-Hub-Signature-256 HMAC | Jira issue webhook; persisted to WebhookInbox and processed async |
| POST | `/v1/webhooks/aether/callback` | X-Aether-Signature HMAC | Generic signed outcome callback from webhook delivery targets |

Comms provider webhooks (`/v1/integrations/webhooks/comms/*`, ADR-C11) use
server-controlled durable endpoint ids; tenant ownership is resolved from the
`whe_` registry, never a request header:

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/v1/integrations/webhooks/comms/{connector}/{endpoint_id}` | Provider-native signature (SendGrid ECDSA / Customer.io HMAC / endpoint id possession) | Normalized comms event receiver; unknown/revoked ids and disabled connectors return a uniform closed denial. `endpoint_secret` providers (Mailchimp, Postmark) authenticate by possession of the resolved id; signing providers require their configured key |
| GET | `/v1/integrations/webhooks/comms/{connector}/{endpoint_id}` | endpoint id possession | Setup validation probe for GET-probing providers (Mailchimp); only connectors declaring `supports_get_validation` answer, others keep the uniform 404 |

## Semantic-Sentiment Intelligence APIs

The semantic-sentiment intelligence plane adds tenant-scoped APIs under `/v1/semantic` for observation creation, observation reads, entity state, entity sentiment, timelines, narrative listing, cascade status, and bounded reprocessing. Kyber operator APIs under `/v1/kyber/semantic` expose fleet health and review queues and require explicit operator scope.

The APIs return real classified observations from the semantic-sentiment repository, include evidence/model/taxonomy metadata, enforce canonical `camp_*` campaign IDs, and preserve insufficient-data states instead of returning fake zero insights.

Additional semantic-sentiment routes in this iteration include `GET /v1/campaigns/{campaign_id}/semantic-impact`, `GET /v1/campaigns/{campaign_id}/sentiment`, `POST /v1/graph/semantic-overlay`, and `POST /v1/population/semantic-compare`. These routes are tenant-scoped and return bounded overlays or insufficient-data states instead of merging semantic-mediated estimates into ordinary attribution. `POST /v1/graph/semantic-overlay` returns real `edge_overlays` read from durable Gold (`gold_relationship_semantic_state`): each overlay edge is a directed relationship projection (`source_ref` → `target_ref`) carrying relationship, stance, trust, and confidence metadata, restricted to edges touching the requested subject when a `subject_ref`/`subject` filter is given.

Graph reachability is governed, never implied by the routes: the semantic graph projector (`services/semantic_intelligence/graph_projector.py`, WorkerSpec `semantic_graph_projector` under the `semantic-worker` role) is flag-gated (`SEMANTIC_GRAPH_PROJECTOR_ENABLED`, default OFF) and, per tenant, projects each Gold relationship row as a directed `SEMANTIC_RELATES_TO` edge **through the canonical `GraphMutationGateway`** — never a direct graph write — so the mutation is ledger-recorded in shadow/enforce mode. The pass is idempotent (an edge already present for `(tenant, source, target)` is skipped) and tenant-scoped. `SEMANTIC_RELATES_TO` maps to `RelationshipLayer.EXCLUDED` (a derived analytics overlay, not a human/agent interaction, so enforce-mode validation needs no consent purpose). The overlay route itself never mutates edges.

## Communications Intelligence APIs

The Communications Intelligence plane ingests provider communications through the
generic connector framework and the canonical comms spine. The certified cohort
(ADR-C11) is **Klaviyo, SendGrid, Customer.io, Mailchimp, Postmark, HubSpot,
Iterable, and Braze**; every comms connector is a `BaseConnector` subclass with
`comms.*` data outputs, and catalog manifests are derived from the connector
declarations. All routes are tenant-scoped; operator routes require an explicit
Kyber operator scope and are audited.

Connector setup + synchronization (`/v1/integrations/connectors/*`):

- `PUT /v1/integrations/connectors/{type}` — configure/enable a connector.
  Enabling a communications connector is plan-gated (§20): an over-limit request
  returns `403` with an explicit `upgrade_required` / `quota_reached` reason.
- `POST /v1/integrations/connectors/{type}/sync?since=<ISO8601>` — start a sync;
  `since` selects a historical backfill window, omitted for incremental.
- `GET /v1/integrations/connectors/{type}/sync-runs` — durable sync-run history
  (the customer-visible progress surface; §12.4 fields including cursor movement,
  record counts, and a safe error classification on failure).

Comms webhook endpoint management (tenant-admin; ADR-C11):

- `POST /v1/integrations/connectors/{type}/webhook-endpoints` — mint a durable,
  high-entropy `whe_` endpoint id for a comms connector. The id resolves
  server-side to exactly one (tenant, connector, environment); it is never read
  from an `X-Aether-Tenant-ID` header.
- `GET /v1/integrations/connectors/{type}/webhook-endpoints` — list the tenant's
  comms webhook endpoints.
- `POST /v1/integrations/connectors/{type}/webhook-endpoints/rotate` — rotate
  (revoke + re-mint) an endpoint id.
- `POST /v1/integrations/connectors/{type}/webhook-endpoints/{endpoint_id}/revoke`
  — revoke an endpoint id; revoked ids resolve to a uniform 404.
- Public delivery targets
  `POST /v1/integrations/webhooks/comms/{connector}/{endpoint_id}` (signature
  verification still applies — the endpoint id is routing, not authentication);
  GET-probing providers (e.g. Mailchimp) validate via
  `GET /v1/integrations/webhooks/comms/{connector}/{endpoint_id}`. Comms
  connectors are permanently denied on the legacy header-tenant route (ADR-C11).

Communications tenant surface (`/v1/comms/*`):

- `GET /v1/comms/entitlement` — the tenant's comms plan entitlement, current
  connection usage, and quota state (`allowed` / `quota_approaching` /
  `quota_reached` / `upgrade_required`).
- `GET /v1/comms/suppressions` — the canonical suppression ledger, exposing
  provider-reported vs Aether-enforced state per row (write-back is a separately
  authorized capability, off by default).
- `GET /v1/comms/identities/provisional` — provider identities awaiting mapping
  review; `POST /v1/comms/identities/{id}/resolve` maps one to a canonical entity.
- `GET /v1/comms/health` — comms pipeline health plus turnkey activation signals
  (provisional identities, active suppressions, latest sync-run).
- `GET /v1/comms/coverage` — per-provider observation coverage for the tenant:
  identity-bridge mappings (observed/resolved/provisional + resolution rate) and
  active suppressions per registered comms connector, next to each provider's
  declared capabilities. Evidence-grounded — providers nobody has wired yet
  report zero observations, never fabricated completeness.

Communications operator surface (`/v1/comms/admin/*`, Kyber operator scope):

- `GET /v1/comms/admin/sync-runs?tenant_id=…` — sync-run history for a tenant.
- `POST /v1/comms/admin/suppressions/reconcile` — observe-only reconciliation of
  provider-reported suppressions against Aether's canonical set (reports drift;
  never writes back unless write-back is separately authorized).
- `GET /v1/comms/admin/coverage?tenant_id=…` — per-provider coverage for one
  tenant, or a fleet aggregate across all observed tenants when unscoped.
- Existing audited remediation: `POST /v1/comms/admin/state/rebuild`,
  `/graph/reproject`, `/dsr/erase`. The durable `/dsr/erase` remediation
  propagates across every subject-data plane — measurement/attribution, mobile
  (continuations, installations, client-sync), and the semantic-intelligence
  plane (observations, sentiment, Gold aggregate state, review queue) — marking
  each `dsr_propagation` component with its own erased-row receipt.

Provider readiness is truthful: without a credential a provider reports
`credential_missing`, is never marked connected, and the certification harness
reports `credential_turnkey / staging_validation_pending` — never `provider_live`
— until real infrastructure and credentials are supplied.

---

## Universal Provider Runtime (UPR) APIs (v8.12.0)

The provider-neutral runtime (ADR-009) exposes generic provider-connection
lifecycle, sync, health, and certification surfaces. A provider is a self-contained
plugin (manifest + capability adapters + normalizer + fixtures) registered at
runtime — no core type-union or registry edits. Legacy `BaseConnector` providers
are exposed through a compatibility plugin (`family.ingestion.connector`) that is
byte-identical to the catalog-derived manifest; the legacy `/v1/integrations/connectors/*`
routes are untouched.

**Feature gating (off by default, additive — zero impact until activated):**
- `AETHER_PROVIDER_RUNTIME_ENABLED=false` gates the tenant + public-webhook routers.
- `KYBER_PROVIDER_RUNTIME_HEALTH_ENABLED=false` additionally gates the admin router.
- `AETHER_PROVIDER_ENTRY_POINTS_ENABLED=false` gates `importlib.metadata` plugin
  discovery (the `aether.providers` entry-point group); local plugins always register.

**Identity:** a plugin is `family.product.capability` (e.g. `shopify.admin.orders_read`).
Legacy connectors register as `{connector_type}.ingestion.connector`.

Tenant connection lifecycle (`/v1/provider-connections/*`, API key + tenant required):

- `GET /v1/provider-connections/providers` — merged manifest catalog (legacy +
  registered plugins) with counts.
- `GET /v1/provider-connections/providers/{identity_key}` — one provider manifest
  (404 if not installed).
- `POST /v1/provider-connections` — create a connection for an installed provider
  (404 for an uninstalled provider).
- `GET /v1/provider-connections/{connection_id}` — connection record. Cross-tenant
  ids resolve to 404 (ownership enforced server-side).
- `PATCH /v1/provider-connections/{connection_id}` — update display name / config;
  config fields are validated against the provider manifest.
- `DELETE /v1/provider-connections/{connection_id}` — disable the connection
  (transition to `disabled`).
- `POST /v1/provider-connections/{connection_id}/credentials` — store a structured
  credential. Only a `credential_ref` is ever returned or stored on the connection;
  secrets are never echoed.
- `POST /v1/provider-connections/{connection_id}/test` — live connectivity test
  through the provider's auth adapter.
- `GET /v1/provider-connections/{connection_id}/accounts` — account discovery.
- `POST /v1/provider-connections/{connection_id}/accounts/select` — select an
  account to scope ingestion.
- `POST /v1/provider-connections/{connection_id}/sync` — trigger a sync run
  (optional `since` for backfill). Provider failure marks the run failed with a
  safe error classification — never a silent empty success.
- `GET /v1/provider-connections/{connection_id}/sync-runs` — durable sync-run
  history.
- `POST /v1/provider-connections/{connection_id}/confirm` — server-side
  confirmation of a web commerce interaction: reconcile an SDK commerce signal
  against the corresponding canonical `commerce.*` event via the
  idempotency-key lineage (`source_record_id`). Replay-safe (a repeated signal
  is `replay`), and never auto-confirms on a mismatch (`unconfirmed` /
  `not_found`).
- `GET /v1/provider-connections/{connection_id}/health` — provider health report
  (state, readiness, last sync/webhook, rate-limit, error signals).
- `GET /v1/provider-connections/{connection_id}/raw-records` — replayed raw
  provider records from the Bronze `provider_records` store (tenant-scoped).

Kyber operator surface (`/v1/admin/kyber/provider-connections/*`, operator scope,
fail-closed):

- `GET /v1/admin/kyber/provider-connections/overview` — per-provider connection
  counts by lifecycle state (aggregate only).
- `GET /v1/admin/kyber/provider-connections/providers` — provider list
  (installed plugins + legacy connectors) at the admin surface, distinct from
  the tenant-scoped `/v1/provider-connections/providers`.
- `GET /v1/admin/kyber/provider-connections/health` — registry summary
  (providers loaded, legacy vs native plugin counts).
- `POST /v1/admin/kyber/provider-connections/certify` — run the certification
  harness against an installed plugin; returns the `CertificationReport` (10
  checks). Never upgrades readiness beyond evidence.
- `GET /v1/admin/kyber/provider-connections/tenants/{tenant_id}` — one tenant's
  connections + health (operator drill-down).
- `POST /v1/admin/kyber/provider-connections/decommission/{connector_type}` —
  operator-gated decommission of a legacy connector type (Shopify only in this
  build, via `DECOMMISSIONABLE_CONNECTOR_TYPES`), gated additionally on
  `AETHER_PROVIDER_LEGACY_DECOMMISSION` (route inert when off — a real gate,
  not a no-op claim). Idempotent: a repeat call is a stable `already_retired`
  no-op that preserves the original retirement timestamp; an unknown type is a
  typed 404; a native-only provider (registered but not decommissionable) is a
  400. The retirement ledger is process-local; persistence across restarts is a
  documented follow-on.

**Provider migrations:** config/secret migration
projections (`shared/integration_contracts/migration.py`) are surfaced on the
**tenant** provider-connections surface (NOT under `/v1/admin/kyber/*`), gated
by `AETHER_PROVIDER_MIGRATIONS_ENABLED`:

- `GET /v1/provider-connections/migrations` — list projectable legacy
  connector families (`MigrationProjection`, `ProjectionCandidate`). Built
  families carry their native identity + confidence;
  `requires_manual_mapping` flags families needing a human decision; families
  the tenant has already migrated are excluded.
- `GET /v1/provider-connections/{connection_id}/migrations` — projection of
  one legacy connection onto a native identity, derived from the loaded
  connection (never from request-supplied secrets).
- `POST /v1/provider-connections/{connection_id}/migrations` — apply a
  projection: build the native connection + credential refs from the legacy
  connection's config/secret. Takes a `connection_id` (not a `connector_type`);
  tenant-host validation fails closed.

Public provider webhooks (`/v1/provider-webhooks/*`):

- `POST /v1/provider-webhooks/{identity_key}` — inbound provider webhook delivery.
  **UNAUTHENTICATED by API key** (listed in `PUBLIC_PATH_PREFIXES`); authorization
  is enforced inside the gateway by cryptographic proof the caller holds the
  connection's webhook secret — a signature scheme (e.g. `shopify_hmac`) requires
  a verifying signature, and `endpoint_secret` requires a caller-presented
  per-connection token that constant-time-matches the stored secret. A delivery
  that cannot be proven is DENIED with an auditable metadata-only denial record
  and a closed 403 — there is no "no secret ⇒ trust" path.

  Headers:
  - `X-Aether-Tenant-ID` — **routing hint only, not an authorization signal**;
    the connection is located by tenant + identity and verified against its own
    secret before anything is persisted.
  - `X-Signature` / `X-Aether-Signature` — provider-native signature (signature schemes).
  - `X-Aether-Webhook-Endpoint-Token` — caller-presented endpoint token
    (`endpoint_secret` schemes).

---

## Continuation Plane & Client-Sync Feed (v8.12.0)

Cross-device context-handoff and catch-up surfaces from the mobile/continuity
productization program. The design stance is deliberate: a **continuation** is a
durable context-handoff token — a bounded `summary`, `canonical_context`, and
`resource_references` describing where a principal left off — never a whole
graph. The **client-sync** feed carries change rows with ids + a revision only;
clients re-fetch full objects through their normal scoped endpoints, so the
graph is never replicated over the feed.

Both surfaces are flag-gated inside every handler — `AETHER_CONTINUATION_ENABLED`
and `AETHER_CLIENT_SYNC_ENABLED` (default OFF). When off they answer 404,
indistinguishable from an unmounted route. Server identity always overrides the
request body: a client cannot forge `principal_id`, `tenant_id`, or `app_kind`.

### Continuation plane — tenant (`/v1/continuations`)

Scope is `t:{tenant_id}`; the principal is the authenticated user (or the tenant
itself for API-key auth). GETs require `read`, writes `write`. Creating,
updating, or deleting a continuation emits a `continuation_changed` sync event.

| Method | Path | Description |
|---|---|---|
| POST | `/v1/continuations` | Create a continuation (optional `idempotency_key` query param). Body: `source_client`, `surface`, `summary`, `canonical_context`, `resource_references`, `sensitivity` (default `standard`), `freshness`, `expires_at`. Returns the row with `state_revision` (0 on create). |
| GET | `/v1/continuations/recent` | Recent continuations for the principal (`limit` 1–100, default 25). Response `{ "continuations": [...] }`. |
| GET | `/v1/continuations/{id}` | One continuation. |
| PATCH | `/v1/continuations/{id}` | Compare-and-swap update. Body is the continuation fields plus the required `expected_state_revision`; a `state_revision` mismatch returns HTTP 409. |
| POST | `/v1/continuations/{id}/handoff` | Mint the backend selection token for a handoff. Body: `mode` (`explicit` \| `query`), `resource_ids`, `saved_view_id`, `query_id`, `as_of`, `expires_at`. The token resolves the same subject set for Noesis exact-handoff and mobile deep-links. |
| DELETE | `/v1/continuations/{id}` | Delete. Response `{ "deleted": true, "id": ... }`. |

### Operator continuation twins (`/v1/kyber/continuations`)

The same durable continuation plane exposed to Kyber operators, scoped to
`o:{operator_id}` and reusing the same `continuations` / `continuation_selections`
tables and the same `client_sync` feed — there is no second continuation store.
The operator identity is always taken from the authenticated Kyber session
(`KyberAccessContext.operator_id`), never from the request body, and every route
is gated by `require_kyber_access(SELF_CAPABILITY)` so only a live, device-bound
workforce session can reach the surface. An operator may only read, update, or
delete their own continuations (the row's `principal_id` must equal the
authenticated `operator_id`; absent and foreign rows both read as 404).

| Method | Path | Description |
|---|---|---|
| GET | `/v1/kyber/continuations/recent` | Recent continuations for the operator (mirror of the tenant shape; `limit` 1–100, default 25). |
| GET | `/v1/kyber/continuations/{id}` | One operator continuation (mirror of the tenant shape). |

The operator router also mirrors the tenant plane's `POST`, `PATCH`
(CAS-guarded via `expected_state_revision`), `POST /{id}/handoff`, and `DELETE`
routes behind the same flag gate and `require_kyber_access(SELF_CAPABILITY)`.

### Client-sync feed — tenant (`/v1/client-sync`)

`AETHER_CLIENT_SYNC_ENABLED` gate; requires `read`. Returns an ordered, gap-free
slice of the durable per-scope change log since `cursor`.

| Method | Path | Description |
|---|---|---|
| GET | `/v1/client-sync` | Query params: `cursor` (opaque; omit to start from the head) and `limit` (1–500, default 200). Response: `{ "events": [SyncEvent...], "cursor", "has_more", "reset" }`. Each `SyncEvent` carries `id`, `scope_key`, `seq`, `change_type`, `resource_kind`, `resource_id`, `revision`, `created_at` — ids + a revision only, never a resource body. |

### Operator client-sync feed (`/v1/kyber/client-sync`)

The operator read-path twin of the tenant feed, reading the SAME
`sync_change_log` / `sync_cursor_counter` — no second feed. Scope is always
`o:{context.operator_id}` from the authenticated session. Gated by
`AETHER_CLIENT_SYNC_ENABLED` and `require_kyber_access(SELF_CAPABILITY)`.

| Method | Path | Description |
|---|---|---|
| GET | `/v1/kyber/client-sync` | Same `cursor` / `limit` contract as the tenant feed, scoped to the authenticated operator. M5 producers emit operator-scoped changes for command receipts, incident updates, Kyber session revocations, and operator continuations. |

### Sync event types

The sync-event type registry (`shared/client_sync/models.py`, drift-guarded by
`tests/contracts/test_sync_event_contract_parity.py`) defines exactly ten
snake_case change types emitted by the feed:

`notification_changed`, `continuation_changed`, `saved_view_changed`,
`conversation_changed`, `watchlist_changed`, `incident_changed`,
`command_receipt_changed`, `preference_changed`, `session_revoked`,
`installation_revoked`.

Producer coverage: notification intelligence (`notification_changed`),
continuation plane (`continuation_changed`), exploration saved views
(`saved_view_changed`), Noesis conversations (`conversation_changed`),
intelligence comparison watchlists (`watchlist_changed`), Kyber ops incidents
and command receipts (`incident_changed`, `command_receipt_changed`), self-service
and Kyber session revocation (`session_revoked`), and mobile installation
revocation (`installation_revoked`).

---

## Mobile Gateway (v8.12.0)

Native installation and push-subscription gateway. Flag-gated inside every
handler via `AETHER_MOBILE_ENABLED` (default OFF → 404). Scope is `t:{tenant_id}`;
`app_kind` is forced to `aether`. Only the hash of a push token is stored — never
the raw token. GETs require `read`, writes `write`. Revoking an installation
emits an `installation_revoked` sync event.

| Method | Path | Description |
|---|---|---|
| POST | `/v1/mobile/installations` | Register an installation. Body: `installation_id` (optional), `platform`, `bundle_id`, `environment`, `device_name`, `push_token`, `push_provider`, `app_version`, `distribution_profile`. Response `{ "installation": {...}, "subscription": {...} }`. |
| GET | `/v1/mobile/installations` | List the caller's installations. Response `{ "installations": [...] }`. |
| GET | `/v1/mobile/installations/{id}` | One installation. |
| DELETE | `/v1/mobile/installations/{id}` | Revoke an installation (emits `installation_revoked`). |
| POST | `/v1/mobile/installations/{id}/subscriptions` | Add a push subscription to an installation. Body: `platform`, `provider`, `push_token`, `environment`. 404 if the installation is absent. |
| POST | `/v1/mobile/deep-links/resolve` | Resolve an opaque deep link (body: `installation_id`, `continuation_id`) to a bounded continuation projection. Fail-closed: every failure that could leak a continuation's existence returns the same `{ "resolved": false, "reason": "unresolvable" }`; a restricted continuation owned by the caller returns `{ "resolved": false, "reason": "step_up_required", "requires_step_up": true }` unless the caller holds `step_up`; success returns `{ "resolved": true, "continuation": {...} }`. |
| GET | `/v1/mobile/config` | Typed `MobileConfig` for an installation (`installation_id` query param required; 404 when the installation is absent). |

`GET /v1/mobile/config` returns `{ "app_kind", "environment", "min_version",
"latest_version", "upgrade_policy", "distribution_profile", "feature_flags",
"service_capabilities", "externally_blocked_providers" }`. `upgrade_policy` is
derived from the installation's `app_version`: `required` below the support
floor, `suggested` between floor and latest, `none` at or above latest (unknown
version fails safe to `required`). `distribution_profile` values are snake_case:
iOS `dev` / `testflight` / `app_store`; Android `dev` / `play_internal` /
`managed`. `service_capabilities` is a read-only projection of existing
`settings.py` flags; `externally_blocked_providers` honestly mirrors the
external-blockers report and never claims a blocked provider is live.

**Bounded redacted projections** (M3a, decision-log D12): `GET /v1/mobile/today`
(alert counts + redacted titles + profile peek), `GET /v1/mobile/profile`
(`user_id` query param), `GET /v1/mobile/campaign` (`campaign_id` query param),
`GET /v1/mobile/alerts` (`unread`, `limit`, `offset`), and `GET /v1/mobile/briefing`
(`views_limit`, `conversations_limit`). Each composes owning-service truth
(profile-360, campaign-360, the single canonical notification inbox, the
saved-views store, Noesis) into a bounded, redacted projection and never
re-calculates it. Wire fields are snake_case. All require `read`.

---

## Kyber Workforce Sessions & Step-Up (v8.12.0)

Session inspection, elevation, and revocation for the Kyber workforce plane
(`/v1/kyber/auth/*`). These routes only inspect and end what the identity-plane
sign-in flow produced, plus raise and verify a step-up elevation — there is no
route that mints, extends, or returns a raw session handle.

### GET /v1/kyber/auth/session

The caller's current session state, plus step-up state and a fresh CSRF token.
Requires a live Kyber presence (`require_kyber_presence`). The CSRF token is
returned in the response body **and** set as an HttpOnly cookie; the application
echoes the body value in `X-Kyber-CSRF`, so a cross-site request cannot produce
a matching pair. Response body includes the session fields (`session_id`,
`operator_id`, `device_id`, `status`, `authentication_strength`,
`authentication_methods`, `environment`, `presence_expires_at`,
`authority_expires_at`, `idle_expires_at`, `created_at`, `last_seen_at`,
`rotated_at`, `revoked_at`, `risk_state`), the step-up state (`stepped_up`,
`step_up_expires_at`, `step_up_capability_id`), and
`meta: { "csrf_token", "granted_disclosure" }`.

### POST /v1/kyber/auth/step-up/options

Issues an authenticator challenge for the session's bound device. Requires
`require_kyber_access(SELF_CAPABILITY)`; 403 if the session is not device-bound.
Body: optional `capability_id`. Response: `{ "challenge_id", "challenge",
"device_id", "capability_id" }`. The challenge is a single-use, server-issued,
device-bound ECDSA P-256 proof challenge (32 CSPRNG bytes, 120 s TTL).

### POST /v1/kyber/auth/step-up/verify

Verifies a signed assertion and elevates the session. Requires
`require_kyber_access(SELF_CAPABILITY)`. Body: `challenge_id`, `signature`,
optional `capability_id`, `reason`, `ttl_minutes`. The `signature` is a
base64url ECDSA-SHA256 over the issued challenge bytes and may be either the raw
64-byte IEEE P1363 form (`r||s`, as WebCrypto emits) **or** DER; both are
accepted and verified. A successful elevation **rotates the session handle** (the
response sets a new session cookie and a fresh CSRF token), so a handle captured
before the elevation cannot ride it. Response: `{ "grant_id", "capability_id",
"expires_at", "session" }` plus `meta: { "csrf_token" }`. Step-up TTL is clamped
to 1–60 minutes (shortest role-template `step_up_minutes`, default 5); grants
are session- and device-bound, single-purpose when a capability is named, and
consumable.

### Additional session routes

| Method | Path | Description |
|---|---|---|
| GET | `/v1/kyber/auth/sessions` | Every session the caller holds — self only, never another operator's. `meta`: `{ "count", "current_session_id" }`. |
| POST | `/v1/kyber/auth/sessions/{session_id}/revoke` | End a session. Callers may always end their own; ending another operator's requires `kyber.workforce.manage`. Emits a `session_revoked` sync event. |

---

## Kyber Command Receipts — Read (v8.12.0)

Read-only surfaces for the governed command lifecycle at `/v1/kyber/ops/*`. Both
routes require `kyber.audit.read` (AUDIT_READ) at disclosure
`D4_EVENT_EVIDENCE` and read action class. `verification: null` on the describe
payload is a real answer — "not verified" — and must be rendered as such, never
omitted: that is the difference between a question nobody asked and one that is
still open, and the whole point of the `executed_unverified` status.

| Method | Path | Description |
|---|---|---|
| GET | `/v1/kyber/ops/commands` | List commands. Query params: `status` (default `open`), `command_type`, `limit` (1–500, default 100). `status=open` **includes `executed_unverified`** — a command whose postconditions were never confirmed is still an open question. Response `{ "commands": [...], "count", "status_filter" }`. |
| GET | `/v1/kyber/ops/commands/{command_id}` | One command with its execution and its verification. `verification: null` means the postconditions were never confirmed. |

---

## Kyber Mobile Action Digest (v8.12.0)

`GET /v1/kyber/mobile/actions` — a **read-only** action-availability digest for
the authenticated operator, gated by `require_kyber_access(SELF_CAPABILITY)`.
It reports what a governed action *exists for*, which capability that action
would require, and whether step-up is fresh. It performs **no mutations and
dispatches nothing** — the governed command lifecycle stays at
`/v1/kyber/ops/commands/*`, and there is no second command plane.

Everything is composed from the owning services (the exception queue, the open
command list, and session step-up state) and never re-derives their priority,
verification, or correlation logic.

Response shape:

```json
{
  "data": {
    "tiers": { "tier0": [], "tier1": [], "tier2": [], "tier3": [] },
    "counts": { "tier0": 0, "tier1": 0, "tier2": 0, "tier3": 0 },
    "step_up_required": false,
    "step_up": { "fresh": true, "grant_id": null, "expires_at": null },
    "generated_at": "..."
  }
}
```

Tier items carry `kind` (`exception` | `command`), `id`, `title`, `severity`,
`status`, `action_class`, `available_action`, `capability_id`,
`requires_step_up`, `priority_score`, `signal_count`, `last_seen_at`. Tier
vocabulary is presentational: `tier0` = act now (critical exceptions + open
high-impact/fleet-destructive commands), `tier1` = needs action, `tier2` = watch,
`tier3` = informational.

---

## Kyber Mobile Proof Keys (v8.12.0)

Mobile-bound ECDSA P-256 proof-key enrollment for Kyber operators
(`/v1/kyber/mobile/proof-keys/*`). Uses the **same** device-proof store, key
validation, and verify path as the browser-profile mechanism — not a second
proof system. Every route is gated by `require_kyber_access(SELF_CAPABILITY)`.

| Method | Path | Description |
|---|---|---|
| POST | `/v1/kyber/mobile/proof-keys` | Register or re-enroll a proof key. Body: `device_id`, `public_key` (base64url SPKI ECDSA P-256; `algorithm` must be `ES256`, anything else is HTTP 400), optional `label`. Idempotent upsert: re-enrolling a device with a different key replaces the stored key in place; an identical key is a no-op. An absent or foreign `device_id` reads as 404 (never 403). Response is the full record, including the SPKI `public_key`, so the client can confirm the exact key stored. |
| GET | `/v1/kyber/mobile/proof-keys` | List the caller's live registered proof keys. **Redacted** — never returns `public_key`; only `proof_key_id`, `device_id`, `operator_id`, `algorithm`, `created_at`, `last_verified_at`. Response `{ "operator_id", "proof_keys": [...] }`. |
| DELETE | `/v1/kyber/mobile/proof-keys/{proof_key_id}` | Revoke a proof key (sets `revoked_at`; the row stays for forensics). Idempotent; absent and foreign keys both read as 404. Response is the full record. |

The `label` field is accepted on the wire for contract stability but is not
persisted on the `DeviceProofKey` row; it is carried in the re-key audit event
instead.

---

## Model Runtime — Multi-Model Intelligence Harness (v8.12.0)

Operator + tenant surfaces for the provider-neutral multi-model harness
(ADR-008) under `/v1/model-runtime`
(`Backend Architecture/aether-backend/services/model_runtime/`). Serves the
generated model registry, per-provider health, tenant entitlements, usage, and
routing traces, plus the tenant model-selection preference.

**Feature-gated (ADR-008 D9).** The entire surface is inert while
`MODEL_RUNTIME_ENABLED=false` (the default): every route returns HTTP 503
`{"status":"disabled","code":"model_runtime_disabled"}` — no data is ever
served and the response shapes leak nothing. The gate is read from
`services/model_runtime/config.py` (`ModelRuntimeSettings`), not the app
settings module, and any configuration error resolves to OFF; in a non-local
environment, enabling the gate additionally requires a production-safe
credential backend and a real (non-test-only) default provider. The router is
mounted in `main.py` only when the gate is on (lazy import, ImportError-guarded
— the surface costs nothing while disabled).

**Tenant scope is server-authoritative.** The tenant is derived from the
authenticated request state (bound by the auth middleware from the verified
session), and a client can never select tenant scope via headers, body, or
query. The Aether tenant surfaces (`models`, `tenant-default`) require an
authenticated tenant (fail-closed HTTP 400
`{"status":"error","code":"tenant_required"}`). The Kyber operator surfaces
(`registry`, `health`, `usage`) are global — they carry no per-tenant data, so
only `require_operator` is applied (mirroring the repo's
`require_kyber_operator` gate; non-operators receive HTTP 401/403
`operator_required`). The tenant-scoped Kyber surfaces (`entitlements`,
`traces`) are operator-authorized and then resolve their tenant scope from the
Kyber workforce access context when a workforce session is present — a
workforce actor is intentionally tenantless, so `request.state.tenant` is never
bound for it and it must not be rejected for lacking one; a workforce session
whose access context carries no tenant scope fails closed (HTTP 403
`{"status":"error","code":"tenant_scope_required"}`), while a non-workforce
request with no authenticated tenant is rejected as before (HTTP 400
`tenant_required`).

**Credential-free responses.** Health and entitlement reasons pass through a
sanitizer that blanks secret-shaped material (`sk-`, `pk_`, `rk_live_`,
`whsec_`, `AKIA`, `Bearer `, `Authorization:`, `X-Api-Key:`, `password=`,
`secret=`, `key=`, `eyJ`). No route returns credentials or raw
request/response content; trace summaries carry routing-decision fields only.

**Backing stores.** The registry is the generated model catalog
(`shared/model_governance/generated_model_registry.py`). Health is probed by
`RuntimeHealthProbe` over a deterministic seed provider set — all
network-backed registry providers report unconfigured (fail-closed). Usage and
traces are deterministic, clearly-marked seed data (all-zero usage); a real
metering/trace store plugs in later. The tenant default model is a
non-durable in-memory seed.

| Method | Path | Summary | Notes |
|---|---|---|---|
| GET | `/v1/model-runtime/models` | Tenant model registry + default | Aether `ModelSelectionPanel`. `tenantDefaultModel` comes from a non-durable in-memory seed (`null` for unknown tenants). |
| PUT | `/v1/model-runtime/tenant-default` | Set the tenant default model | Body `{ "modelId" }`; unknown model id → HTTP 400 `unknown_model`; a model the tenant is not entitled to → HTTP 403 `model_not_entitled`; persists to the in-memory seed only; returns 204. |
| GET | `/v1/model-runtime/registry` | Full model catalog | Kyber `ModelRegistryPage`. Global surface — operator-authorized, no per-tenant data, no tenant scope required (workforce operators served). |
| GET | `/v1/model-runtime/health` | Provider health summary | Kyber `ModelRuntimeHealthPage`. Global surface — operator-authorized, no tenant scope required. `status` ∈ `ok` / `degraded` / `unhealthy`; reasons sanitized. |
| GET | `/v1/model-runtime/entitlements` | Per-model entitlement rows | Kyber `EntitlementsPage`. Operator-authorized; tenant scope resolved from the workforce access context when present, else the legacy tenant binding (403 `tenant_scope_required` for a tenantless workforce session). |
| GET | `/v1/model-runtime/usage` | Aggregate + per-model usage | Kyber `UsagePage`. Global surface — operator-authorized, no tenant scope required. Deterministic all-zero seed data (fail-closed) until metering is wired. |
| GET | `/v1/model-runtime/traces` | Routing trace summaries | Kyber `TracesPage`. Operator-authorized; content-free decision summaries only; tenant scope resolved from the workforce access context when present, else the legacy tenant binding. |

All routes share the `tags=["model-runtime"]` group and carry the D9 gate
dependency; the Aether (`models`, `tenant-default`) and Kyber (`registry`,
`health`, `entitlements`, `usage`, `traces`) clients are typed to these exact
paths in `frontend/aether/src/features/model-selection/types.ts` and
`frontend/kyber/src/features/model-runtime/types.ts` respectively.
