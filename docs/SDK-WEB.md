# Aether Web SDK v8.7.1 — Integration Guide

## Installation

```html
<!-- CDN (recommended) -->
<script src="https://cdn.aether.io/sdk/v8/aether.min.js"></script>

<!-- Or via npm -->
npm install @aether/web-sdk
```

## Quick Start

```typescript
import aether from '@aether/web-sdk';

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

### Device Fingerprint

The SDK automatically generates a SHA-256 device fingerprint on initialization from 17 browser signals (canvas rendering, WebGL, audio context, fonts, screen, timezone, language, platform, hardware). The fingerprint is included in every event's `context.fingerprint.id`.

- Only the composite hash is sent to the backend — raw signals never leave the browser
- Fingerprinting is skipped when GDPR mode is active and analytics consent is not granted
- Cached in localStorage with a 7-day TTL

### Consent Management (GDPR/CCPA)

```typescript
// Grant consent for specific categories
aether.consent.grant(['analytics', 'marketing', 'web3']);

// Revoke consent
aether.consent.revoke(['marketing']);

// Check consent state
const state = aether.consent.getState();
// { analytics: true, marketing: false, web3: true, updatedAt: '...', policyVersion: '...' }

// Show consent banner (auto-shown in gdprMode if no prior consent)
aether.consent.showBanner({ position: 'bottom', theme: 'dark' });

// Listen for consent changes
const unsub = aether.consent.onUpdate((state) => {
  console.log('Consent updated:', state);
});
```

## Web3 Wallet Tracking

The SDK detects wallets across 7 VM families:

| VM | Wallets Detected |
|---|---|
| **EVM** | MetaMask, Coinbase, Rainbow, WalletConnect, Rabby, Brave, Trust |
| **Solana (SVM)** | Phantom, Solflare, Backpack, Glow |
| **Bitcoin** | Unisat, Xverse, Leather |
| **Move (SUI)** | Sui Wallet, Ethos, Martian, Surf |
| **NEAR** | NEAR Wallet, MyNearWallet, Meteor |
| **TRON (TVM)** | TronLink |
| **Cosmos** | Keplr, Leap |

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

Classification (organic, paid, social, email, direct, etc.) happens server-side via `POST /v1/track/traffic-source` using the `SourceClassifier` — the SDK ships raw signals only.

## Rewards

```typescript
// Check if user is eligible for a reward
const eligible = await aether.rewards.checkEligibility('user-123', 'reward-abc');

// Get pre-built claim payload (for on-chain submission)
const payload = await aether.rewards.getClaimPayload('user-123', 'reward-abc');

// Submit claim after on-chain transaction
await aether.rewards.submitClaim(txHash, 'reward-abc');
```

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

v8.0 adds 5 new event types for the Intelligence Graph:

| Event Type | Description | Required Consent |
|---|---|---|
| `agent_task` | An AI agent begins or completes a task | `agent` |
| `agent_decision` | An AI agent makes an autonomous decision | `agent` |
| `payment` | A fiat or crypto payment is recorded | `commerce` |
| `x402_payment` | An HTTP 402-based micropayment is captured | `commerce` |
| `contract_action` | A smart-contract interaction is observed | `web3` |

Two new consent purposes are available alongside the existing `analytics`, `marketing`, and `web3` purposes:
- **`agent`** — governs tracking of AI-agent activity (`agent_task`, `agent_decision`)
- **`commerce`** — governs tracking of payment events (`payment`, `x402_payment`)

The SDK routes events through a `CONSENT_MAP`:
- `agent_task` / `agent_decision` → `'agent'`
- `payment` / `x402_payment` → `'commerce'`
- `contract_action` → `'web3'`

These events are only tracked when the corresponding consent purpose is granted. If the user has not consented to the mapped purpose, the event is silently dropped at flush time, consistent with all other consent-gated event types.
