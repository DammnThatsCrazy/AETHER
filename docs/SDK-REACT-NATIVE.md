# Aether React Native SDK v7.0.0 — Integration Guide

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
import { AetherProvider, Aether } from '@aether/react-native-sdk';

export default function App() {
  return (
    <AetherProvider config={{
      apiKey: 'your-api-key',
      environment: 'production',
      debug: false,
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
import { Aether } from '@aether/react-native-sdk';

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

## React Hooks

### useAether

```tsx
import { useAetherContext } from '@aether/react-native-sdk';

function MyComponent() {
  const { track, identify, isInitialized } = useAetherContext();

  const handlePress = () => {
    track('item_selected', { itemId: '123' });
  };

  return <Button onPress={handlePress} title="Select" />;
}
```

### useIdentity

```tsx
import { useIdentity } from '@aether/react-native-sdk';

function ProfileScreen() {
  const { identity, hydrate } = useIdentity();

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

### useExperiment

```tsx
import { useExperiment } from '@aether/react-native-sdk';

function FeatureComponent() {
  const variant = useExperiment('new-checkout-flow');

  if (variant === 'treatment') {
    return <NewCheckoutFlow />;
  }
  return <OldCheckoutFlow />;
}
```

## Wallet Tracking

```typescript
// Wallet connected
Aether.wallet.connect('0x1234...abcd', {
  walletType: 'metamask',
  chainId: 1,
});

// Wallet disconnected
Aether.wallet.disconnect('0x1234...abcd');

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
import { RNEcommerce } from '@aether/react-native-sdk';

// Initialize (done automatically via AetherProvider)
RNEcommerce.initialize({ onTrack: Aether.track });

// Product view
RNEcommerce.productViewed({
  id: 'sku-001', name: 'Widget Pro', price: 29.99
});

// Add to cart
RNEcommerce.addToCart({
  productId: 'sku-001', quantity: 2, price: 29.99
});

// Purchase
RNEcommerce.orderCompleted({
  orderId: 'order-456', total: 29.99, currency: 'USD',
  items: [{ productId: 'sku-001', quantity: 1, price: 29.99 }]
});
```

## Feature Flags

```typescript
import { RNFeatureFlags } from '@aether/react-native-sdk';

// Check flag
const enabled = await RNFeatureFlags.isEnabled('dark-mode');

// Get value
const flag = await RNFeatureFlags.getFlag('upload-limit');

// Force refresh
await RNFeatureFlags.refresh();

// Local override (for testing)
await RNFeatureFlags.setOverride('dark-mode', true);
await RNFeatureFlags.clearOverride('dark-mode');
```

## Feedback / Surveys

```typescript
import { RNFeedback } from '@aether/react-native-sdk';

// Register a survey (definitions come from backend)
RNFeedback.registerSurvey(surveyConfig, { event: 'purchase_completed' });

// Check if survey should show
const shouldShow = await RNFeedback.shouldShowSurvey('survey-123');

// Submit response
RNFeedback.submitResponse('survey-123', {
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
  endpoint?: string;           // Custom API endpoint
  debug?: boolean;             // Enable debug logging
  batchSize?: number;          // Events per batch (default: 10)
  flushInterval?: number;      // Flush interval in ms (default: 5000)
  modules?: {
    ecommerce?: boolean;
    featureFlags?: boolean;
    feedback?: boolean;
    web3?: boolean;
  };
}
```

## Architecture

The React Native SDK follows a **"Sense and Ship"** architecture with native bridge delegation:

```
React Components / Hooks
        |
    AetherProvider (init + cleanup)
        |
    +-- Aether singleton (JS)
    |       |
    |   NativeModules.AetherNative (bridge to iOS/Android)
    |       |
    |   Native Event Queue + Batch Flush
    |       |
    |   POST /v1/batch -> Aether Backend
    |
    +-- Semantic Context (Tier 1 only)
    |       |
    |   {os, osVersion, viewport, locale, timezone, sessionId}
    |
    +-- Module Bridges (pure delegation)
        +-- Ecommerce -> NativeModules.AetherEcommerce
        +-- FeatureFlags -> NativeModules.AetherFeatureFlags
        +-- Feedback -> NativeModules.AetherFeedback
```

### What changed in v7.0:
- **Removed**: OTA Update Manager (361 lines) — backend serves config
- **Removed**: Semantic Context Tiers 2 & 3 — backend handles enrichment
- **Removed**: Survey factory methods — backend defines surveys
- **Kept**: All NativeModules bridges (zero JS processing)
- **Kept**: React hooks (useIdentity, useExperiment, useScreenTracking)
- **Added**: Server config fetch on init via `GET /v1/config`

### v7.0 Size:
- **Before**: 1,064 LOC across 6 files
- **After**: 497 LOC across 5 files (53% reduction)
