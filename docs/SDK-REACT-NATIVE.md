# Aether React Native SDK v8.7.1 — Integration Guide

## Installation

```bash
npm install @aether/react-native-sdk
# or
yarn add @aether/react-native-sdk
```

### iOS Setup

```bash
cd ios && pod install
```

### Android Setup

No additional setup required — the native module auto-links.

## Quick Start

```tsx
import { AetherProvider } from '@aether/react-native-sdk';

export default function App() {
  return (
    <AetherProvider config={{
      apiKey: 'your-api-key',
      environment: 'production',
    }}>
      <NavigationContainer>
        <AppNavigator />
      </NavigationContainer>
    </AetherProvider>
  );
}
```

## Core API

### Event Tracking

```typescript
import Aether from '@aether/react-native-sdk';

// Custom event
Aether.track('button_tapped', { buttonId: 'cta-hero', screen: 'home' });

// Screen view
Aether.screenView('PricingScreen', { source: 'tab_bar' });

// Conversion
Aether.conversion('purchase_completed', 29.99, { plan: 'pro' });
```

### Identity

```typescript
// Identify user
Aether.hydrateIdentity({
  userId: 'user-123',
  traits: {
    email: 'user@example.com',
    plan: 'enterprise',
  },
});

// Get identity
const identity = await Aether.getIdentity();

// Reset on logout
Aether.reset();
```

### Device Fingerprint

The SDK generates a device fingerprint via the native bridge (`NativeModules.AetherNative.getFingerprint()`), which delegates to the platform-specific implementation (CryptoKit on iOS, MessageDigest on Android). The fingerprint is cached and included in every event context.

```typescript
// Get fingerprint (async, cached after first call)
const fingerprintId = await Aether.getFingerprint();
```

## React Hooks

### useAetherContext

```tsx
import { useAetherContext } from '@aether/react-native-sdk';

function MyComponent() {
  const { aether, isInitialized } = useAetherContext();

  const handlePress = () => {
    aether.track('item_selected', { itemId: '123' });
  };

  return <Button onPress={handlePress} title="Select" />;
}
```

### useIdentity

```tsx
import { useIdentity } from '@aether/react-native-sdk';

function ProfileScreen() {
  const { identity, hydrate, reset } = useIdentity();

  useEffect(() => {
    if (user) {
      hydrate({ userId: user.id, traits: { name: user.name } });
    }
  }, [user]);

  return <Text>ID: {identity?.anonymousId}</Text>;
}
```

### useScreenTracking

```tsx
import { useScreenTracking } from '@aether/react-native-sdk';

function SettingsScreen() {
  useScreenTracking('SettingsScreen');
  // Automatically tracks screen view on mount

  return <View>...</View>;
}
```

## Wallet Tracking

```typescript
// Wallet connected
Aether.wallet.connect('0x1234...abcd', {
  type: 'metamask',
  chainId: 1,
});

// Wallet disconnected
Aether.wallet.disconnect();

// Transaction
Aether.wallet.transaction('0xabc123...', {
  chainId: 1,
  value: '1.5',
  token: 'ETH',
});
```

## Consent Management

```typescript
// Grant consent
Aether.consent.grant(['analytics', 'marketing']);

// Revoke consent
Aether.consent.revoke(['marketing']);

// Get state
const state = await Aether.consent.getState();
```

## Ecommerce

```typescript
// Product view
Aether.ecommerce.trackProductView({
  id: 'sku-001', name: 'Widget Pro', price: 29.99
});

// Add to cart
Aether.ecommerce.trackAddToCart({
  productId: 'sku-001', quantity: 2, price: 29.99
});

// Purchase
Aether.ecommerce.trackPurchase({
  orderId: 'order-456', total: 29.99, currency: 'USD',
  items: [{ productId: 'sku-001', quantity: 1, price: 29.99 }]
});
```

## Feature Flags

```typescript
// Check flag
const enabled = await Aether.featureFlag.isEnabled('dark-mode');

// Get value
const flag = await Aether.featureFlag.getFlag('upload-limit');

// Force refresh
await Aether.featureFlag.refresh();
```

## Feedback / Surveys

Survey definitions come from the backend. The SDK provides methods to register and display them.

```typescript
// Register a survey (definitions come from backend)
Aether.feedback.registerSurvey(surveyConfig, { event: 'purchase_completed' });

// Submit response
Aether.feedback.submitResponse('survey-123', {
  answers: { q1: 9, q2: 'Great experience!' }
});
```

## Deep Links

```typescript
import { Linking } from 'react-native';

// Handle deep links
Linking.addEventListener('url', ({ url }) => {
  Aether.handleDeepLink(url);
});

// Handle initial URL
const initialUrl = await Linking.getInitialURL();
if (initialUrl) Aether.handleDeepLink(initialUrl);
```

## Push Notifications

```typescript
// When notification is opened
Aether.trackPushOpened({
  campaignId: notification.data.campaign_id,
  messageId: notification.data.message_id,
});
```

## Configuration Reference

```typescript
interface AetherRNConfig {
  apiKey: string;
  environment?: 'production' | 'staging' | 'development';
  endpoint?: string;           // Default: 'https://api.aether.io'
  debug?: boolean;
  modules?: {
    screenTracking?: boolean;  // Auto screen tracking
    deepLinkAttribution?: boolean;
    pushTracking?: boolean;
    walletTracking?: boolean;
    experiments?: boolean;     // Removed in v7.0 — use feature flags
  };
  privacy?: {
    gdprMode?: boolean;
    anonymizeIP?: boolean;
  };
}
```

## Architecture

```
React Components / Hooks
        │
    AetherProvider (init + cleanup)
        │
    ├── Aether singleton (JS)
    │       │
    │   NativeModules.AetherNative (bridge to iOS/Android)
    │       │
    │   Native Event Queue + Batch Flush + Device Fingerprint
    │       │
    │   POST /v1/batch → Aether Backend
    │
    ├── Semantic Context (Tier 1 only)
    │       │
    │   {device, viewport, locale, timezone, sessionId}
    │
    └── Module Bridges (pure delegation)
        ├── Ecommerce → RNEcommerce
        ├── FeatureFlags → RNFeatureFlags
        └── Feedback → RNFeedback
```

### What changed in v7.0:
- **Removed**: OTA Update Manager (361 lines) — backend serves config via `GET /v1/config`
- **Removed**: Semantic Context Tiers 2 & 3 — backend handles enrichment
- **Added**: Device fingerprint via native bridge (`getFingerprint()`)
- **Added**: Server config fetch on init
- **Kept**: All NativeModules bridges (zero JS processing)
- **Kept**: React hooks (useIdentity, useScreenTracking)

### v7.0 Size:
- **Before**: 1,064 LOC across 6 files
- **After**: 497 LOC across 5 files (53% reduction)
