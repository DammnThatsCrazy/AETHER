# @aether/web

<!-- Badges -->
![Version](https://img.shields.io/badge/version-8.2.0-blue)
![TypeScript](https://img.shields.io/badge/TypeScript-strict-3178C6)
![Build](https://img.shields.io/badge/build-Rollup-EC4A3F)
![Tests](https://img.shields.io/badge/tests-Vitest-6E9F18)
![License](https://img.shields.io/badge/license-proprietary-lightgrey)

**Behavioral analytics SDK for the browser with multi-chain Web3 support.** Track user interactions, resolve identities across sessions, run A/B experiments, monitor Web3 wallets across 7 VM families (EVM, Solana, Bitcoin, MoveVM, NEAR, TRON, Cosmos), track DeFi positions across 150+ protocols, aggregate cross-chain portfolios, and score sessions with on-device ML -- all with built-in GDPR consent management and privacy-first data collection.

---

## Features

- **Event tracking** -- page views, clicks, scroll depth, form interactions, conversions, and custom events
- **Identity resolution** -- anonymous-to-known user merging with cross-subdomain persistence
- **Session management** -- automatic timeout, heartbeat, and SPA navigation support
- **GDPR consent management** -- configurable banner UI with per-purpose opt-in/opt-out
- **Auto-discovery** -- automatic capture of clicks, forms, scroll depth, rage clicks, and dead clicks
- **A/B experiments** -- deterministic variant assignment with weighted splits and exposure tracking
- **Multi-chain Web3 wallet tracking** -- 7 VM families (EVM, SVM/Solana, Bitcoin, MoveVM/SUI, NEAR, TVM/TRON, Cosmos) with 20+ blockchain support, wallet classification (hot, cold, smart, exchange, protocol, multisig), and automatic provider detection
- **DeFi protocol tracking** -- 150+ protocols across 15 categories (DEX, lending, perpetuals, staking, bridges, NFTs, yield, governance, insurance, options, launchpads, payments, restaking, CEX, routing)
- **Cross-chain portfolio aggregation** -- real-time portfolio value tracking, token balances, and DeFi position monitoring across all connected chains
- **Edge ML** -- in-browser intent prediction, bot detection, and session scoring (no server round-trip)
- **Performance monitoring** -- Core Web Vitals (LCP, FID, CLS, TTFB, FCP) and error tracking
- **CDN auto-loader** -- lightweight (~3KB) loader at stable URL that dynamically fetches and caches the latest SDK bundle, with background version checks and offline fallback
- **OTA data updates** -- automatic over-the-air updates for chain registry, DeFi protocol definitions, wallet labels, and classification rules without requiring SDK reinstall
- **Event batching** -- configurable batch size, flush intervals, retry with exponential backoff, and offline queue persistence
- **Tiered semantic context** -- 3-tier consent-driven context enrichment (Essential → Functional → Rich) with journey stage inference, sentiment signals (frustration, engagement, urgency, confusion), interaction heatmaps, and inferred intent -- automatically attached to every event
- **Automatic traffic source tracking** -- zero-config detection of all traffic sources (UTM params, ad click IDs across 12 platforms, organic/social/email/referral classification), localStorage-persisted attribution with configurable window, and dynamic virtual link creation on the backend
- **Automated reward pipeline** -- SDK-side reward client with eligibility checking, oracle-signed proof retrieval, and on-chain ERC20/NFT reward claiming via connected wallet (fraud → attribution → eligibility → oracle → smart contract)
- **Multi-chain reward claiming** -- claim rewards on any supported chain (EVM, SVM/Solana, Bitcoin, MoveVM/SUI, NEAR, TVM/TRON, Cosmos) with chain-specific transaction builders and wallet adapter support
- **E-commerce tracking** -- product views, cart state management with localStorage persistence, checkout funnel, order lifecycle, refunds, coupon tracking
- **Form analytics** -- field-level interaction tracking (focus time, hesitation, corrections), abandonment detection, MutationObserver for dynamic forms
- **Feature flags** -- remote config with stale-while-revalidate caching, priority chain (overrides > remote > defaults), periodic background refresh
- **Feedback surveys** -- NPS (0-10), CSAT (1-5), CES (1-7) with configurable trigger rules (event, delay, URL, sample rate), DOM rendering
- **Heatmaps** -- click, movement, scroll, and attention tracking with IntersectionObserver and grid-based aggregation
- **Funnel tracking** -- multi-step conversion funnels with sequential/non-sequential support, timeout handling, drop-off analysis
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

### CDN (UMD -- static version)

```html
<script src="https://cdn.aether.network/sdk/v8/aether.umd.js"></script>
<script>
  const aether = Aether.default;
  aether.init({ apiKey: 'your-key' });
</script>
```

### CDN Auto-Loader (recommended)

Use the auto-loader for zero-maintenance SDK updates. The loader (~3KB) caches the full SDK bundle in localStorage and automatically fetches new versions in the background:

```html
<script src="https://cdn.aether.network/sdk/v8/loader.js"></script>
<script>
  AetherLoader.load().then(aether => {
    aether.init({ apiKey: 'your-key' });
  });
</script>
```

**Loader options:**

| Option | Default | Description |
|---|---|---|
| `cacheTTL` | `3600000` (1 hour) | How long to use the cached bundle before checking for updates (ms) |
| `version` | `'latest'` | Pin to a specific version (e.g. `'5.1.0'`) or use `'latest'` |
| `timeout` | `10000` | Network timeout for fetching the SDK bundle (ms) |
| `onReady` | -- | Callback invoked when the SDK is loaded: `(sdk) => void` |
| `onError` | -- | Callback invoked on load failure: `(error) => void` |

**Behavior:**
- First load: fetches manifest from CDN, resolves latest version, downloads and caches bundle
- Subsequent loads: serves from localStorage cache immediately, background-checks for updates
- Offline: falls back to cached bundle (even if expired) with a console warning
- No cache + offline: throws error (fires `onError` callback)

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
    intentPrediction: true,        // edge ML intent model
    predictiveAnalytics: true,     // ML prediction event forwarding

    // Web3 — Multi-VM wallet tracking
    walletTracking: true,          // EVM wallet events (MetaMask, Coinbase, etc.)
    svmTracking: true,             // Solana/SVM wallet tracking (Phantom, Solflare)
    bitcoinTracking: true,         // Bitcoin wallet tracking (UniSat, Xverse)
    moveVMTracking: true,          // MoveVM/SUI wallet tracking
    nearTracking: true,            // NEAR wallet tracking
    tronTracking: true,            // TRON/TVM wallet tracking (TronLink)
    cosmosTracking: true,          // Cosmos wallet tracking (Keplr)
    tokenTracking: true,           // ERC-20/SPL token balance tracking
    nftDetection: true,            // NFT ownership detection
    defiTracking: true,            // DeFi protocol interaction tracking
    portfolioTracking: true,       // Cross-chain portfolio aggregation
    walletClassification: true,    // Wallet type classification
    crossChainTracking: true,      // Cross-chain bridge and transfer tracking

    // Web2 Modules
    ecommerce: true,              // e-commerce product/cart/order tracking
    formAnalytics: true,          // field-level form interaction tracking
    featureFlags: true,           // remote feature flag management
    feedback: true,               // NPS/CSAT/CES survey framework
    heatmaps: true,               // click/movement/scroll/attention heatmaps
    funnels: true,                // multi-step conversion funnel tracking
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

  autoUpdate: {
    enabled: true,                 // enable OTA data module updates (default: true)
    checkIntervalMs: 3600000,      // how often to check for updates (default: 1 hour)
    onUpdateAvailable: (version, urgency) => {
      // Called when a new SDK version is available on CDN
      console.log(`Aether SDK v${version} available (${urgency})`);
    },
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
| `hydrateIdentity` | `(data: IdentityData) => void` | Merge anonymous identity with known user data. Accepts `userId`, `traits`, wallet addresses, and chain info across all supported VMs. |
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

### Multi-Chain Web3 Wallet Tracking

```typescript
// EVM wallet connection (MetaMask, Coinbase, Brave, etc.)
aether.wallet.connect('0xabc...def', {
  chainId: 1,
  type: 'metamask',
  ens: 'user.eth',
});

// Solana/SVM wallet connection (Phantom, Solflare)
aether.wallet.connectSVM('7xKX...9mP1', {
  type: 'phantom',
  cluster: 'mainnet-beta',
});

// Bitcoin wallet connection (UniSat, Xverse)
aether.wallet.connectBTC('bc1q...w508d', {
  type: 'unisat',
  network: 'mainnet',
});

// MoveVM/SUI, NEAR, TRON, Cosmos
aether.wallet.connectSUI('0xsui...addr', { type: 'sui-wallet' });
aether.wallet.connectNEAR('user.near', { type: 'near-wallet' });
aether.wallet.connectTRON('T...addr', { type: 'tronlink' });
aether.wallet.connectCosmos('cosmos1...addr', { type: 'keplr' });

// Track a transaction (works across all VMs)
aether.wallet.transaction('0xtxhash...', {
  type: 'swap',
  value: '1.5',
  from: '0xabc...def',
  to: '0x123...789',
  chainId: 1,
  protocol: 'uniswap-v3',        // DeFi protocol tracking
  category: 'dex',               // DeFi category
});

// Get all connected wallets
const wallets = aether.wallet.getWallets();

// Get wallets filtered by VM family
const evmWallets = aether.wallet.getWalletsByVM('evm');
const svmWallets = aether.wallet.getWalletsByVM('svm');

// Cross-chain portfolio aggregation
const portfolio = aether.wallet.getPortfolio();
// => { totalValue, walletCount, chainCount, tokens, defiPositions, ... }

// Wallet classification
const classification = aether.wallet.classifyWallet('0xabc...def');
// => { type: 'hot', confidence: 0.95, labels: ['active-trader', 'defi-user'] }

// Listen for wallet changes (connect/disconnect/chain-switch across all VMs)
const unsub = aether.wallet.onWalletChange((event) => {
  // event.type: 'connect' | 'disconnect' | 'chainChanged' | 'accountChanged'
  // event.vm: 'evm' | 'svm' | 'btc' | 'move' | 'near' | 'tvm' | 'cosmos'
  // event.wallet: WalletInfo
});

// Disconnect all wallets
aether.wallet.disconnect();
```

**Supported VM Families (7):**

| VM Family | Blockchains | Providers |
|-----------|-------------|-----------|
| EVM       | Ethereum, Polygon, Arbitrum, Optimism, BSC, Avalanche, Base | MetaMask, Coinbase, Brave, Ledger, WalletConnect |
| SVM       | Solana | Phantom, Solflare, Backpack |
| Bitcoin   | Bitcoin mainnet, testnet | UniSat, Xverse, Leather |
| MoveVM    | SUI, Aptos | SUI Wallet, Petra |
| NEAR      | NEAR mainnet | NEAR Wallet, MyNearWallet |
| TVM       | TRON | TronLink |
| Cosmos    | Cosmos Hub, Osmosis, Juno | Keplr, Leap |

**DeFi Protocol Tracking (15 categories, 150+ protocols):**

| Category | Protocols |
|----------|-----------|
| DEX | Uniswap, SushiSwap, Curve, Jupiter, Raydium, Orca |
| Lending | AAVE, Compound, MakerDAO, Solend, Marginfi |
| Perpetuals | GMX, dYdX, Drift |
| Staking | Lido, Rocket Pool, Marinade, Jito |
| Bridges | Wormhole, LayerZero, Stargate, Across |
| NFT Marketplaces | OpenSea, Blur, Magic Eden, Tensor |
| Yield | Yearn, Convex, Beefy |
| Governance | Snapshot, Tally |
| Insurance | Nexus Mutual |
| Options | Lyra, Dopex |
| Launchpads | Fjord, Copper Launch |
| Payments | Request Network |
| Restaking | EigenLayer, Symbiotic |
| CEX | Coinbase, Binance |
| Routing | 1inch, Paraswap, CowSwap |

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

### E-commerce Tracking

```typescript
// Track a product view
aether.ecommerce.viewProduct({ id: 'SKU-123', name: 'Widget', price: 29.99, category: 'Tools' });

// Cart operations (persisted to localStorage)
aether.ecommerce.addToCart({ id: 'SKU-123', quantity: 2, price: 29.99 });
aether.ecommerce.removeFromCart('SKU-123');

// Checkout funnel
aether.ecommerce.beginCheckout({ cartValue: 59.98, itemCount: 2 });
aether.ecommerce.purchase({ orderId: 'ORD-789', total: 59.98, currency: 'USD' });

// Refund and coupon tracking
aether.ecommerce.refund({ orderId: 'ORD-789', amount: 29.99, reason: 'defective' });
aether.ecommerce.applyCoupon({ code: 'SAVE20', discount: 11.99 });
```

### Feature Flags

```typescript
// Get a typed feature flag value
const limit = aether.featureFlags.getValue<number>('upload_limit', 10);

// Check a boolean flag
if (aether.featureFlags.isEnabled('new_checkout')) {
  showNewCheckout();
}

// Set local overrides (highest priority)
aether.featureFlags.setOverride('dark_mode', true);
```

### Feedback Surveys

```typescript
// Show an NPS survey (0-10 scale)
aether.feedback.showSurvey({ type: 'nps', trigger: { event: 'purchase_complete' } });

// Show a CSAT survey (1-5 scale)
aether.feedback.showSurvey({ type: 'csat', trigger: { delayMs: 30000 }, sampleRate: 0.1 });

// Programmatically submit a response
aether.feedback.submitResponse({ surveyId: 'srv-1', score: 9, comment: 'Great experience' });
```

### Heatmaps

```typescript
// Start heatmap recording (click, movement, scroll, attention)
aether.heatmaps.start({ types: ['click', 'movement', 'scroll', 'attention'] });

// Stop recording
aether.heatmaps.stop();

// Get aggregated heatmap data for a page
const data = aether.heatmaps.getData('/pricing');
```

### Funnel Tracking

```typescript
// Define and start tracking a funnel
aether.funnels.define({
  id: 'signup-flow',
  steps: ['visit_landing', 'click_signup', 'fill_form', 'verify_email', 'complete'],
  sequential: true,
  timeoutMs: 1800000,
});

// Record a funnel step
aether.funnels.step('signup-flow', 'click_signup');

// Get funnel analysis with drop-off rates
const analysis = aether.funnels.getAnalysis('signup-flow');
```

### Form Analytics

```typescript
// Auto-track all forms on the page (uses MutationObserver for dynamic forms)
aether.formAnalytics.trackAll();

// Track a specific form by selector
aether.formAnalytics.track('#signup-form');

// Get field-level interaction data (focus time, hesitation, corrections)
const stats = aether.formAnalytics.getFieldStats('#signup-form');
```

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

| Directory | File(s) | Responsibility |
|---|---|---|
| `src/core/` | `identity.ts` | Anonymous ID generation, identity merging, cross-subdomain persistence via cookies and localStorage |
| `src/core/` | `session.ts` | Session lifecycle, 30-minute inactivity timeout, heartbeat, page/event counting |
| `src/core/` | `event-queue.ts` | Batching, flush timers, exponential backoff retry, offline localStorage persistence, `sendBeacon` fallback |
| `src/consent/` | `index.ts` | GDPR/CCPA consent state, banner UI rendering, per-purpose grant/revoke, consent-gated event filtering |
| `src/modules/` | `auto-discovery.ts` | Automatic capture of clicks, forms, scroll depth, rage clicks, dead clicks with PII masking |
| `src/modules/` | `performance.ts` | Core Web Vitals collection (LCP, FID, CLS, TTFB, FCP) and global error tracking |
| `src/modules/` | `experiments.ts` | Deterministic A/B variant assignment (FNV-1a hashing), weighted splits, exposure tracking |
| `src/ml/` | `edge-ml.ts` | Browser-side behavioral signal collection, intent prediction, bot detection, session scoring |
| `src/web3/` | `index.ts` | Multi-VM wallet orchestrator, unified wallet interface, connection lifecycle |
| `src/web3/providers/` | `evm-provider.ts`, `svm-provider.ts`, `bitcoin-provider.ts`, `move-provider.ts`, `near-provider.ts`, `tron-provider.ts`, `cosmos-provider.ts` | VM-specific wallet provider adapters for each blockchain family |
| `src/web3/chains/` | `chain-registry.ts`, `evm-chains.ts`, `chain-utils.ts` | Multi-chain registry with 20+ blockchains, chain metadata, and utility functions |
| `src/web3/tracking/` | `evm-tracker.ts`, `svm-tracker.ts`, `btc-tracker.ts`, `move-tracker.ts`, `near-tracker.ts`, `tron-tracker.ts`, `cosmos-tracker.ts` | Per-VM event trackers for transactions, token transfers, and chain-specific events |
| `src/web3/defi/` | `protocol-registry.ts`, `dex-tracker.ts`, `lending-tracker.ts`, `staking-tracker.ts`, `perpetuals-tracker.ts`, `bridge-tracker.ts`, `nft-marketplace-tracker.ts`, + 9 more | DeFi protocol detection and tracking across 15 categories and 150+ protocols |
| `src/web3/wallet/` | `wallet-classifier.ts`, `wallet-labels.ts` | Wallet classification (hot, cold, smart, exchange, protocol, multisig) and behavioral labeling |
| `src/web3/portfolio/` | `portfolio-tracker.ts` | Cross-chain portfolio aggregation, token balances, and DeFi position monitoring |
| `src/context/` | `semantic-context.ts` | 3-tier semantic context collector: Tier 1 (timestamp, event ID, basic device info), Tier 2 (journey stage, screen path, session duration, app state), Tier 3 (inferred intent, sentiment signals, interaction heatmaps, error logs) |
| `src/tracking/` | `traffic-source-tracker.ts` | Zero-config traffic source capture: raw referrer + `referrerDomain` extraction, 5 UTM params, 12 ad click IDs (gclid, msclkid, fbclid, ttclid, twclid, li_fat_id, rdt_cid, scid, dclid, epik, irclickid, aff_id), landing page URL. `sessionStorage`-persisted for SPA navigation. All classification happens server-side via `SourceClassifier` |
| `src/rewards/` | `reward-client.ts` | SDK reward client: eligibility checking, oracle proof retrieval, ABI-encoded on-chain claiming via `claimReward()`, campaign discovery, reward history, localStorage proof caching |
| `src/modules/` | `ecommerce.ts` | Full e-commerce tracking: product views, cart state (Map + localStorage), checkout funnel, purchase, refund, coupon tracking |
| `src/modules/` | `form-analytics.ts` | Field-level form interaction tracking: focus time, hesitation, corrections, abandonment detection, MutationObserver for dynamic forms |
| `src/modules/` | `feature-flags.ts` | Remote feature flag management with stale-while-revalidate caching, overrides > remote > defaults, typed getValue<T>() |
| `src/modules/` | `feedback.ts` | NPS/CSAT/CES survey framework with configurable trigger rules, sample rate, max displays, DOM rendering |
| `src/modules/` | `heatmaps.ts` | Click, movement, scroll, and attention heatmap tracking with IntersectionObserver and grid-based aggregation |
| `src/modules/` | `funnels.ts` | Multi-step funnel tracking with sequential/non-sequential support, timeout handling, drop-off analysis |
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
      update-manager.ts   # OTA data module sync manager
    loader/
      aether-loader.ts    # CDN auto-loader (~3KB)
    context/
      semantic-context.ts # 3-tier semantic context collector
    tracking/
      traffic-source-tracker.ts # Zero-config traffic source auto-detection
    rewards/
      reward-client.ts    # Automated reward pipeline client
    consent/
      index.ts            # GDPR consent module
    modules/
      auto-discovery.ts   # Automatic event capture
      performance.ts      # Core Web Vitals
      experiments.ts      # A/B testing
      ecommerce.ts        # E-commerce product/cart/checkout tracking
      form-analytics.ts   # Field-level form interaction tracking
      feature-flags.ts    # Remote feature flag management
      feedback.ts         # NPS/CSAT/CES survey framework
      heatmaps.ts         # Click/movement/scroll/attention heatmaps
      funnels.ts          # Multi-step conversion funnel tracking
    ml/
      edge-ml.ts          # Browser-side ML predictions
    web3/
      index.ts            # Multi-VM wallet orchestrator
      providers/          # VM-specific wallet provider adapters
        evm-provider.ts   #   EVM (MetaMask, Coinbase, WalletConnect)
        svm-provider.ts   #   Solana (Phantom, Solflare)
        bitcoin-provider.ts # Bitcoin (UniSat, Xverse)
        move-provider.ts  #   MoveVM/SUI (SUI Wallet, Petra)
        near-provider.ts  #   NEAR (NEAR Wallet)
        tron-provider.ts  #   TRON (TronLink)
        cosmos-provider.ts #  Cosmos (Keplr)
      chains/             # Chain registry and utilities
        chain-registry.ts #   20+ blockchain metadata
        evm-chains.ts     #   EVM chain definitions
        chain-utils.ts    #   Chain utility functions
      tracking/           # Per-VM event trackers
        evm-tracker.ts    #   EVM transaction tracking
        svm-tracker.ts    #   Solana transaction tracking
        btc-tracker.ts    #   Bitcoin UTXO tracking
        move-tracker.ts   #   MoveVM transaction tracking
        near-tracker.ts   #   NEAR transaction tracking
        tron-tracker.ts   #   TRON transaction tracking
        cosmos-tracker.ts #   Cosmos transaction tracking
      defi/               # DeFi protocol tracking (15 categories)
        protocol-registry.ts # 150+ protocol definitions
        dex-tracker.ts    #   DEX interactions
        lending-tracker.ts #  Lending protocol tracking
        staking-tracker.ts #  Staking protocol tracking
        perpetuals-tracker.ts # Perpetuals tracking
        bridge-tracker.ts #   Cross-chain bridge tracking
        nft-marketplace-tracker.ts # NFT marketplace tracking
        yield-tracker.ts  #   Yield aggregator tracking
        governance-tracker.ts # Governance tracking
        insurance-tracker.ts # Insurance protocol tracking
        options-tracker.ts #  Options protocol tracking
        launchpad-tracker.ts # Launchpad tracking
        payments-tracker.ts # Payment protocol tracking
        restaking-tracker.ts # Restaking tracking
        cex-tracker.ts    #   CEX integration tracking
        router-tracker.ts #   DEX aggregator/router tracking
      wallet/             # Wallet analysis
        wallet-classifier.ts # Wallet type classification
        wallet-labels.ts  #   Behavioral labeling
      portfolio/          # Cross-chain portfolio
        portfolio-tracker.ts # Portfolio aggregation
    utils/
      index.ts            # Helper functions
  dist/                   # Compiled bundles
  rollup.config.mjs       # Rollup build configuration (main SDK)
  rollup.loader.mjs       # Rollup build configuration (CDN loader)
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
- `window.ethereum` (EVM Web3, optional)
- `window.solana` / `window.phantom` (Solana/SVM, optional)
- `window.unisat` / `window.bitcoin` (Bitcoin, optional)
- `window.suiWallet` (MoveVM/SUI, optional)
- `window.near` (NEAR, optional)
- `window.tronWeb` / `window.tronLink` (TRON/TVM, optional)
- `window.keplr` (Cosmos, optional)
- `PerformanceObserver` (Web Vitals, optional)

---

## Intelligence Graph Events

v8.0 introduces 5 new event types for the Intelligence Graph:

| Event Type | Description | Required Consent |
|---|---|---|
| `agent_task` | AI agent begins or completes a task | `agent` |
| `agent_decision` | AI agent makes an autonomous decision | `agent` |
| `payment` | Fiat or crypto payment recorded | `commerce` |
| `x402_payment` | HTTP 402-based micropayment captured | `commerce` |
| `contract_action` | Smart-contract interaction observed | `web3` |

Two new consent purposes -- `agent` and `commerce` -- join the existing `analytics`, `marketing`, and `web3` purposes. Events are gated by consent like all other event types: if the mapped consent purpose has not been granted, the event is silently dropped at flush time.

---

## License

Proprietary. All rights reserved. See LICENSE for details.
