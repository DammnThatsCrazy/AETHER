# @aether/web

<!-- Badges -->
![Version](https://img.shields.io/badge/version-4.0.0-blue)
![TypeScript](https://img.shields.io/badge/TypeScript-strict-3178C6)
![Build](https://img.shields.io/badge/build-Rollup-EC4A3F)
![Tests](https://img.shields.io/badge/tests-Vitest-6E9F18)
![License](https://img.shields.io/badge/license-proprietary-lightgrey)

**Behavioral analytics SDK for the browser.** Track user interactions, resolve identities across sessions, run A/B experiments, monitor Web3 wallets, and score sessions with on-device ML -- all with built-in GDPR consent management and privacy-first data collection.

---

## Features

- **Event tracking** -- page views, clicks, scroll depth, form interactions, conversions, and custom events
- **Identity resolution** -- anonymous-to-known user merging with cross-subdomain persistence
- **Session management** -- automatic timeout, heartbeat, and SPA navigation support
- **GDPR consent management** -- configurable banner UI with per-purpose opt-in/opt-out
- **Auto-discovery** -- automatic capture of clicks, forms, scroll depth, rage clicks, and dead clicks
- **A/B experiments** -- deterministic variant assignment with weighted splits and exposure tracking
- **Web3 wallet tracking** -- Ethereum provider detection, chain switching, and transaction monitoring
- **Edge ML** -- in-browser intent prediction, bot detection, and session scoring (no server round-trip)
- **Performance monitoring** -- Core Web Vitals (LCP, FID, CLS, TTFB, FCP) and error tracking
- **Event batching** -- configurable batch size, flush intervals, retry with exponential backoff, and offline queue persistence
- **Privacy controls** -- data minimization, PII masking, Do Not Track support, consent-gated collection

---

## Installation

```bash
npm install @aether/web
```

```bash
yarn add @aether/web
```

```bash
pnpm add @aether/web
```

### CDN (UMD)

```html
<script src="https://cdn.aether.network/sdk/v4/aether.umd.js"></script>
<script>
  const aether = Aether.default;
  aether.init({ apiKey: 'your-key' });
</script>
```

---

## Quick Start

```typescript
import aether from '@aether/web';

// Initialize with your API key
aether.init({
  apiKey: 'your-api-key',
  environment: 'production',
});

// Track a custom event
aether.track('button_click', { element: 'cta', position: 'hero' });

// Track a page view (automatically called on init and SPA navigation)
aether.pageView('/pricing', { source: 'nav' });

// Identify a user (merges anonymous activity with known identity)
aether.hydrateIdentity({
  userId: 'user-123',
  traits: { email: 'user@example.com', plan: 'pro' },
});

// Track a conversion
aether.conversion('purchase', 49.99, { orderId: 'ORD-456' });
```

---

## Configuration

Pass an `AetherConfig` object to `aether.init()`. Only `apiKey` is required.

```typescript
aether.init({
  apiKey: 'your-api-key',
  environment: 'production',       // 'production' | 'staging' | 'development'
  endpoint: 'https://api.aether.network', // custom endpoint
  debug: false,

  modules: {
    autoDiscovery: true,           // automatic click/form/scroll capture
    formTracking: true,            // form field interaction events
    scrollDepth: true,             // scroll depth measurement
    rageClickDetection: true,      // detect frustrated repeated clicks
    deadClickDetection: true,      // detect clicks with no effect
    performanceTracking: true,     // Core Web Vitals
    errorTracking: true,           // JS error capture
    experiments: true,             // A/B testing framework
    walletTracking: true,          // Web3 wallet events
    intentPrediction: true,        // edge ML intent model
    predictiveAnalytics: true,     // ML prediction event forwarding
  },

  privacy: {
    gdprMode: true,                // show consent banner on first visit
    ccpaMode: false,
    respectDNT: true,              // honor Do Not Track header
    anonymizeIP: true,
    maskSensitiveFields: true,     // redact passwords, credit cards
    cookieConsent: 'opt-in',       // 'none' | 'notice' | 'opt-in' | 'opt-out'
    piiPatterns: [/ssn/i],         // additional PII field patterns to mask
  },

  advanced: {
    batchSize: 10,                 // events per batch
    flushInterval: 5000,           // flush timer in ms
    maxQueueSize: 100,             // force flush threshold
    heartbeatInterval: 30000,      // session heartbeat in ms
    retry: {
      maxRetries: 3,
      baseDelay: 1000,
      maxDelay: 30000,
      backoffMultiplier: 2,
    },
    customHeaders: {},
  },
});
```

---

## API Reference

### Core Methods

| Method | Signature | Description |
|---|---|---|
| `init` | `(config: AetherConfig) => void` | Initialize the SDK. Must be called before any other method. |
| `track` | `(event: string, properties?: Record<string, unknown>) => void` | Track a custom event. |
| `pageView` | `(page?: string, properties?: Record<string, unknown>) => void` | Record a page view. Called automatically on init and SPA navigation. |
| `conversion` | `(event: string, value?: number, properties?: Record<string, unknown>) => void` | Track a conversion event with optional monetary value. |
| `hydrateIdentity` | `(data: IdentityData) => void` | Merge anonymous identity with known user data. Accepts `userId`, `traits`, `walletAddress`, and chain info. |
| `getIdentity` | `() => Identity \| null` | Return the current identity object. |
| `reset` | `() => void` | Clear identity, session, and experiment data. Creates a fresh anonymous identity. |
| `flush` | `() => Promise<void>` | Send all queued events immediately. |
| `destroy` | `() => void` | Tear down the SDK and release all resources. |
| `use` | `(plugin: AetherPlugin) => void` | Register a plugin. |

### Consent

```typescript
// Get current consent state
aether.consent.getState();
// => { analytics: false, marketing: false, web3: false, updatedAt: '...', policyVersion: '1.0' }

// Grant consent for specific purposes
aether.consent.grant(['analytics', 'marketing']);

// Revoke consent
aether.consent.revoke(['marketing']);

// Show the consent banner programmatically
aether.consent.showBanner({
  position: 'bottom',       // 'bottom' | 'top' | 'center'
  theme: 'dark',            // 'light' | 'dark'
  title: 'Cookie Settings',
  acceptAllText: 'Accept',
  rejectAllText: 'Decline',
  accentColor: '#2E75B6',
});

// Hide the banner
aether.consent.hideBanner();

// Listen for consent changes
const unsubscribe = aether.consent.onUpdate((state) => {
  console.log('Consent updated:', state);
});
```

Events are automatically filtered by consent category at flush time. Consent events themselves always pass through.

### Web3 Wallet Tracking

```typescript
// Connect a wallet
aether.wallet.connect('0xabc...def', {
  chainId: 1,
  type: 'metamask',
  ens: 'user.eth',
});

// Track a transaction
aether.wallet.transaction('0xtxhash...', {
  type: 'swap',
  value: '1.5',
  from: '0xabc...def',
  to: '0x123...789',
  chainId: 1,
});

// Get wallet info
const wallet = aether.wallet.getInfo();

// Disconnect
aether.wallet.disconnect();
```

When `walletTracking` is enabled, the SDK automatically detects `window.ethereum` providers (MetaMask, Coinbase Wallet, Brave Wallet) and tracks account and chain changes.

### A/B Experiments

```typescript
// Run an experiment with equal weight
const variant = aether.experiments.run({
  id: 'checkout-flow-v2',
  variants: {
    control: () => showOriginalCheckout(),
    treatment: () => showNewCheckout(),
  },
});

// Weighted variants
aether.experiments.run({
  id: 'pricing-test',
  variants: {
    low: () => setPrice(9.99),
    mid: () => setPrice(14.99),
    high: () => setPrice(19.99),
  },
  weights: { low: 0.5, mid: 0.3, high: 0.2 },
});

// Check an existing assignment
const assignment = aether.experiments.getAssignment('checkout-flow-v2');
// => { experimentId: 'checkout-flow-v2', variantId: 'treatment', assignedAt: '...' }
```

Assignments are deterministic (FNV-1a hash of anonymous ID + experiment ID) and persist across sessions. Exposure events are tracked automatically.

### Edge ML Predictions

Register callbacks to receive real-time, in-browser predictions. No data leaves the device for these computations.

```typescript
// Intent prediction
const unsubIntent = aether.onIntentPrediction((intent) => {
  // intent.predictedAction: 'purchase' | 'signup' | 'browse' | 'exit' | 'engage' | 'idle'
  // intent.confidenceScore: 0-1
  // intent.highExitRisk: boolean
  // intent.highConversionProbability: boolean
  // intent.journeyStage: 'awareness' | 'consideration' | 'decision' | 'retention'
  if (intent.highExitRisk) {
    showExitOffer();
  }
});

// Bot detection
const unsubBot = aether.onBotDetection((score) => {
  // score.likelyBot: boolean
  // score.botType: 'human' | 'scraper' | 'automated_test' | 'click_farm' | 'legitimate_bot'
  if (score.likelyBot) {
    flagSession();
  }
});

// Session scoring
const unsubSession = aether.onSessionScore((score) => {
  // score.engagementScore: 0-100
  // score.conversionProbability: 0-1
  // score.recommendedIntervention: 'none' | 'soft_cta' | 'hard_cta' | 'exit_offer'
  if (score.recommendedIntervention === 'hard_cta') {
    showPromotion();
  }
});

// Unsubscribe when done
unsubIntent();
unsubBot();
unsubSession();
```

### Plugins

Extend the SDK with custom plugins.

```typescript
const myPlugin: AetherPlugin = {
  name: 'my-plugin',
  version: '1.0.0',
  init(sdk) {
    sdk.track('plugin_loaded', { plugin: 'my-plugin' });
  },
  destroy() {
    // cleanup
  },
};

aether.use(myPlugin);
```

---

## Modules

| Directory | File | Responsibility |
|---|---|---|
| `src/core/` | `identity.ts` | Anonymous ID generation, identity merging, cross-subdomain persistence via cookies and localStorage |
| `src/core/` | `session.ts` | Session lifecycle, 30-minute inactivity timeout, heartbeat, page/event counting |
| `src/core/` | `event-queue.ts` | Batching, flush timers, exponential backoff retry, offline localStorage persistence, `sendBeacon` fallback |
| `src/consent/` | `index.ts` | GDPR/CCPA consent state, banner UI rendering, per-purpose grant/revoke, consent-gated event filtering |
| `src/modules/` | `auto-discovery.ts` | Automatic capture of clicks, forms, scroll depth, rage clicks, dead clicks with PII masking |
| `src/modules/` | `performance.ts` | Core Web Vitals collection (LCP, FID, CLS, TTFB, FCP) and global error tracking |
| `src/modules/` | `experiments.ts` | Deterministic A/B variant assignment (FNV-1a hashing), weighted splits, exposure tracking |
| `src/ml/` | `edge-ml.ts` | Browser-side behavioral signal collection, intent prediction, bot detection, session scoring |
| `src/web3/` | `index.ts` | Ethereum provider detection, wallet connect/disconnect, chain switching, transaction monitoring |
| `src/utils/` | `index.ts` | ID generation, timestamps, localStorage/cookie helpers, device/page/campaign context extraction |
| `src/` | `types.ts` | Full TypeScript interface definitions for config, events, identity, session, ML, Web3, and consent |

---

## Build Output

Rollup produces three bundles from `src/index.ts`:

| File | Format | Notes |
|---|---|---|
| `dist/aether.cjs.js` | CommonJS | For Node.js / bundlers using `require()` |
| `dist/aether.esm.js` | ES Modules | For modern bundlers (tree-shakeable) |
| `dist/aether.umd.js` | UMD (minified) | For direct `<script>` tag inclusion; global `Aether` |

Type declarations are emitted to `dist/index.d.ts`.

---

## Development

```bash
# Build all bundles
npm run build

# Run tests
npm run test

# Type-check without emitting
npm run typecheck
```

### Project Structure

```
packages/web/
  src/
    index.ts              # SDK entry point and public API
    types.ts              # TypeScript type definitions
    core/
      identity.ts         # Identity management
      session.ts          # Session tracking
      event-queue.ts      # Event batching and delivery
    consent/
      index.ts            # GDPR consent module
    modules/
      auto-discovery.ts   # Automatic event capture
      performance.ts      # Core Web Vitals
      experiments.ts      # A/B testing
    ml/
      edge-ml.ts          # Browser-side ML predictions
    web3/
      index.ts            # Ethereum wallet tracking
    utils/
      index.ts            # Helper functions
  dist/                   # Compiled bundles
  rollup.config.mjs       # Rollup build configuration
  tsconfig.json           # TypeScript configuration
  tsconfig.build.json     # TypeScript build configuration
  package.json
```

---

## Browser Support

The SDK targets modern browsers with support for:

- `fetch` API
- `localStorage`
- `navigator.sendBeacon`
- `Intl.DateTimeFormat`
- `history.pushState` / `popstate` (SPA routing)
- `window.ethereum` (Web3 features, optional)
- `PerformanceObserver` (Web Vitals, optional)

---

## License

Proprietary. All rights reserved. See LICENSE for details.
