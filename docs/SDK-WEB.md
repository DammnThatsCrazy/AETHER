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
  - packages/shared/events.ts
  - packages/shared/consent.ts
canonical_owner: sdk@aether
estimated_read_minutes: 12
toc_depth: 3
last_synced_commit: 4d76caf
---

# Aether Web SDK v8.11.0 — Integration Guide

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

```typescript
// Custom event
aether.track('button_clicked', { buttonId: 'cta-hero', variant: 'blue' });

// Page view (auto-tracked on SPA navigation)
aether.pageView('/pricing', { referrer: '/home' });

// Conversion
aether.conversion('signup_completed', 0, { plan: 'pro' });

// Error event (new in 8.9.0 — extracts message, name, stack from Error instances)
aether.error('Payment failed', new Error('Network timeout'), { paymentId: 'pay_1' });
```

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
posts the current fingerprint + any connected wallets to
`POST /sdk/identity/resolve`; if the backend matches, it returns a
`ResolvedIdentity` and the SDK silently merges the anonymous IDs.

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

The SDK automatically generates a SHA-256 device fingerprint on initialization from 17 browser signals (canvas rendering, WebGL, audio context, fonts, screen, timezone, language, platform, hardware). The fingerprint is included in every event's `context.fingerprint.id`.

- Only the composite hash is sent to the backend — raw signals never leave the browser
- Fingerprinting requires `personalization` consent. Revoking `personalization` deletes the cached fingerprint.
- Cached in localStorage with a 7-day TTL

### Consent Management (GDPR/CCPA)

Eight canonical purposes: `analytics`, `marketing`, `personalization`, `web3`, `agent`, `commerce`,
`credit`, `location`. `credit` and `location` **always require explicit opt-in** — `grantAll()` never
grants them. Present them as separate choices in your consent UI.

`personalization` gates device fingerprinting: revoking it automatically deletes the cached fingerprint.

```typescript
// Grant consent for specific purposes
aether.consent.grant(['analytics', 'marketing', 'web3']);

// Grant all non-sensitive purposes (excludes credit and location)
aether.consent.grantAll();

// Grant credit after showing separate opt-in UI
aether.consent.grant(['credit']);

// Revoke consent (revoking personalization also deletes cached fingerprint)
aether.consent.revoke(['marketing']);

// Check consent state (all 8 boolean fields)
const state = aether.consent.getState();
// { analytics: true, marketing: false, personalization: false, web3: true,
//   agent: false, commerce: false, credit: false, location: false,
//   updatedAt: '...', policyVersion: '...' }

// Show consent banner (auto-shown in gdprMode if no prior consent)
aether.consent.showBanner({ position: 'bottom', theme: 'dark' });

// Listen for consent changes
const unsub = aether.consent.onUpdate((state) => {
  console.log('Consent updated:', state);
});
```

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

```typescript
// Product view
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
- Landing page URL

**SPA persistence:** Traffic source data is cached in `sessionStorage` on first detection. Subsequent SPA navigations return the original source data instead of losing it when `document.referrer` clears.

**Acquisition evidence envelope (v8.11.0+):** The SDK emits an `AcquisitionEvidence` envelope (from `@aether/shared`) on landing that captures the full attribution signal set — UTM params, click IDs, platform identity, `utm_id`, `externalCampaignId`, `canonicalCampaignId`, and temporal metadata. This envelope is attached to touchpoint events as `acquisitionEvidence` and is used by the server-side `CampaignResolver` to deterministically link touchpoints to canonical campaign UUIDs. Import via `import type { AcquisitionEvidence } from '@aether/shared'` or call `evidenceFromSearchParams(new URLSearchParams(window.location.search))`.

Classification (organic, paid, social, email, direct, etc.) happens server-side via `POST /v1/track/traffic-source` using the `SourceClassifier` — the SDK ships raw signals only.

## Rewards (A6 — Attribution-Verified Eligibility)

The SDK emits reward lifecycle events as part of the no-custody reward enablement system.
Aether verifies eligibility and produces reward action payloads; tenants execute rewards
through their own configured rails.

```typescript
// Emit reward eligibility events (emitted automatically by the backend via reward_action_queued)
// The SDK carries reward context in EventContext:
aether.track('conversion', {
  properties: { channel: 'organic', value: 49.99 },
  context: {
    rewardCampaignId: 'camp_uuid',
    rewardIdempotencyKey: 'evt_session_123_conversion',
    rewardWalletAddress: '0xf39Fd...',
    attributionResultId: 'attr_abc',
  },
});
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
  endpoint?: string;                       // Default: 'https://api.aether.io'
  debug?: boolean;                         // Enable console logging
  modules?: {
    // Web2 Analytics
    autoDiscovery?: boolean;               // Auto-track clicks (default: true)
    ecommerce?: boolean;                   // Ecommerce tracking (default: true)
    featureFlags?: boolean;                // Feature flags (default: false)
    heatmaps?: boolean;                    // Heatmap collection (default: false)
    funnels?: boolean;                     // Funnel tagging (default: false)
    formAnalytics?: boolean;               // Form field tracking (default: true)
    // Web3 (enable per VM family)
    walletTracking?: boolean;              // EVM wallets
    svmTracking?: boolean;                 // Solana wallets
    bitcoinTracking?: boolean;             // Bitcoin wallets
    moveTracking?: boolean;                // SUI/Move wallets
    nearTracking?: boolean;                // NEAR wallets
    tronTracking?: boolean;                // TRON wallets
    cosmosTracking?: boolean;              // Cosmos wallets
  };
  privacy?: {
    anonymizeIP?: boolean;                 // Hash IP addresses (default: true)
    gdprMode?: boolean;                    // Require consent before tracking
    ccpaMode?: boolean;                    // CCPA compliance
    respectDNT?: boolean;                  // Honor Do Not Track header
    maskSensitiveFields?: boolean;         // Mask passwords/CC fields
    cookieConsent?: 'none' | 'notice' | 'opt-in' | 'opt-out';
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
- No Web Vitals collection
- No OTA data module updates
- No traffic source classification
- No heatmap grid building

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
