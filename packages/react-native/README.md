# @aether/react-native

<!-- Badges -->
![Version](https://img.shields.io/badge/version-4.0.0-blue)
![TypeScript](https://img.shields.io/badge/TypeScript-strict-3178C6)
![Platform](https://img.shields.io/badge/platform-iOS%20%7C%20Android-lightgrey)
![License](https://img.shields.io/badge/license-proprietary-lightgrey)

**React Native bridge to the Aether native iOS and Android SDKs.** Track events, resolve identities, manage consent, monitor Web3 wallets, run A/B experiments, and capture screen views -- all through a unified JavaScript API backed by native Swift and Kotlin modules.

---

## Features

- **Event tracking** -- custom events, screen views, and conversions with arbitrary properties
- **Identity resolution** -- anonymous-to-known user merging with reactive hooks for identity changes
- **Session management** -- automatic session lifecycle handled by the underlying native SDKs
- **Consent management** -- per-purpose grant/revoke for analytics, marketing, and Web3 categories
- **Web3 wallet tracking** -- wallet connect/disconnect, on-chain transaction tracking, and multi-chain support
- **A/B experiments** -- deterministic variant assignment with async hooks for React components
- **Auto-screen tracking** -- declarative `useScreenTracking` hook for React Navigation integration
- **Deep link attribution** -- pass deep link URLs to the native attribution engine
- **Push notification tracking** -- record push-opened events from notification payloads
- **React context and hooks** -- `AetherProvider`, `useAether`, `useIdentity`, `useExperiment`, and `useScreenTracking`
- **Native performance** -- all heavy lifting runs in native Swift (iOS) and Kotlin (Android) for minimal JS thread overhead

---

## Requirements

| Dependency | Minimum Version |
|---|---|
| React | >= 18.0 |
| React Native | >= 0.72 |
| iOS Deployment Target | 14.0 |
| Android `minSdkVersion` | 21 |
| Android `compileSdkVersion` | 34 |

---

## Installation

### 1. Install the package

```bash
npm install @aether/react-native
```

```bash
yarn add @aether/react-native
```

```bash
pnpm add @aether/react-native
```

### 2. iOS -- install CocoaPods dependencies

```bash
cd ios && pod install && cd ..
```

The podspec declares a dependency on `AetherSDK ~> 4.0`, which CocoaPods will resolve automatically.

### 3. Android -- Gradle

No manual configuration is required. The library's `build.gradle` is picked up automatically by React Native auto-linking. Rebuild your project after installation:

```bash
npx react-native run-android
```

> **Note:** If your project does not use React Native auto-linking (versions < 0.72), you must manually register `AetherPackage` in your `MainApplication.kt` or `MainApplication.java`. See [Manual Android Setup](#manual-android-setup) below.

---

## Quick Start

Wrap your app in `AetherProvider` and start tracking:

```tsx
import React from 'react';
import { AetherProvider } from '@aether/react-native';
import App from './App';

export default function Root() {
  return (
    <AetherProvider
      config={{
        apiKey: 'your-api-key',
        environment: 'production',
      }}
    >
      <App />
    </AetherProvider>
  );
}
```

Then use the SDK anywhere in your component tree:

```tsx
import { useAether, useIdentity, useScreenTracking } from '@aether/react-native';

function HomeScreen() {
  const aether = useAether();
  const { identity, hydrate } = useIdentity();

  // Automatically track this screen view
  useScreenTracking('HomeScreen');

  const handleSignIn = (user) => {
    hydrate({
      userId: user.id,
      traits: { email: user.email, plan: user.plan },
    });
  };

  const handlePurchase = (order) => {
    aether.conversion('purchase', order.total, {
      orderId: order.id,
      currency: 'USD',
    });
  };

  return (
    // ...
  );
}
```

---

## Configuration

Pass an `AetherRNConfig` object to `AetherProvider` or call `Aether.init()` directly. Only `apiKey` is required.

```typescript
import Aether from '@aether/react-native';

Aether.init({
  apiKey: 'your-api-key',
  environment: 'production',       // 'production' | 'staging' | 'development'
  endpoint: 'https://api.aether.network', // custom endpoint
  debug: false,                    // enable native debug logging

  modules: {
    screenTracking: true,          // automatic activity/screen tracking (native)
    deepLinkAttribution: true,     // deep link attribution engine
    pushTracking: true,            // push notification open tracking
    walletTracking: false,         // Web3 wallet event tracking
    experiments: true,             // A/B experiment framework
  },

  privacy: {
    gdprMode: false,               // require consent before tracking
    anonymizeIP: true,             // strip last octet from IP addresses
  },
});
```

---

## API Reference

### Core Methods

| Method | Signature | Description |
|---|---|---|
| `init` | `(config: AetherRNConfig) => void` | Initialize the SDK. Must be called before any other method. Handled automatically by `AetherProvider`. |
| `track` | `(event: string, properties?: Record<string, unknown>) => void` | Track a custom event with optional properties. |
| `screenView` | `(screenName: string, properties?: Record<string, unknown>) => void` | Record a screen view event. |
| `conversion` | `(event: string, value?: number, properties?: Record<string, unknown>) => void` | Track a conversion event with optional monetary value. |
| `hydrateIdentity` | `(data: IdentityData) => void` | Merge anonymous identity with known user data. Accepts `userId`, `walletAddress`, `walletType`, `chainId`, and `traits`. |
| `getIdentity` | `() => Promise<Identity>` | Return the current identity object asynchronously from the native layer. |
| `reset` | `() => void` | Clear identity, session, and experiment data. Creates a fresh anonymous identity. |
| `flush` | `() => void` | Send all queued events to the server immediately. |
| `handleDeepLink` | `(url: string) => void` | Pass a deep link URL to the native attribution engine. |
| `trackPushOpened` | `(data: Record<string, string>) => void` | Record a push notification open event from the notification payload. |

### Wallet Methods

| Method | Signature | Description |
|---|---|---|
| `wallet.connect` | `(address: string, options?: { type?: string; chainId?: number }) => void` | Register a wallet connection with optional wallet type and chain ID. |
| `wallet.disconnect` | `() => void` | Record a wallet disconnection event. |
| `wallet.transaction` | `(txHash: string, options?: Record<string, unknown>) => void` | Track an on-chain transaction by hash with optional metadata. |

### Experiment Methods

| Method | Signature | Description |
|---|---|---|
| `experiments.run` | `(id: string, variants: string[]) => Promise<string>` | Run an experiment and return the assigned variant. Assignment is deterministic based on the anonymous ID. |
| `experiments.getAssignment` | `(id: string) => Promise<string \| null>` | Retrieve an existing experiment assignment without triggering a new one. |

### Consent Methods

| Method | Signature | Description |
|---|---|---|
| `consent.getState` | `() => Promise<{ analytics: boolean; marketing: boolean; web3: boolean }>` | Get the current consent state from the native layer. |
| `consent.grant` | `(purposes: string[]) => void` | Grant consent for the specified purposes (e.g., `['analytics', 'marketing']`). |
| `consent.revoke` | `(purposes: string[]) => void` | Revoke consent for the specified purposes. |

---

## React Hooks

### `useAether()`

Returns the core `Aether` SDK object for imperative calls.

```tsx
const aether = useAether();
aether.track('item_added', { sku: 'ABC-123' });
```

### `useIdentity()`

Reactive hook that subscribes to identity changes via the native event emitter. Returns the current identity, a `hydrate` function, and a `reset` function.

```tsx
const { identity, hydrate, reset } = useIdentity();

// identity.anonymousId -- always present
// identity.userId      -- set after hydration
// identity.traits      -- user traits dictionary
```

### `useExperiment(id, variants)`

Runs an experiment on mount and returns the assigned variant (or `null` while loading).

```tsx
const variant = useExperiment('onboarding-v2', ['control', 'streamlined']);

if (variant === 'streamlined') {
  return <StreamlinedOnboarding />;
}
return <DefaultOnboarding />;
```

### `useScreenTracking(screenName)`

Fires a `screenView` event when the component mounts or when `screenName` changes. Ideal for use inside screen components with React Navigation.

```tsx
function ProfileScreen() {
  useScreenTracking('ProfileScreen');
  return <Profile />;
}
```

### `useAetherContext()`

Access the context value provided by `AetherProvider`, including the SDK instance and initialization state.

```tsx
const { aether, isInitialized } = useAetherContext();
```

---

## Context Provider

`AetherProvider` initializes the SDK and makes it available to all descendant components via React context. Place it at the root of your component tree.

```tsx
import { AetherProvider } from '@aether/react-native';

function Root() {
  return (
    <AetherProvider
      config={{
        apiKey: 'your-api-key',
        environment: 'production',
        modules: { walletTracking: true },
        privacy: { gdprMode: true, anonymizeIP: true },
      }}
    >
      <App />
    </AetherProvider>
  );
}
```

The provider re-initializes only when `apiKey` changes.

---

## Platform Setup

### iOS

The podspec (`aether-react-native.podspec`) declares a dependency on `AetherSDK ~> 4.0` and targets iOS 14.0+. After installing the npm package:

```bash
cd ios && pod install
```

No additional configuration is needed. The native module (`AetherNativeModule.swift`) bridges to `Aether.shared` from the core iOS SDK.

**Deep linking:** To capture deep links for attribution, forward URLs from your `AppDelegate` or `SceneDelegate`:

```swift
// AppDelegate.swift
func application(_ app: UIApplication,
                 open url: URL,
                 options: [UIApplication.OpenURLOptionsKey: Any] = [:]) -> Bool {
    // Aether handles attribution automatically via the native SDK
    return true
}
```

### Android

The library targets `minSdkVersion 21` and `compileSdkVersion 34`. React Native auto-linking registers `AetherPackage` automatically.

Rebuild after installation:

```bash
npx react-native run-android
```

#### Manual Android Setup

If auto-linking is not available, register the package manually:

```kotlin
// MainApplication.kt
import com.aether.reactnative.AetherPackage

class MainApplication : Application(), ReactApplication {
    override fun getPackages(): List<ReactPackage> {
        val packages = PackageList(this).packages.toMutableList()
        packages.add(AetherPackage())
        return packages
    }
}
```

**Deep linking:** Configure intent filters in `AndroidManifest.xml` as you normally would. Pass the URL to `Aether.handleDeepLink()` from your React Native deep link handler:

```tsx
import { Linking } from 'react-native';
import Aether from '@aether/react-native';

Linking.addEventListener('url', ({ url }) => {
  Aether.handleDeepLink(url);
});
```

---

## TypeScript

The package ships with full TypeScript definitions. All public types are exported from the main entry point:

```typescript
import type {
  AetherRNConfig,
  Identity,
  IdentityData,
} from '@aether/react-native';
```

---

## Project Structure

```
packages/react-native/
  src/
    index.tsx                  # Unified JS API, hooks, and context provider
  ios/
    AetherNativeModule.swift   # Swift bridge to AetherSDK (iOS)
    AetherNativeModule.m       # Objective-C extern declarations for React Native
  android/
    src/main/java/com/aether/reactnative/
      AetherNativeModule.kt    # Kotlin bridge to Aether SDK (Android)
      AetherPackage.kt         # React Native package registration
    build.gradle               # Android library build configuration
  aether-react-native.podspec  # CocoaPods spec for iOS
  package.json
  tsconfig.json
```

---

## License

Proprietary. All rights reserved. See LICENSE for details.
