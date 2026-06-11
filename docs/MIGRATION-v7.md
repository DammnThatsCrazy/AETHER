---
title: SDK Migration Guide — v6.x to v7.0
slug: sdks/migration-v7
section: sdks
visibility: P
audience: [dev-junior, dev-senior]
status: deprecated
since_version: "8.8.0"
source_files:
  - packages/shared/schema-version.ts
canonical_owner: sdk@aether
estimated_read_minutes: 8
toc_depth: 3
last_synced_commit: af65923
---
# Migration Guide: Aether SDK v6.x to v7.0.0

## Overview

v7.0.0 is a major architectural shift from a **"fat client"** to a **"thin client"** (Sense and Ship). The SDK no longer performs processing, ML inference, or data classification client-side. All computation moves to the Aether backend. v7.0 also introduces cross-device identity resolution via device fingerprinting and a graph-based resolution engine.

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
  walletTracking: true,      // EVM wallets
  svmTracking: true,         // Solana wallets
  bitcoinTracking: true,     // Bitcoin wallets
  // ... etc per VM family
}
```

#### Removed Types

```typescript
// These TypeScript types are removed from the SDK:
IntentVector, BotScore, BehaviorSignature, SessionScore,
ExperimentConfig, ExperimentAssignment, ExperimentInterface,
PerformanceEvent
```

#### New: Identity Resolution Signals

```typescript
// v7.0 — hydrateIdentity() now accepts cross-device resolution signals
aether.hydrateIdentity({
  userId: 'user-123',
  traits: { name: 'Jane' },
  email: 'jane@example.com',       // NEW: deterministic cross-device link
  phone: '+14155551234',            // NEW: deterministic cross-device link
  oauthProvider: 'google',          // NEW: OAuth-based linking
  oauthSubject: 'google-uid-xyz',   // NEW: OAuth subject ID
});
```

#### New: Device Fingerprinting

The SDK now automatically generates a SHA-256 device fingerprint from 17 browser signals. The fingerprint is included in every event's `context.fingerprint.id` and is used by the backend for probabilistic identity resolution.

- Web: Canvas, WebGL, audio, fonts, screen, timezone, language, platform, hardware
- iOS: identifierForVendor, device model, screen, locale, timezone, processor count, memory
- Android: ANDROID_ID, Build.MODEL, display metrics, locale, timezone, processors
- React Native: Delegates to native module

#### Simplified Modules

**Ecommerce** — Cart state management removed:
```typescript
// v6.x
aether.ecommerce.addToCart(item);
aether.ecommerce.getCart(); // removed
aether.ecommerce.calculateTotal(); // removed

// v7.0
aether.ecommerce.trackAddToCart(item);
// Cart state managed by your app or backend
```

**Heatmaps** — Grid building removed. SDK ships raw coordinates only.
**Funnels** — Client-side matching removed. Funnels defined in dashboard, matched server-side.
**Feature Flags** — Local evaluation removed. Flags evaluated server-side, cached locally.
**Form Analytics** — Hesitation detection removed. SDK ships raw field events.
**Traffic Source** — Client-side classification removed. SDK ships raw UTM/referrer/click IDs.

### iOS SDK

#### Updated Context

```swift
// v6.x — SDK sent device model, screen size, etc.
// v7.0 — SDK sends only: os, osVersion, locale, timezone
// Backend derives device details from HTTP headers
```

#### New: Device Fingerprint

```swift
// Automatically generated on initialize() via CryptoKit SHA-256
// Included in every event's context.fingerprint.id
```

#### New Methods Added

```swift
// Wallet tracking
Aether.shared.walletConnected(address:walletType:chainId:)
Aether.shared.walletDisconnected(address:)
Aether.shared.walletTransaction(txHash:chainId:value:properties:)

// Consent management
Aether.shared.grantConsent(categories:)
Aether.shared.revokeConsent(categories:)
Aether.shared.getConsentState()

// Ecommerce
Aether.shared.trackProductView(_:)
Aether.shared.trackAddToCart(_:)
Aether.shared.trackPurchase(orderId:total:currency:items:)

// Feature flags
Aether.shared.isFeatureEnabled(_:default:)
Aether.shared.getFeatureValue(_:default:)
```

### Android SDK

Same changes as iOS — new wallet, consent, ecommerce, feature flag methods, and device fingerprinting. Device context slimmed to minimal fields.

### React Native SDK

#### Removed Modules

```typescript
// v6.x
import { OTAUpdateManager } from '@aether/react-native-sdk';
OTAUpdateManager.syncDataModules(); // removed

// v7.0 — Config fetched automatically from GET /v1/config
```

#### New: Device Fingerprint

```typescript
// Bridge to native fingerprint via NativeModules
const fingerprintId = await Aether.getFingerprint();
```

#### Simplified Semantic Context

```typescript
// v6.x — 3-tier context with sentiment analysis
semanticContext.collect(); // returned Tier 1 + 2 + 3

// v7.0 — Tier 1 only (device, viewport, session)
semanticContext.collect(); // returns minimal context
// Backend handles Tier 2/3 enrichment
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

### 4. Add Identity Resolution Signals (Optional)

Pass `email`, `phone`, `oauthProvider`, `oauthSubject` to `hydrateIdentity()` to enable cross-device identity resolution:

```typescript
aether.hydrateIdentity({
  userId: 'user-123',
  email: 'user@example.com',
  phone: '+14155551234',
});
```

### 5. Update Ecommerce Calls

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

### 6. External Tools for Removed Features

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
| `POST /v1/batch` | iOS, Android, React Native | Batched events |
| `POST /v1/tx/enrich` | Web SDK | Transaction classification |
| `POST /v1/predict` | Optional | ML inference |
| `GET /v1/rewards/{id}/eligibility` | Web SDK | Reward checks |
| `GET /v1/rewards/{id}/payload` | Web SDK | Claim payloads |
| `POST /v1/rewards/{id}/claim` | Web SDK | Claim submission |
| `GET /v1/resolution/cluster/{user_id}` | Admin dashboard | Identity clusters |
| `GET /v1/resolution/pending` | Admin dashboard | Pending merges |
