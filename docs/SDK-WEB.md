# Aether Web SDK v7.0.0 — Integration Guide

## Installation

```html
<!-- CDN (recommended) -->
<script src="https://cdn.aether.io/sdk/v7/aether.min.js"></script>

<!-- Or via npm -->
npm install @aether/web-sdk
```

## Quick Start

```typescript
import { aether } from '@aether/web-sdk';

aether.init({
  apiKey: 'your-api-key',
  environment: 'production',
  modules: {
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

// Page/screen view
aether.page('pricing', { referrer: '/home' });

// Conversion
aether.conversion('signup_completed', 0, { plan: 'pro' });
```

### Identity

```typescript
// Identify a user
aether.identify('user-123', {
  email: 'user@example.com',
  plan: 'enterprise',
  createdAt: '2024-01-15',
});

// Get anonymous ID (auto-generated)
const anonId = aether.getAnonymousId();

// Reset identity (logout)
aether.reset();
```

### Consent Management (GDPR/CCPA)

```typescript
// Grant consent for specific categories
aether.consent.grant(['analytics', 'marketing']);

// Revoke consent
aether.consent.revoke(['marketing']);

// Check consent state
const state = aether.consent.getState();
// { analytics: true, marketing: false, functional: true }
```

## Web3 Wallet Tracking

The SDK automatically detects wallets across 7 VM families:

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
// Wallet events are captured automatically when detected.
// You can also manually track:
aether.wallet.connect(address, { chainId: 1, walletType: 'metamask' });
aether.wallet.disconnect(address);
aether.wallet.transaction(txHash, { chainId: 1, value: '1.5' });
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
const limit = aether.featureFlag.getValue('upload-limit', 10); // default: 10

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
- `document.referrer`
- All UTM parameters (`utm_source`, `utm_medium`, `utm_campaign`, etc.)
- Click IDs (`gclid`, `fbclid`, `ttclid`, `msclkid`, etc.)
- Landing page URL

Classification (organic, paid, social, email, etc.) happens server-side.

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
  apiKey: string;
  environment?: 'production' | 'staging' | 'development';
  endpoint?: string;           // Custom API endpoint
  debug?: boolean;             // Enable console logging
  batchSize?: number;          // Events per batch (default: 10)
  flushInterval?: number;      // Flush interval in ms (default: 5000)
  modules?: {
    autoDiscovery?: boolean;   // Auto-track clicks (default: true)
    ecommerce?: boolean;       // Ecommerce tracking (default: false)
    featureFlags?: boolean;    // Feature flags (default: false)
    heatmaps?: boolean;        // Heatmap collection (default: false)
    funnels?: boolean;         // Funnel tagging (default: false)
    formAnalytics?: boolean;   // Form field tracking (default: false)
    web3?: boolean;            // Web3 wallet detection (default: true)
  };
  privacy?: {
    anonymizeIP?: boolean;     // Hash IP addresses (default: true)
    gdprMode?: boolean;        // Require consent before tracking (default: false)
    respectDNT?: boolean;      // Honor Do Not Track header (default: true)
  };
}
```

## Architecture

The Web SDK follows a **"Sense and Ship"** architecture:

```
Browser DOM / Wallets
        |
    Raw Events (clicks, scrolls, wallet connects, purchases)
        |
    Consent Gate (GDPR/CCPA check)
        |
    Event Queue (localStorage persistence, batch flush)
        |
    POST /v1/events → Aether Backend
        |
    Backend Processing:
    - ML inference (intent, bot detection)
    - DeFi transaction classification
    - Traffic source classification
    - Funnel matching & analysis
    - Heatmap grid generation
    - Portfolio aggregation
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
