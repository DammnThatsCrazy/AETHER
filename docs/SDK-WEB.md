---
title: Aether Web SDK — Integration Guide
slug: sdks/web
section: sdks
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "8.9.0"
source_files:
  - packages/web/src/index.ts
  - packages/web/src/tracking/traffic-source-tracker.ts
  - packages/shared/acquisition-evidence.ts
  - packages/shared/events.ts
  - packages/shared/consent.ts
canonical_owner: sdk@aether
estimated_read_minutes: 12
toc_depth: 3
last_synced_commit: "db530dce"
---

# Aether Web SDK v8.12.0 — Integration Guide

## Installation

```html
<!-- CDN (recommended) -->
<script src="https://cdn.aether.io/sdk/v8/aether.min.js"></script>

<!-- Or via npm -->
npm install @aether/web
```

## Quick Start

```typescript
import aether from '@aether/web';

aether.init({
  apiKey: 'your-api-key',
  environment: 'production',
  modules: {
    walletTracking: true,
    autoDiscovery: true,
    ecommerce: true,
    featureFlags: true,
    heatmaps: true,
    funnels: true,
    formAnalytics: true,
  },
  privacy: {
    anonymizeIP: true,
    gdprMode: true,
  },
});
```

## Core API

### Event Tracking

`track()` is for **custom application events** — it always ships as top-level
type `track` with the custom name in `properties.event`. To emit a **canonical
backend event type** directly, use `observe()`. Official helpers (ecommerce,
etc.) emit canonical types through `observe()`; they never route canonical
events through `track()`.

```typescript
// Custom event (top-level type 'track', name in properties.event)
aether.track('button_clicked', { buttonId: 'cta-hero', variant: 'blue' });

// Canonical low-level observation — emits the first-class registry event type.
// Unknown types are a production-safe no-op (debug warning), never mislabeled.
// Payloads asserting `execution_by_aether: true` are rejected — Aether observes,
// it never executes.
aether.observe('order_completed', { orderId: 'ord_1', total: 42.0, currency: 'USD' });

// Page view (auto-tracked on SPA navigation)
aether.pageView('/pricing', { referrer: '/home' });

// Conversion
aether.conversion('signup_completed', 0, { plan: 'pro' });

// Error event (extracts message, name, stack from Error instances)
aether.error('Payment failed', new Error('Network timeout'), { paymentId: 'pay_1' });
```

Canonical event types and their required consent purposes are registry-derived
(`packages/shared/contracts/event-registry.json`); the web SDK's runtime map is
generated into `packages/web/src/core/generated-consent-map.ts`, never
hand-maintained.

### Canonical envelope context

Every emitted event carries the canonical envelope v1 context in addition to
page/device/campaign context:

- `context.surface` — the origin plane, always `'web'` for this SDK
- `context.schemaVersion` — the envelope contract version the emitter conforms to
- `context.sequence` — `{ event: n }`, a monotonic per-instance counter for
  gap/reorder detection at ingest
- `context.operatingSystem` — `{ name, version }` in the canonical envelope
  shape (`device.os` / `device.osVersion` remain for backward compatibility)
- `context.application` — the emitting product identity, when declared via
  `config.application`
- `context.journey` — snapshot of the active journey (id/name/type/status) on
  every event, not just `journey_*` lifecycle events
- Temporal provenance captured at event occurrence: `timezone`,
  `utcOffsetMinutes`, `timeZoneSource: 'device'`, `clockSource: 'device'`

Staging/production ingestion **enforces** `sequence`, `schemaVersion`, and
`surface` for release-critical event families (`core`, `journey`, `identity`,
`consent`): events missing any of them are rejected with reason
`envelope_missing:<field>`. Keep the SDK current so these fields are always
stamped.

### Identity

```typescript
// Identify a user with cross-device resolution signals
aether.hydrateIdentity({
  userId: 'user-123',
  traits: {
    email: 'user@example.com',
    plan: 'enterprise',
    createdAt: '2024-01-15',
  },
  // Identity resolution signals (optional)
  email: 'user@example.com',       // Deterministic cross-device link
  phone: '+14155551234',            // Deterministic cross-device link
  oauthProvider: 'google',          // OAuth-based linking
  oauthSubject: 'google-uid-xyz',   // OAuth subject ID
});

// Get current identity
const identity = aether.getIdentity();
// { anonymousId, userId, wallets[], traits, firstSeen, lastSeen, sessionCount }

// Reset identity (logout)
aether.reset();
```

### Cross-device journey resumption

When a user returns on a new device but presents a wallet the backend has
seen before, the SDK can resume their prior session. On `init()` the SDK
posts the current fingerprint + any cached wallets to
`POST /sdk/identity/resolve`, and it re-resolves on every subsequent wallet
connect; if the backend matches, it returns a `ResolvedIdentity` and the SDK
silently merges the anonymous IDs.

```typescript
import type { ResolvedIdentity } from '@aether/web';

aether.init({
  apiKey: '...',
  autoResumeJourney: true,    // default true
  onJourneyResumed: (resolved: ResolvedIdentity) => {
    // resolved = { anonymousId, userId, wallets, matchSignals, ... }
    // Restore session state, greet returning user, etc.
    restoreSession(resolved.userId);
  },
});
```

The same `ResolvedIdentity` shape is re-exported from the Aether SDK so
React Native and the Web SDK can share types.

### Device Fingerprint

Device fingerprinting is **personalization-gated**. The SDK generates a SHA-256
device fingerprint from browser signals (canvas, WebGL, audio, fonts, screen,
timezone, language, platform, hardware) **only after `personalization` consent
is granted** (and never under an honored Do-Not-Track signal). It is included in
`context.fingerprint.id` only on events emitted while personalization consent is
active. Revoking `personalization` clears both the cached fingerprint and the
in-memory collector, so no further events are stamped until consent is granted
again.

- Only the composite hash is sent to the backend — raw signals never leave the browser
- Fingerprinting requires `personalization` consent. Revoking `personalization` deletes the cached fingerprint.
- Cached in localStorage with a 7-day TTL

### Consent Management (GDPR/CCPA)

Consent purposes are **registry-derived** — the canonical set of 12 purposes
lives in `packages/shared/contracts/consent-registry.json` (the web SDK consumes
the generated `@aether/shared` consent contract, never a hand copy). Base
purposes (`analytics`, `marketing`, `personalization`, `web3`, `agent`,
`commerce`) can be granted together; explicit opt-in purposes
(`financial_activity`, `credit`, `location`, `economic_observability`,
`cross_chain_observability`, `fraud_prevention`) **always require separate
opt-in** and are never granted by the banner's accept-all path. Present each
explicit opt-in purpose as a separate choice in your consent UI.

`personalization` gates device fingerprinting: revoking it automatically deletes the cached fingerprint.

```typescript
// Grant consent for specific purposes
aether.consent.grant(['analytics', 'marketing', 'web3']);

// Grant an explicit opt-in purpose after showing its separate opt-in UI
aether.consent.grant(['credit']);
aether.consent.grant(['fraud_prevention']);

// Revoke consent (revoking personalization also deletes cached fingerprint)
aether.consent.revoke(['marketing']);

// Check consent state (one boolean per registry purpose — 12 fields)
const state = aether.consent.getState();
// { analytics: true, marketing: false, personalization: false, web3: true,
//   agent: false, commerce: false, financial_activity: false, credit: false,
//   location: false, economic_observability: false,
//   cross_chain_observability: false, fraud_prevention: false,
//   updatedAt: '...', policyVersion: '...' }

// Show consent banner (auto-shown in gdprMode if no prior consent).
// The banner's accept-all button grants every purpose EXCEPT the six
// explicit opt-in purposes.
aether.consent.showBanner({ position: 'bottom', theme: 'dark' });

// Listen for consent changes
const unsub = aether.consent.onUpdate((state) => {
  console.log('Consent updated:', state);
});

// Persist an authoritative, deterministic consent receipt to the backend
// (POST /v1/consent/records). Returns the canonical receipt.
const receipt = await aether.consent.recordReceipt({
  tenant_id: 'tenant-1',
  subject_id: 'user-123',
  purposes: ['analytics', 'marketing'],
  state: 'granted',
  source: 'banner',
  policy_version: '2026-06',
});
```

The public consent facade exposes `getState`, `grant`, `revoke`, `showBanner`,
`hideBanner`, `onUpdate`, and `recordReceipt`. There is no public `grantAll()`
method — accept-all is a banner action, and it never grants explicit opt-in
purposes.

## Web3 Wallet Tracking

The SDK detects wallets across 16 VM families:

| VM | Wallets Detected |
|---|---|
| **EVM** | MetaMask, Coinbase, Rainbow, WalletConnect, Rabby, Brave, Trust |
| **Solana (SVM)** | Phantom, Solflare, Backpack, Glow |
| **Bitcoin** | Unisat, Xverse, Leather |
| **Move (SUI)** | Sui Wallet, Ethos, Martian, Surf |
| **Aptos** (also Move) | Petra, Martian, Pontem |
| **NEAR** | NEAR Wallet, MyNearWallet, Meteor |
| **TRON (TVM)** | TronLink |
| **Cosmos** | Keplr, Leap |
| **TON** | Tonkeeper, OpenMask |
| **Starknet** | Argent X, Braavos |
| **Cardano** | Nami, Eternl, Flint |
| **Algorand** | Pera, MyAlgo |
| **Hedera** | HashPack, Blade |
| **Stellar** | Freighter, Albedo |
| **Substrate** (Polkadot/Kusama) | Polkadot{.js}, Talisman |
| **ICP** (Internet Computer) | Plug, Stoic |

`aether.wallet.connect<VM>(...)` exists for every family
(`connectAptos`, `connectTON`, `connectStarknet`, `connectCardano`,
`connectAlgorand`, `connectHedera`, `connectStellar`,
`connectSubstrate`, `connectICP` joined the original seven).

### Wallet Events

```typescript
// EVM wallet
aether.wallet.connect(address, { chainId: 1, type: 'metamask' });
aether.wallet.disconnect(address);
aether.wallet.transaction(txHash, { chainId: 1, value: '1.5' });

// Multi-VM wallets
aether.wallet.connectSVM(address, { type: 'phantom' });
aether.wallet.connectBTC(address, { type: 'unisat' });
aether.wallet.connectSUI(address, { type: 'sui-wallet' });
aether.wallet.connectNEAR(accountId, { type: 'near-wallet' });
aether.wallet.connectTRON(address, { type: 'tronlink' });
aether.wallet.connectCosmos(address, { type: 'keplr' });

// Get all connected wallets
const wallets = aether.wallet.getWallets();
const evmWallets = aether.wallet.getWalletsByVM('evm');

// Listen for wallet changes
const unsub = aether.wallet.onWalletChange((wallets) => {
  console.log('Wallets changed:', wallets);
});
```

### Transaction Enrichment

Raw transaction data is shipped to the backend where it gets classified:
- DeFi protocol identification (Uniswap, Aave, Compound, etc.)
- Transaction type (swap, stake, lend, bridge, NFT mint, etc.)
- Gas analytics and whale detection
- Portfolio aggregation across all connected wallets

## Ecommerce

Ecommerce helpers emit **canonical top-level event types** via `observe()`
(`commerce` consent). `trackAddToCart` emits `cart_item_added`,
`trackRemoveFromCart` emits `cart_item_removed`, `trackProductView` emits
`product_viewed`, `trackCheckout` emits `checkout_started`, and `trackPurchase`
emits `order_completed`. The retired legacy names `product_added` /
`product_removed` are no longer emitted; the deprecated `productAdded()` /
`productRemoved()` aliases now emit the canonical payloads.

Alongside the manual helpers, an opt-out **commerce auto-detection engine**
(`modules.commerceDetection`, default on) watches the DOM for product views,
cart changes, checkout starts and confirmations, and emits raw
`SDKCommerceSignal`s that are bridged into the canonical event plane (see
[SDK-COMMERCE-BRIDGES.md](SDK-COMMERCE-BRIDGES.md)). Confirmation is
server-owned; the SDK plane never re-emits runtime-domain `commerce.*` types.

```typescript
// Product view — emits canonical product_viewed
aether.ecommerce.trackProductView({
  id: 'sku-001', name: 'Widget Pro', price: 29.99, category: 'tools'
});

// Add to cart
aether.ecommerce.trackAddToCart({
  productId: 'sku-001', quantity: 2, price: 29.99
});

// Remove from cart
aether.ecommerce.trackRemoveFromCart({
  productId: 'sku-001', quantity: 1
});

// Checkout
aether.ecommerce.trackCheckout([
  { productId: 'sku-001', quantity: 1, price: 29.99 }
], 1); // step number

// Purchase
aether.ecommerce.trackPurchase({
  orderId: 'order-456', total: 29.99, currency: 'USD',
  items: [{ productId: 'sku-001', quantity: 1, price: 29.99 }]
});
```

## Feature Flags

Feature flags are fetched from the server on `init()` and cached locally.

```typescript
// Boolean check
if (aether.featureFlag.isEnabled('dark-mode')) {
  enableDarkMode();
}

// Get typed value
const limit = aether.featureFlag.getValue('upload-limit', 10);

// Force refresh from server
await aether.featureFlag.refresh();
```

## Heatmaps

Heatmap data is collected automatically when `modules.heatmaps: true`. The SDK captures:

- **Click coordinates** — `{x, y, selector, timestamp}`
- **Mouse movement** — throttled to 100ms intervals
- **Scroll depth** — percentage-based scroll tracking

All coordinates are shipped raw to the backend, which builds the grid visualization.

## Form Analytics

When `modules.formAnalytics: true`, the SDK captures:

- Field focus/blur events with timestamps
- Field change events (values are NOT captured, only field names)
- Form submission events

```typescript
// Events are auto-captured. No manual API needed.
// The backend analyzes:
// - Time spent per field
// - Field abandonment patterns
// - Form completion rates
```

## Funnels

Funnel definitions come from the server via `/v1/config`. The SDK tags events with funnel metadata when they match server-defined funnel steps.

```typescript
// Funnels are configured in the Aether dashboard, not in code.
// The SDK receives funnel definitions at init and tags matching events.
```

## Traffic Source Attribution

The SDK automatically captures on init:
- `document.referrer` — full referrer URL
- `referrerDomain` — parsed hostname with `www.` stripped (e.g. `google.com`, `t.co`)
- All UTM parameters (`utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`)
- 12 click IDs (`gclid`, `msclkid`, `fbclid`, `ttclid`, `twclid`, `li_fat_id`, `rdt_cid`, `scid`, `dclid`, `epik`, `irclickid`, `aff_id`)
- The opaque `aether_ref` value as `referralToken`
- Landing page URL

**SPA persistence:** Traffic source data is cached in `sessionStorage` on first detection. Subsequent SPA navigations return the original source data instead of losing it when `document.referrer` clears.

**Wire shape:** The standard web SDK attaches its first-touch observations to
events as `context.trafficSource`; it does not emit a separate
`context.acquisitionEvidence` field. `referralToken` is forwarded unchanged in
that raw context and is interpreted only after server-side verification — the
typed field is its ONLY carrier: the captured landing page URL is sanitized
(fragments and sensitive query params such as `aether_ref` and click IDs
stripped) so the token never travels inside a URL. The schema-versioned
`AcquisitionEvidence` helper from `@aether/shared` (schema v3, including
`entryMethod`, `destinationDomain`, and first-touch fields) remains available
to custom integrations through
`evidenceFromSearchParams(new URLSearchParams(window.location.search))`.

Classification (including AI provider/product, actor, mediation, verification,
and attribution eligibility) happens server-side using the canonical
`SourceClassifier`; the SDK ships raw signals only.

## Rewards (A6 — Attribution-Verified Eligibility)

The SDK emits reward lifecycle events as part of the no-custody reward enablement system.
Aether verifies eligibility and produces reward action payloads; tenants execute rewards
through their own configured rails.

The shared `EventContext` carries the reward correlation fields
(`rewardCampaignId`, `rewardIdempotencyKey`, `rewardWalletAddress`,
`attributionResultId`); eligibility decisions and action payloads are produced
backend-side. The SDK also exposes a thin claim-only client:

```typescript
// Thin claim-only reward API — no custody, no execution
await aether.rewards.checkEligibility('user-123', 'reward-1');
await aether.rewards.getClaimPayload('user-123', 'reward-1');
await aether.rewards.submitClaim('0xTxHash...', 'reward-1');
```

Reward lifecycle event types emitted by the platform:
- `reward_action_queued` — eligibility decision produced, action payload queued
- `reward_proof_generated` — on-chain claim proof generated for `onchain_claim` rail
- `reward_delivered` — tenant delivery confirmed (webhook receipt, approval, etc.)
- `reward_claim_submitted` — tenant submitted on-chain claim tx

## Configuration Reference

```typescript
interface AetherConfig {
  apiKey: string;                          // Required
  environment?: 'production' | 'staging' | 'development';
  appVersion?: string;                     // Host app version (fleet heartbeats)
  application?: {                          // Canonical envelope: emitting product
    name?: string; version?: string;       // identity, stamped as
    build?: string; environment?: string;  // context.application on every event
    namespace?: string;
  };
  endpoint?: string;                       // Default: 'https://api.aether.io'
  wsEndpoint?: string;                     // WebSocket endpoint override
  debug?: boolean;                         // Enable console logging
  autoResumeJourney?: boolean;             // Cross-device resolve (default: true)
  onJourneyResumed?: (identity: ResolvedIdentity) => void;
  journeyTimeoutMs?: number;               // Inactivity window before abandonment
  onBatchResult?: (health: BatchHealth) => void; // Per-batch ingestion health
  modules?: {
    // Web2 Analytics
    autoDiscovery?: boolean;               // Auto-track clicks (default: true)
    navigationCorrelation?: boolean;       // navigation_intent/arrival events (default: true, requires autoDiscovery)
    ecommerce?: boolean;                   // Ecommerce tracking (default: true)
    commerceDetection?: boolean;           // DOM commerce auto-detection → SDK signals (default: true)
    featureFlags?: boolean;                // Feature flags (default: false)
    heatmaps?: boolean;                    // Heatmap collection (default: false)
    funnels?: boolean;                     // Funnel tagging (default: false)
    formAnalytics?: boolean;               // Form field tracking (default: true)
    performance?: boolean | { sampleRate?: number }; // Web Vitals / Navigation Timing / Long Tasks / Memory (default: true)
    // Web3 (enable per VM family — one flag per supported family)
    walletTracking?: boolean;              // EVM wallets
    svmTracking?: boolean;                 // Solana wallets
    bitcoinTracking?: boolean;             // Bitcoin wallets
    moveTracking?: boolean;                // SUI/Move wallets
    nearTracking?: boolean;                // NEAR wallets
    tronTracking?: boolean;                // TRON wallets
    cosmosTracking?: boolean;              // Cosmos wallets
    aptosTracking?: boolean;               // Aptos wallets
    tonTracking?: boolean;                 // TON wallets
    starknetTracking?: boolean;            // Starknet wallets
    cardanoTracking?: boolean;             // Cardano wallets
    substrateTracking?: boolean;           // Polkadot/Kusama wallets
    algorandTracking?: boolean;            // Algorand wallets
    hederaTracking?: boolean;              // Hedera wallets
    stellarTracking?: boolean;             // Stellar wallets
    icpTracking?: boolean;                 // Internet Computer wallets
    cosmosChains?: string[];               // Cosmos chain IDs (default: sei-pacific-1)
    // Connect-time enrichment (optional, adds latency)
    approvalScan?: boolean;
    domainResolution?: boolean;
    networkContext?: boolean;
  };
  privacy?: {
    anonymizeIP?: boolean;                 // Hash IP addresses (default: true)
    gdprMode?: boolean;                    // Require consent before tracking
    ccpaMode?: boolean;                    // CCPA compliance
    respectDNT?: boolean;                  // Honor Do Not Track header
    maskSensitiveFields?: boolean;         // Mask passwords/CC fields
    cookieConsent?: 'none' | 'notice' | 'opt-in' | 'opt-out';
    piiPatterns?: RegExp[];                // Custom PII field patterns to mask
    sanitizeUrls?: boolean;                // Strip fragments + sensitive query params from URLs (default: true)
  };
  advanced?: {
    heartbeatInterval?: number;            // Session heartbeat in ms (default: 30000)
    batchSize?: number;                    // Events per batch (default: 10)
    flushInterval?: number;                // Flush interval in ms (default: 5000)
    maxQueueSize?: number;                 // Max queued events (default: 100)
    retry?: { maxRetries?: number; baseDelay?: number; maxDelay?: number };
    customHeaders?: Record<string, string>;
  };
}
```

## Plugins

Extend SDK functionality with plugins:

```typescript
const myPlugin: AetherPlugin = {
  name: 'my-plugin',
  version: '1.0.0',
  init(sdk) { /* called on SDK init */ },
  destroy() { /* cleanup */ },
};

aether.use(myPlugin);
```

## Architecture

The Web SDK follows a **"Sense and Ship"** architecture:

```
Browser DOM / Wallets
        │
    Raw Events (clicks, scrolls, wallet connects, purchases)
        │
    Device Fingerprint (SHA-256 from 17 browser signals)
        │
    Consent Gate (GDPR/CCPA check)
        │
    Event Queue (localStorage persistence, batch flush)
        │
    POST /v1/events → Aether Backend
        │
    Backend Processing:
    ├── Identity resolution (cross-device matching)
    ├── ML inference (9 models: intent, bot, session, identity, journey, churn, LTV, anomaly, attribution)
    ├── DeFi transaction classification
    ├── Traffic source classification
    ├── Funnel matching & analysis
    ├── Heatmap grid generation
    └── Portfolio aggregation
```

### What the SDK does NOT do (v7.0+):
- No client-side ML inference
- No DeFi protocol classification
- No wallet risk scoring
- No portfolio aggregation
- No survey rendering
- No A/B experiment assignment
- No OTA data module updates
- No traffic source classification
- No heatmap grid building

(Web Vitals / Navigation Timing / Long Tasks / Memory *are* collected
client-side by the performance module — raw metrics only; analysis is
backend-side.)

All of the above are handled by the Aether backend.

## Intelligence Graph Event Types

The SDK ships granular lifecycle emitters for agent activity and x402 payment flows, plus legacy aliases kept for backward compatibility.

### Agent lifecycle events (`agent` consent)

| Emitter | Event type | Description |
|---|---|---|
| `aether.agent.registered(props)` | `agent_registered` | Agent registered with the platform |
| `aether.agent.updated(props)` | `agent_updated` | Agent config/capabilities updated |
| `aether.agent.authorized(props)` | `agent_authorized` | Delegation granted to agent |
| `aether.agent.deauthorized(props)` | `agent_deauthorized` | Delegation revoked |
| `aether.agent.capabilityGranted(props)` | `agent_capability_granted` | Specific capability granted |
| `aether.agent.capabilityRevoked(props)` | `agent_capability_revoked` | Specific capability revoked |
| `aether.agent.taskCreated(props)` | `agent_task_created` | New task created for agent |
| `aether.agent.taskDecomposed(props)` | `agent_task_decomposed` | Task split into subtasks |
| `aether.agent.taskStarted(props)` | `agent_task_started` | Task execution began |
| `aether.agent.taskCompleted(props)` | `agent_task_completed` | Task finished successfully |
| `aether.agent.taskFailed(props)` | `agent_task_failed` | Task finished with error |
| `aether.agent.toolCalled(props)` | `agent_tool_called` | Agent invoked an external tool |
| `aether.agent.resourceRequested(props)` | `agent_resource_requested` | Agent requested a resource |
| `aether.agent.delegatedTask(props)` | `agent_delegated_task` | Task delegated to another agent |
| `aether.agent.subagentSpawned(props)` | `agent_subagent_spawned` | Child agent created |
| `aether.agent.policyEvaluated(props)` | `agent_policy_evaluated` | Policy check executed |
| `aether.agent.handoff(props)` | `agent_handoff` | Control handed to another agent/session |
| `aether.agent.escalatedToHuman(props)` | `agent_escalated_to_human` | Agent escalated to human review |
| `aether.agent.outcomeRecorded(props)` | `agent_outcome_recorded` | Final agent outcome captured |

Legacy aliases (backward compatible): `aether.agent.task()` → `agent_task`, `aether.agent.decision()` → `agent_decision`, `aether.agent.interaction()` → `a2h_interaction`.

### x402 payment lifecycle events (`commerce` consent)

| Emitter | Event type | Description |
|---|---|---|
| `aether.x402.resourceRequested(props)` | `x402_resource_requested` | Resource behind x402 paywall requested |
| `aether.x402.paymentRequired(props)` | `x402_payment_required` | Server returned HTTP 402 |
| `aether.x402.quoteReceived(props)` | `x402_quote_received` | Payment quote received from facilitator |
| `aether.x402.authorizationRequested(props)` | `x402_authorization_requested` | Authorization from owner requested |
| `aether.x402.authorizationResolved(props)` | `x402_authorization_resolved` | Authorization approved or denied |
| `aether.x402.paymentIntentCreated(props)` | `x402_payment_intent_created` | Payment intent record created |
| `aether.x402.paymentSubmitted(props)` | `x402_payment_submitted` | Payment submitted on-chain or via rail |
| `aether.x402.paymentSettled(props)` | `x402_payment_settled` | Payment confirmed settled (terminal) |
| `aether.x402.paymentFailed(props)` | `x402_payment_failed` | Payment failed (terminal) |
| `aether.x402.paymentTimeout(props)` | `x402_payment_timeout` | Payment timed out (terminal) |
| `aether.x402.receiptVerified(props)` | `x402_receipt_verified` | Receipt verified by service |
| `aether.x402.accessGranted(props)` | `x402_access_granted` | Access to resource granted |
| `aether.x402.accessDenied(props)` | `x402_access_denied` | Access to resource denied |
| `aether.x402.refundOrReversal(props)` | `x402_refund_or_reversal` | Refund or on-chain reversal processed |

Legacy alias: `aether.x402.payment()` → `x402_payment`.

### Consent mapping

All events are silently dropped at flush time if the required consent purpose is not granted:
- Agent lifecycle events → `agent` consent required
- x402 lifecycle events → `commerce` consent required
- `contract_action` → `web3` consent required

## React Browser Wrapper (`@aether/web/react`)

Install: `npm install @aether/web react`

```tsx
import { AetherProvider, useAether, useConsentState, useIdentity, useScreenOrPageTracking, useJourneyResumed } from '@aether/web/react';

function App() {
  return (
    <AetherProvider config={{ apiKey: 'YOUR_KEY' }}>
      <MyComponent />
    </AetherProvider>
  );
}

function MyComponent() {
  const aether = useAether();          // SDK singleton
  const consent = useConsentState();   // live consent state
  const identity = useIdentity();      // live identity

  // Auto-track page view on mount / name change
  useScreenOrPageTracking('Home');

  // Register journey resumed callback
  useJourneyResumed((resolved) => console.log('Resumed:', resolved.userId));

  return <button onClick={() => aether.track('cta_click')}>Click</button>;
}
```

The provider is SSR-safe: `AetherProvider` is a no-op when `typeof window === 'undefined'`.
