---
title: Getting Started with the Web SDK
slug: quickstart/web-sdk
section: quickstart
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: sdk@aether
estimated_read_minutes: 5
toc_depth: 3
---

# Getting Started with the Web SDK

`@aether/web` is Aether's browser SDK. It captures page views, custom events,
e-commerce signals, wallet activity, and performance metrics from a single
`init()` call, and ships them through a consent-aware, batched event queue.

This guide gets a page from zero to its first verified event in about five
minutes.

## Install

```bash
npm install @aether/web
```

A CDN build is also available if you'd rather not add a build-time
dependency:

```html
<script src="https://cdn.aether.io/sdk/v8/aether.min.js"></script>
```

## Initialize

Create a write-scoped API key in **Settings → API Keys**, then initialize the
SDK as early as possible on the page — typically in your app's entry point:

```typescript
import aether from '@aether/web';

aether.init({
  apiKey: 'YOUR_WRITE_KEY',
  environment: 'production',
  modules: {
    ecommerce: true,
    formAnalytics: true,
    performance: true,
  },
  privacy: {
    anonymizeIP: true,
    gdprMode: true,
  },
});
```

`init()` requires only `apiKey`. Everything else — page-view tracking,
auto-discovery of clicks, performance metrics — is on by default; pass
`modules: { <name>: false }` to disable a module, or `true` to opt into an
off-by-default one (`heatmaps`, `funnels`, `featureFlags`, wallet tracking for
each supported chain family).

The SDK fires an initial `page` event automatically and re-fires on every SPA
route change — no manual `pageView()` call is required for a standard React,
Vue, or Next.js app.

## Track events

Two emitters cover almost everything you'll need:

```typescript
// Custom application events — ships as type "track", name goes in
// properties.event. Use this for anything specific to your product.
aether.track('signup_button_clicked', { plan: 'pro', placement: 'nav' });

// Canonical registry events — ships as a first-class event type. Use this
// for events the platform already understands (orders, payments, agent
// activity, …). Unknown types are safely ignored with a console warning.
aether.observe('order_completed', {
  orderId: 'ord_492',
  total: 84.0,
  currency: 'USD',
});
```

`track()` and `observe()` are both fire-and-forget: events are enqueued,
batched, and flushed on an interval (or immediately once the queue fills).
Call `await aether.flush()` if you need to guarantee delivery before, say,
navigating away from a checkout page.

## Identify a user

```typescript
aether.hydrateIdentity({
  userId: 'usr_18f2',
  traits: { plan: 'pro', email: 'user@example.com' },
});
```

`hydrateIdentity()` merges the supplied traits into the current identity and,
when a `userId` or `email` is seen for the first time, asks the backend to
resolve any prior anonymous sessions or wallets into the same profile — see
[Profiles & Identity Resolution](/doc/concepts/profiles).

## Consent

The SDK ships deny-by-default for every consent purpose beyond `analytics`.
Grant or revoke purposes explicitly:

```typescript
aether.consent.grant(['marketing', 'personalization']);
aether.consent.revoke(['web3']);

const state = aether.consent.getState();
```

With `privacy.gdprMode: true`, the SDK also shows a first-party consent
banner (`aether.consent.showBanner()` to trigger it manually) and blocks
non-essential collection — including device fingerprinting — until consent is
granted.

## Verify your first event

Open your browser's network tab and reload the page — you should see a
request to `POST /v1/batch`. In the Aether dashboard, the **Activation**
page (`/activation`) polls for exactly this and marks your source verified
once an event lands.

## Next steps

- [React SDK quickstart](/doc/quickstart/react-sdk) — the same SDK, wrapped
  in a provider and hooks for React apps.
- [Event ingestion API](/doc/api/ingestion) — the wire format every SDK
  batches into.
- [Sources](/doc/concepts/sources) — how the Web SDK relates to the other
  ways data reaches Aether.
