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
last_synced_commit: 55d372c

---
# Aether Backend API v8.9.0 — Endpoint Specification

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

### Automatic Traffic Source Classification (v8.2.0)

`POST /v1/track/traffic-source` now automatically classifies raw SDK signals into source/medium/channel using the server-side `SourceClassifier`. No client-side classification logic is needed — SDKs ship raw referrer, UTM params, click IDs, and referrer domain; the backend resolves everything.

**Classification Priority Chain:**

| Priority | Signal | Confidence | Example |
|----------|--------|------------|---------|
| 1 | Click IDs | 1.0 | `gclid=abc` → google / cpc / Paid Search |
| 2 | UTM params | 0.95 | `utm_source=newsletter` → newsletter / email / Email |
| 3 | Referrer domain | 0.9 | `t.co` → twitter / social / Organic Social |
| 4 | No signals | 0.5 | → (direct) / (none) / Direct |

**Supported Click IDs (12):** `gclid`, `msclkid`, `fbclid`, `ttclid`, `twclid`, `li_fat_id`, `rdt_cid`, `scid`, `dclid`, `epik`, `irclickid`, `aff_id`

**Channel Categories:** Paid Search, Paid Social, Organic Search, Organic Social, Email, Display, Affiliate, Referral, Direct, Other

**SourceInfo model now includes:**
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

Rails: `recommend_only` | `manual_approval` | `manual_export` | `tenant_webhook` | `onchain_claim`.
Beta (config only, no delivery): `stripe_credit` | `loyalty_points` | `coupon` | `internal_credit` | `x402_credit`.

### GET /v1/rewards/rails

List configured rails for the authenticated tenant.

### GET /v1/rewards/rails/{id}

Get a single rail configuration.

### PATCH /v1/rewards/rails/{id}

Update a rail configuration.

### POST /v1/rewards/rails/{id}/verify

Trigger verification of a rail configuration (e.g., send a test webhook, verify contract address).

### POST /v1/rewards/rails/{id}/disable

Disable a rail without deleting its configuration.

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
| GET | `/v1/providers/health` | All providers with health status and circuit breaker states |
| GET | `/v1/providers/categories` | List all provider categories and supported provider names |
| POST | `/v1/providers/test` | Test a provider call (verifies BYOK key works) |

**Permissions:**
- Key management endpoints (`POST/GET/DELETE /keys`) require `admin` permission
- Usage endpoints (`GET /usage`, `GET /usage/summary`) require `billing` permission
- Health and categories endpoints require `admin` permission
- Test endpoint requires `admin` permission

**Provider Categories:**
- `blockchain_rpc` — QuickNode, Alchemy, Infura, Custom RPC
- `block_explorer` — Etherscan, Moralis
- `social_api` — Twitter, Reddit
- `analytics_data` — Dune Analytics

**Priority Chain (every provider call):**
1. Tenant BYOK key → 2. System default provider → 3. Fallback provider(s) → 4. ServiceUnavailableError

Feature flag: `PROVIDER_GATEWAY_ENABLED=false` (default). Zero impact until activated.

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
| GET | `/v1/identity/health` | Identity resolution subsystem health — queue depth, recompute lag, conflict count |
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

**Permissions:** `write` for create/update/delete, `read` for queries

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

Event-driven multi-channel operator notification pipeline. Ingests intelligence signals from Kafka (anomaly detection, CIS quarantine, agent escalation, ML extraction, governance, commerce approvals), routes them to Slack/Discord/Telegram/Webhook, and surfaces an operator review queue with RBAC-gated approve/suppress/escalate/annotate actions.

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

### Tenant Configuration

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/notifications/config` | Get tenant notification config |
| PUT | `/v1/notifications/config` | Update config (Slack token stored via vault) |

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

### Interactive Callbacks

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/notifications/slack/callback` | Slack Block Kit action handler (HMAC-verified) |
| POST | `/v1/notifications/telegram/callback` | Telegram inline keyboard handler |

### Required Permissions

- `notifications:approve` — operator approve/suppress/escalate
- `notifications:manage` — config management
- `notifications:channels:write` — channel registration/removal
