---
title: Aether SDK — Web2 Quickstart
slug: sdk-web2-quickstart
section: reference
visibility: P
audience: [dev-junior, dev-senior, buyer]
status: stable
since_version: 0.1.0
canonical_owner: sdk@aether
estimated_read_minutes: 8
toc_depth: 3
---

# Aether SDK — Web2 Quickstart

This guide gets a Web2 company — e-commerce, SaaS, media — live on Aether within 24 hours.
**No blockchain required.** No wallets, no on-chain events, no crypto context.

---

## What you'll have by the end

- Events flowing from your web app into Aether
- First entities appearing in Profile360 within 15 minutes of your first event
- Ad-platform attribution (Meta Ads, Google Ads) linked to customer journeys
- Optional: bank-account signals via Plaid

---

## Step 1 — Register your site and install the SDK

In **Settings → SDK Sites**, register the origin your site is served from. Then
mint a **publishable** key for it and paste the tag the platform renders:

```html
<script src="https://cdn.aether.network/v1.js"
        data-key="pk_YOUR_PUBLISHABLE_KEY"
        data-site="site_YOUR_SITE_ID"
        async></script>
```

That tag is the whole install: the loader reads the attributes and brings the
SDK up itself, so there is no follow-up `init()` call and no build step.

> **Use a publishable key here.** It starts with `pk_`. A secret key (`ak_`) is
> for server-side calls only — it works perfectly in this tag right up until
> somebody opens View Source, and because it carries your full account
> authority it can then write anything your account can. When you mint a key you
> choose the class; the prefix states which one you are holding.

If you would rather not hand-edit HTML, install from npm instead:

```bash
npm install @aether/web
```

```typescript
import aether from '@aether/web';
```

---

## Step 2 — Confirm the install came up

The snippet reports its own progress, so you do not have to guess whether it
worked:

```http
GET /v1/sdk/sites/{site_id}/heartbeat
```

A site that has not been installed yet reads `awaiting_first_signal`, which is
the expected answer until someone loads the page. `live` means the loader ran
*and* the SDK accepted its config. `failed` carries the reason the SDK gave.

If you installed from npm and want to configure the SDK from JavaScript rather
than attributes:

```typescript
aether.init({
  apiKey: 'pk_YOUR_PUBLISHABLE_KEY',
  siteId: 'site_YOUR_SITE_ID',    // required alongside a publishable key
  environment: 'production',
  modules: {
    ecommerce: true,              // checkout, cart, conversion events
    funnels: true,                // funnel drop-off analysis
    formAnalytics: true,          // form field timing
  },
  privacy: {
    anonymizeIP: true,
    gdprMode: true,               // gate capture on user consent
  },
});
```

`siteId` is not optional on this path. A publishable key is scoped to the sites
it was minted for, and a batch that does not declare which one it is writing for
is refused rather than accepted for your whole account.

---

## Step 3 — Track Web2 events

Aether uses a simple `track()` API. The table below shows which events to instrument for a Web2 app.

### Core events

```typescript
// User identifies (link a session to a known user)
aether.hydrateIdentity({
  userId: 'user-abc123',
  traits: {
    email: 'alice@example.com',
    plan: 'pro',
    createdAt: '2024-01-15',
  },
});

// Page view (auto-tracked on SPA navigation — or call manually)
aether.pageView('/products/widget-pro');

// Signup
aether.track('signup', {
  method: 'email',       // 'email' | 'google' | 'github'
  plan: 'pro',
});

// Add to cart
aether.track('add_to_cart', {
  productId: 'prod-123',
  productName: 'Widget Pro',
  price: 49.99,
  currency: 'USD',
  quantity: 1,
});

// Checkout
aether.track('checkout_started', {
  cartValue: 149.99,
  currency: 'USD',
  itemCount: 3,
});

aether.track('checkout_completed', {
  orderId: 'order-987',
  revenue: 149.99,
  currency: 'USD',
  paymentMethod: 'card',
});

// Session
aether.track('session_start', {
  referrer: document.referrer,
  channel: 'organic',   // 'organic' | 'paid_social' | 'email' | 'direct'
});
```

### Event taxonomy reference

| Event | When to fire | Required fields |
|---|---|---|
| `session_start` | New browser session starts | `channel` |
| `page_view` | Every page/route change | `path` |
| `signup` | User creates account | `method`, `plan` |
| `login` | User authenticates | `method` |
| `add_to_cart` | Item added to cart | `productId`, `price`, `currency` |
| `checkout_started` | Checkout flow begins | `cartValue`, `currency` |
| `checkout_completed` | Order confirmed | `orderId`, `revenue`, `currency` |
| `subscription_started` | Subscription created | `plan`, `billingPeriod` |
| `subscription_cancelled` | Subscription cancelled | `plan`, `reason` |
| `feature_used` | Feature interaction (SaaS) | `featureName` |
| `support_ticket_opened` | Support ticket created | `category` |

> **Web2 vs Web3:** Web2 events never include `wallet_address`, `chain_id`, or `tx_hash` fields. Aether handles both event types in the same pipeline — just omit blockchain fields and they are ignored.

---

## Step 4 — Connect BYOK provider keys (optional, recommended)

Provider keys let Aether pull richer signals for your customers. All keys are stored encrypted under your tenant; Aether never sees your raw credentials.

Add keys in **Settings → API Keys → Provider Keys**, or via API:

```bash
# Meta Ads
curl -X POST https://api.aether.io/v1/providers/keys \
  -H "X-API-Key: ak_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"provider_name": "meta_ads", "api_key": "YOUR_META_ACCESS_TOKEN"}'

# Google Ads
curl -X POST https://api.aether.io/v1/providers/keys \
  -H "X-API-Key: ak_YOUR_KEY" \
  -d '{"provider_name": "google_ads", "api_key": "YOUR_GOOGLE_ADS_TOKEN"}'

# Plaid (bank account signals — requires credit consent from your end-users)
curl -X POST https://api.aether.io/v1/providers/keys \
  -H "X-API-Key: ak_YOUR_KEY" \
  -d '{"provider_name": "plaid", "api_key": "YOUR_PLAID_SECRET"}'
```

Once connected, Aether nightly-syncs ad spend, ROAS, and attribution data from these platforms and surfaces them in the **Journey Economics** and **Attribution** tabs of each customer's Profile360.

---

## Step 5 — Verify in Profile360

Within 15 minutes of your first event, you should see entities appearing at:

```
https://app.aether.io/graph
```

Click any entity to open their Profile360. For a Web2 customer, you'll see:

- **Identity** tab — device graph, session history, cross-platform identity matches
- **Journey** tab — funnel stages, drop-off points, conversion timeline
- **Intelligence** tab — churn risk score, LTV prediction, behavioral patterns
- **Attribution** tab — ROAS per campaign (requires Meta/Google Ads key)

> **Data freshness:** Profile360 gold tables refresh every 15 minutes. Provider adapter sync is nightly. See [Data Freshness SLA](DATA-FRESHNESS-SLA.md) for full guarantees.

---

## What you do NOT need

| Item | Required? |
|---|---|
| Crypto wallet | ✗ No |
| Chain ID or network | ✗ No |
| On-chain events | ✗ No |
| Web3 modules in `aether.init()` | ✗ No |
| Blockchain RPC keys | ✗ No |

You can add Web3 capabilities later without touching your existing integration.

---

## Troubleshooting

**No entities appearing after 15 minutes**
- Read the install verifier first: `GET /v1/sdk/sites/{site_id}/heartbeat`. If it
  says `awaiting_first_signal`, the tag never ran — a CSP header or a snippet
  pasted outside `<head>` is the usual cause, and no amount of event debugging
  will show it.
- If it says `failed`, the `reason` field is what the SDK reported.
- Confirm the `data-key` is a `pk_...` publishable key bound to this site, and
  that `data-site` matches the site you are reading.
- Check browser devtools → Network for POST to `/v1/batch` — should return HTTP 200/202
- Ensure `aether.init()` is called before any `track()` calls
- If `gdprMode: true`, confirm the user has granted `analytics` consent first

**Events accepted but Profile360 shows no data**
- `hydrateIdentity()` must be called with a stable `userId` to create an entity record
- Anonymous sessions (no `hydrateIdentity`) are queued until identity is resolved

**Provider key test fails**
- Use `POST /v1/providers/test` to validate the key before relying on it
- Meta Ads requires a System User token with `ads_read` permission
- Google Ads requires OAuth token with `reporting` scope

---

## Next steps

- [Full SDK API reference](SDK-WEB.md)
- [Event schema contracts](SDK-EVENT-SCHEMAS.md)
- [Data Freshness SLA](DATA-FRESHNESS-SLA.md)
- [Capabilities discovery: `GET /v1/capabilities`](BACKEND-API.md)
- [BYOK provider catalog](SDKS.md)
