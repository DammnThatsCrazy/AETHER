# Migration Guide: Aether SDK v6.x to v7.0.0

## Overview

v7.0.0 is a major architectural shift from a **"fat client"** to a **"thin client"** (Sense and Ship). The SDK no longer performs processing, ML inference, or data classification client-side. All computation moves to the Aether backend.

## Breaking Changes

### Web SDK

#### Removed Modules

| Module | Replacement |
|---|---|
| `aether.experiments.run()` | Use `aether.featureFlag.isEnabled()` |
| `aether.onIntentPrediction()` | Backend ML via `POST /v1/predict` |
| `aether.onBotDetection()` | Backend ML via `POST /v1/predict` |
| `aether.onSessionScore()` | Backend ML via `POST /v1/predict` |
| `aether.feedback.registerSurvey()` | Backend-rendered surveys (iframe) |
| `aether.wallet.getPortfolio()` | Backend aggregation API |
| `aether.wallet.classifyWallet()` | Backend via `GET /v1/wallet-label/{addr}` |

#### Removed Config Options

```typescript
// v6.x (removed)
modules: {
  intentPrediction: true,     // removed
  experiments: true,           // removed — use featureFlags
  performanceTracking: true,   // removed — use Sentry/DataDog
  predictiveAnalytics: true,   // removed
  rageClickDetection: true,    // removed — backend detects
  deadClickDetection: true,    // removed — backend detects
}

// v7.0 (new)
modules: {
  autoDiscovery: true,
  ecommerce: true,
  featureFlags: true,
  heatmaps: true,
  funnels: true,
  formAnalytics: true,
  web3: true,
}
```

#### Removed Types

```typescript
// These TypeScript types are removed from the SDK:
IntentVector, BotScore, BehaviorSignature, SessionScore,
ExperimentConfig, ExperimentAssignment, ExperimentInterface,
PerformanceEvent
```

#### Simplified Modules

**Ecommerce** — Cart state management removed. Use:
```typescript
// v6.x
aether.ecommerce.addToCart(item);
aether.ecommerce.getCart(); // removed
aether.ecommerce.calculateTotal(); // removed

// v7.0
aether.ecommerce.trackAddToCart(item);
// Cart state and totals managed by your app or backend
```

**Heatmaps** — Grid building removed. SDK now ships raw coordinates only.

**Funnels** — Client-side funnel matching removed. Funnels are defined in the Aether dashboard and matched server-side.

**Feature Flags** — Local evaluation logic removed. Flags are evaluated server-side and cached locally.

**Form Analytics** — Hesitation detection and abandonment analysis removed. SDK ships raw field events.

**Traffic Source** — Client-side classification removed. SDK ships raw UTM/referrer/click IDs.

### iOS SDK

#### Updated Context

```swift
// v6.x — SDK sent device model, screen size, etc.
// v7.0 — SDK sends only: os, osVersion, locale, timezone
// Backend derives device details from HTTP headers
```

#### New Methods Added

```swift
// Wallet tracking (new in v7.0)
Aether.shared.walletConnected(address:walletType:chainId:)
Aether.shared.walletDisconnected(address:)
Aether.shared.walletTransaction(txHash:chainId:value:properties:)

// Consent management (new in v7.0)
Aether.shared.grantConsent(categories:)
Aether.shared.revokeConsent(categories:)
Aether.shared.getConsentState()

// Ecommerce (new in v7.0)
Aether.shared.trackProductView(_:)
Aether.shared.trackAddToCart(_:)
Aether.shared.trackPurchase(orderId:total:currency:items:)

// Feature flags (new in v7.0)
Aether.shared.isFeatureEnabled(_:default:)
Aether.shared.getFeatureValue(_:default:)
```

### Android SDK

Same changes as iOS — new wallet, consent, ecommerce, and feature flag methods. Device context slimmed to minimal fields.

### React Native SDK

#### Removed Modules

```typescript
// v6.x
import { OTAUpdateManager } from '@aether/react-native-sdk';
OTAUpdateManager.syncDataModules(); // removed

// v7.0 — Config fetched automatically from GET /v1/config
```

#### Simplified Semantic Context

```typescript
// v6.x — 3-tier context with sentiment analysis
semanticContext.collect(); // returned Tier 1 + 2 + 3

// v7.0 — Tier 1 only (device, viewport, session)
semanticContext.collect(); // returns minimal context
// Backend handles Tier 2/3 enrichment
```

#### Removed Survey Factories

```typescript
// v6.x
RNFeedback.createNPS('How likely...', 'Any feedback?');
RNFeedback.createCSAT('How satisfied...', { min: 1, max: 5 });
RNFeedback.createCES('How easy...', { min: 1, max: 7 });

// v7.0 — Survey definitions come from backend
// Use RNFeedback.registerSurvey(backendSurveyConfig) instead
```

## Migration Steps

### 1. Update Dependencies

```bash
# Web
npm install @aether/web-sdk@7.0.0

# React Native
npm install @aether/react-native-sdk@7.0.0

# iOS — update Package.swift or Podfile
# Android — update build.gradle
```

### 2. Update Config

Remove deprecated module flags and add new ones (see config changes above).

### 3. Replace Removed APIs

- `experiments.run()` -> `featureFlag.isEnabled()`
- `onIntentPrediction()` -> Use backend webhook or dashboard
- `feedback.registerSurvey()` -> Configure surveys in dashboard
- `wallet.getPortfolio()` -> Use backend portfolio API
- `wallet.classifyWallet()` -> Use backend wallet label API

### 4. Update Ecommerce Calls

Rename methods and remove any cart state management that relied on SDK:

```typescript
// v6.x
aether.ecommerce.productViewed(product);
aether.ecommerce.addToCart(item);
aether.ecommerce.orderCompleted(order);

// v7.0
aether.ecommerce.trackProductView(product);
aether.ecommerce.trackAddToCart(item);
aether.ecommerce.trackPurchase(order);
```

### 5. External Tools for Removed Features

| Removed Feature | Recommended Alternative |
|---|---|
| Web Vitals / Performance | Sentry, DataDog, Vercel Analytics |
| A/B Experiments | Feature flags module (built-in) or LaunchDarkly |
| Survey Rendering | Aether dashboard (backend-rendered) or Typeform |
| ML Intent Prediction | Backend `/v1/predict` endpoint |

## Backend Requirements

v7.0 SDKs require the following backend endpoints (deploy before upgrading):

| Endpoint | Required By | Purpose |
|---|---|---|
| `GET /v1/config` | All SDKs | Init config, feature flags |
| `POST /v1/events` | Web SDK | Batched events |
| `POST /v1/tx/enrich` | Web SDK | Transaction classification |
| `POST /v1/predict` | Optional | ML inference |
| `GET /v1/rewards/{id}/eligibility` | Web SDK | Reward checks |
| `GET /v1/rewards/{id}/payload` | Web SDK | Claim payloads |
| `POST /v1/rewards/{id}/claim` | Web SDK | Claim submission |
