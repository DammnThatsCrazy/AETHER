# Aether Mobile SDK

The Aether Mobile SDK provides native analytics, identity resolution, multi-chain Web3 wallet tracking, and event tracking for iOS, Android, and React Native applications. It is designed for high-throughput mobile environments with offline support, automatic batching, and GDPR-compliant consent management.

---

## Platform Support

| Platform      | Minimum Version   | SDK Language | File               |
|---------------|-------------------|--------------|--------------------|
| iOS           | 14.0+             | Swift        | `Aether.swift`     |
| Android       | API 21+ (5.0)     | Kotlin       | `Aether.kt`        |
| React Native  | 0.72+             | TypeScript   | `ReactNativeSDK.tsx`|

---

## Features

- **Event tracking** -- custom events, screen views, and conversion tracking
- **Identity resolution** -- seamless anonymous-to-known-user transition
- **Session management** -- automatic session rotation on foreground re-entry
- **GDPR consent management** -- purpose-based consent (analytics, marketing, web3)
- **Multi-chain Web3 wallet tracking** -- 7 VM families (EVM, SVM/Solana, Bitcoin, MoveVM/SUI, NEAR, TVM/TRON, Cosmos) with wallet connect/disconnect, transaction tracking, DeFi interactions, portfolio aggregation, and wallet classification
- **A/B experiment framework** -- variant assignment with persistent bucketing
- **Auto screen tracking** -- automatic view controller / activity tracking
- **Offline event queuing** -- batched delivery with automatic retry on failure
- **Deep link attribution** -- UTM, gclid, fbclid, and msclkid parameter capture
- **Push notification tracking** -- campaign-level open attribution
- **Error tracking** -- uncaught exception capture (Android)
- **Lifecycle tracking** -- foreground/background events with automatic flush
- **Tiered semantic context** -- 3-tier consent-driven context enrichment (Essential → Functional → Rich) automatically attached to every event. Tier 1: timestamp, event ID, basic device info (anonymized). Tier 2: journey stage, screen path, session duration, app state. Tier 3: inferred intent, sentiment signals, error logs
- **OTA data updates** -- automatic over-the-air updates for chain registry, DeFi protocol definitions, wallet labels, and classification rules without requiring app store updates (JSON data modules only, no executable code)

---

## Installation

### iOS -- Swift Package Manager

Add the package dependency in Xcode:

```
File > Add Package Dependencies...
```

Enter the repository URL:

```
https://github.com/aether-network/aether-ios-sdk.git
```

Set the version rule to **5.0.0** or later.

### iOS -- CocoaPods

Add the following to your `Podfile`:

```ruby
pod 'AetherSDK', '~> 5.0'
```

Then run:

```bash
pod install
```

### Android -- Gradle

Add the Aether repository and dependency to your module-level `build.gradle.kts`:

```kotlin
repositories {
    maven { url = uri("https://maven.aether.network/releases") }
}

dependencies {
    implementation("com.aether:sdk-android:5.0.0")
}
```

Minimum SDK requirement in your `build.gradle.kts`:

```kotlin
android {
    defaultConfig {
        minSdk = 21
    }
}
```

### React Native

Install the package via npm or yarn:

```bash
npm install @aether/react-native-sdk
```

```bash
yarn add @aether/react-native-sdk
```

For iOS, install the native CocoaPods dependency:

```bash
cd ios && pod install
```

No additional linking is required for React Native 0.72+.

---

## Quick Start

### iOS (Swift)

```swift
import AetherSDK

// 1. Configure and initialize (typically in AppDelegate or App init)
var config = AetherConfig(apiKey: "your-api-key")
config.environment = .production
config.debug = false
config.modules.screenTracking = true
config.modules.walletTracking = true
config.modules.svmTracking = true       // Solana wallet tracking
config.modules.bitcoinTracking = true   // Bitcoin wallet tracking
config.modules.defiTracking = true      // DeFi protocol tracking
config.modules.portfolioTracking = true // Cross-chain portfolio
config.privacy.gdprMode = true
config.privacy.anonymizeIP = true

Aether.shared.initialize(config: config)

// 2. Track events
Aether.shared.track("button_tapped", properties: [
    "buttonId": AnyCodable("checkout"),
    "screen": AnyCodable("product_detail")
])

// 3. Track screen views manually
Aether.shared.screenView("ProductDetailScreen")

// 4. Track conversions
Aether.shared.conversion("purchase_complete", value: 49.99, properties: [
    "currency": AnyCodable("USD"),
    "itemCount": AnyCodable(3)
])

// 5. Identify a user
Aether.shared.hydrateIdentity(IdentityData(
    userId: "user-12345",
    walletAddress: "0xABC...DEF",
    traits: ["plan": AnyCodable("pro"), "signup_date": AnyCodable("2025-01-15")]
))

// 6. Handle deep links
func application(_ app: UIApplication, open url: URL, options: [UIApplication.OpenURLOptionsKey: Any] = [:]) -> Bool {
    Aether.shared.handleDeepLink(url)
    return true
}

// 7. Track push notification opens
func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
    Aether.shared.trackPushOpened(userInfo: response.notification.request.content.userInfo)
}

// 8. Reset on logout
Aether.shared.reset()
```

### Android (Kotlin)

```kotlin
import com.aether.sdk.*

// 1. Configure and initialize (typically in Application.onCreate)
class MyApp : Application() {
    override fun onCreate() {
        super.onCreate()

        val config = AetherConfig(
            apiKey = "your-api-key",
            environment = AetherConfig.Environment.PRODUCTION,
            debug = false,
            modules = ModuleConfig(
                activityTracking = true,
                walletTracking = true,
                svmTracking = true,          // Solana wallet tracking
                bitcoinTracking = true,      // Bitcoin wallet tracking
                defiTracking = true,         // DeFi protocol tracking
                portfolioTracking = true,    // Cross-chain portfolio
                errorTracking = true
            ),
            privacy = PrivacyConfig(
                gdprMode = true,
                anonymizeIP = true
            )
        )

        Aether.initialize(this, config)
    }
}

// 2. Track events
Aether.track("button_tapped", mapOf(
    "buttonId" to "checkout",
    "screen" to "product_detail"
))

// 3. Track screen views manually
Aether.screenView("ProductDetailScreen")

// 4. Track conversions
Aether.conversion("purchase_complete", value = 49.99, properties = mapOf(
    "currency" to "USD",
    "itemCount" to 3
))

// 5. Identify a user
Aether.hydrateIdentity(IdentityData(
    userId = "user-12345",
    walletAddress = "0xABC...DEF",
    traits = mapOf("plan" to "pro", "signup_date" to "2025-01-15")
))

// 6. Handle deep links
Aether.handleDeepLink("https://app.example.com/promo?utm_source=email&utm_campaign=summer")

// 7. Track push notification opens
Aether.trackPushOpened(remoteMessage.data)

// 8. Reset on logout
Aether.reset()
```

### React Native (TypeScript)

```tsx
import Aether, { AetherProvider, useAether, useIdentity, useExperiment, useScreenTracking } from '@aether/react-native-sdk';

// 1. Wrap your app with the provider
function App() {
  return (
    <AetherProvider config={{
      apiKey: 'your-api-key',
      environment: 'production',
      debug: false,
      modules: {
        screenTracking: true,
        walletTracking: true,
        svmTracking: true,
        bitcoinTracking: true,
        defiTracking: true,
        portfolioTracking: true,
        experiments: true,
      },
      privacy: {
        gdprMode: true,
        anonymizeIP: true,
      },
    }}>
      <MainApp />
    </AetherProvider>
  );
}

// 2. Use hooks in your components
function ProductScreen() {
  const aether = useAether();
  const { identity, hydrate } = useIdentity();
  const variant = useExperiment('checkout_flow', ['control', 'streamlined']);

  // Auto screen tracking via hook
  useScreenTracking('ProductScreen');

  const handlePurchase = () => {
    aether.conversion('purchase_complete', 49.99, {
      currency: 'USD',
      itemCount: 3,
    });
  };

  const handleLogin = () => {
    hydrate({
      userId: 'user-12345',
      walletAddress: '0xABC...DEF',
      traits: { plan: 'pro' },
    });
  };

  return (
    // your component JSX
  );
}

// 3. Direct API usage (outside of React components)
Aether.track('app_opened');
Aether.handleDeepLink('https://app.example.com/promo?utm_source=email');
Aether.trackPushOpened({ campaign_id: 'summer_2025' });

// 4. Multi-chain wallet tracking
Aether.wallet.connect('0xABC...DEF', { type: 'metamask', chainId: 1 });       // EVM
Aether.wallet.connectSVM('7xKX...9mP1', { type: 'phantom' });                 // Solana
Aether.wallet.connectBTC('bc1q...w508d', { type: 'unisat' });                 // Bitcoin
Aether.wallet.connectSUI('0xsui...addr', { type: 'sui-wallet' });             // SUI
Aether.wallet.connectNEAR('user.near', { type: 'near-wallet' });              // NEAR
Aether.wallet.connectTRON('T...addr', { type: 'tronlink' });                  // TRON
Aether.wallet.connectCosmos('cosmos1...addr', { type: 'keplr' });             // Cosmos
Aether.wallet.transaction('0xTXHASH...', { value: '1.5', token: 'ETH', protocol: 'uniswap-v3' });
Aether.wallet.getWallets();                                                    // All connected wallets
Aether.wallet.getWalletsByVM('evm');                                           // Filter by VM
Aether.wallet.getPortfolio();                                                  // Cross-chain portfolio
Aether.wallet.classifyWallet('0xABC...DEF');                                   // Wallet classification
Aether.wallet.disconnect();

// 5. Experiment assignment
const variant = await Aether.experiments.run('onboarding_v2', ['control', 'new_flow']);
const current = await Aether.experiments.getAssignment('onboarding_v2');

// 6. Consent management
const state = await Aether.consent.getState();
Aether.consent.grant(['analytics', 'marketing']);
Aether.consent.revoke(['web3']);

// 7. Reset on logout
Aether.reset();
```

---

## Configuration Reference

### `AetherConfig` / `AetherRNConfig`

| Property         | Type            | Default                          | Description                                      |
|------------------|-----------------|----------------------------------|--------------------------------------------------|
| `apiKey`         | `string`        | **required**                     | Your Aether project API key.                     |
| `environment`    | `enum`          | `production`                     | Target environment: `production`, `staging`, or `development`. |
| `debug`          | `boolean`       | `false`                          | Enable verbose logging to the console.           |
| `endpoint`       | `string`        | `https://api.aether.network`    | API endpoint URL. Override for self-hosted deployments. |
| `batchSize`      | `int`           | `10`                             | Number of events per batch before automatic flush. |
| `flushInterval`  | `double` / `long` | `5.0` (s) / `5000` (ms)       | Interval between automatic flush cycles.         |

### Module Configuration

| Property                | Type      | Default | Description                                     |
|-------------------------|-----------|---------|-------------------------------------------------|
| `screenTracking`        | `boolean` | `true`  | Auto-track screen views via swizzling (iOS) or `ActivityLifecycleCallbacks` (Android). |
| `deepLinkAttribution`   | `boolean` | `true`  | Capture UTM and click-ID parameters from deep links. |
| `pushNotificationTracking` / `pushTracking` | `boolean` | `true` | Enable push notification open tracking. |
| `walletTracking`        | `boolean` | `false` | Enable EVM wallet connection and transaction tracking. |
| `svmTracking`           | `boolean` | `false` | Enable Solana/SVM wallet tracking (Phantom, Solflare). |
| `bitcoinTracking`       | `boolean` | `false` | Enable Bitcoin wallet tracking (UniSat, Xverse). |
| `moveVMTracking`        | `boolean` | `false` | Enable MoveVM/SUI wallet tracking. |
| `nearTracking`          | `boolean` | `false` | Enable NEAR wallet tracking. |
| `tronTracking`          | `boolean` | `false` | Enable TRON/TVM wallet tracking (TronLink). |
| `cosmosTracking`        | `boolean` | `false` | Enable Cosmos wallet tracking (Keplr). |
| `defiTracking`          | `boolean` | `false` | Enable DeFi protocol interaction tracking (150+ protocols). |
| `portfolioTracking`     | `boolean` | `false` | Enable cross-chain portfolio aggregation. |
| `walletClassification`  | `boolean` | `false` | Enable wallet type classification (hot, cold, smart, exchange). |
| `purchaseTracking`      | `boolean` | `true`  | Enable purchase and transaction event tracking.  |
| `errorTracking`         | `boolean` | `true`  | Capture uncaught exceptions (Android).           |
| `experiments`           | `boolean` | `true`  | Enable the A/B experiment framework.             |

### Privacy Configuration

| Property       | Type      | Default | Description                                          |
|----------------|-----------|---------|------------------------------------------------------|
| `gdprMode`     | `boolean` | `false` | When enabled, no events are sent until consent is granted. |
| `anonymizeIP`  | `boolean` | `true`  | Strip the last octet of IP addresses server-side.    |
| `respectATT`   | `boolean` | `true`  | (iOS only) Respect App Tracking Transparency status. |

---

## API Reference

### Core Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `initialize` / `init` | `initialize(config)` | Initialize the SDK. Call once at app startup. |
| `track` | `track(event, properties?)` | Track a custom event with optional properties. |
| `screenView` | `screenView(screenName, properties?)` | Record a screen view event. |
| `conversion` | `conversion(event, value?, properties?)` | Track a conversion event with optional monetary value. |
| `hydrateIdentity` | `hydrateIdentity(data)` | Associate identity data (user ID, wallet, traits) with the current user. Merges with existing traits. |
| `getAnonymousId` | `getAnonymousId() -> string` | Return the persistent anonymous ID for this device. |
| `getUserId` | `getUserId() -> string?` | Return the current identified user ID, or null. |
| `reset` | `reset()` | Clear all identity data, flush pending events, and generate new anonymous and session IDs. Call on user logout. |
| `flush` | `flush()` | Immediately send all queued events to the server. |
| `handleDeepLink` | `handleDeepLink(url)` | Parse a deep link URL and track attribution parameters (UTM, gclid, fbclid, msclkid). |
| `trackPushOpened` | `trackPushOpened(data)` | Track a push notification open event with campaign metadata. |

### Wallet Methods (React Native)

| Method | Signature | Description |
|--------|-----------|-------------|
| `wallet.connect` | `wallet.connect(address, options?)` | Connect an EVM wallet. Options: `type`, `chainId`, `ens`. |
| `wallet.connectSVM` | `wallet.connectSVM(address, options?)` | Connect a Solana/SVM wallet. Options: `type`, `cluster`. |
| `wallet.connectBTC` | `wallet.connectBTC(address, options?)` | Connect a Bitcoin wallet. Options: `type`, `network`. |
| `wallet.connectSUI` | `wallet.connectSUI(address, options?)` | Connect a MoveVM/SUI wallet. |
| `wallet.connectNEAR` | `wallet.connectNEAR(address, options?)` | Connect a NEAR wallet. |
| `wallet.connectTRON` | `wallet.connectTRON(address, options?)` | Connect a TRON wallet. |
| `wallet.connectCosmos` | `wallet.connectCosmos(address, options?)` | Connect a Cosmos wallet. |
| `wallet.disconnect` | `wallet.disconnect()` | Disconnect all wallets and track the event. |
| `wallet.transaction` | `wallet.transaction(txHash, options?)` | Track an on-chain transaction with optional DeFi protocol metadata. |
| `wallet.getWallets` | `wallet.getWallets() -> WalletInfo[]` | Get all connected wallets across all VMs. |
| `wallet.getWalletsByVM` | `wallet.getWalletsByVM(vm) -> WalletInfo[]` | Get connected wallets filtered by VM family. |
| `wallet.getPortfolio` | `wallet.getPortfolio() -> Portfolio` | Get aggregated cross-chain portfolio data. |
| `wallet.classifyWallet` | `wallet.classifyWallet(address) -> Classification` | Classify wallet type (hot, cold, smart, exchange). |
| `wallet.onWalletChange` | `wallet.onWalletChange(callback) -> unsubscribe` | Listen for wallet connect/disconnect/chain changes across all VMs. |

### Experiment Methods (React Native)

| Method | Signature | Description |
|--------|-----------|-------------|
| `experiments.run` | `experiments.run(id, variants) -> Promise<string>` | Run an experiment and return the assigned variant. |
| `experiments.getAssignment` | `experiments.getAssignment(id) -> Promise<string?>` | Get the previously assigned variant for an experiment. |

### Consent Methods (React Native)

| Method | Signature | Description |
|--------|-----------|-------------|
| `consent.getState` | `consent.getState() -> Promise<ConsentState>` | Get the current consent state for all purposes. |
| `consent.grant` | `consent.grant(purposes)` | Grant consent for the specified purposes. Accepts: `analytics`, `marketing`, `web3`. |
| `consent.revoke` | `consent.revoke(purposes)` | Revoke consent for the specified purposes. |

### React Native Hooks

| Hook | Signature | Description |
|------|-----------|-------------|
| `useAether` | `useAether() -> Aether` | Access the Aether SDK instance. |
| `useIdentity` | `useIdentity() -> { identity, hydrate, reset }` | Reactive identity state with hydration and reset helpers. |
| `useExperiment` | `useExperiment(id, variants) -> string \| null` | Run an experiment and reactively return the assigned variant. |
| `useScreenTracking` | `useScreenTracking(screenName)` | Automatically track a screen view when the component mounts or the screen name changes. |
| `useAetherContext` | `useAetherContext() -> { aether, isInitialized }` | Access the Aether context from `AetherProvider`. |

### React Native Components

| Component | Props | Description |
|-----------|-------|-------------|
| `AetherProvider` | `config: AetherRNConfig`, `children: ReactNode` | Context provider that initializes the SDK and exposes it to child components. |

---

## Privacy and Consent

The Aether Mobile SDK provides built-in GDPR consent management with purpose-based controls.

### Consent Purposes

| Purpose      | Description                                              |
|-------------|----------------------------------------------------------|
| `analytics`  | Core analytics events, screen tracking, and session data. |
| `marketing`  | Campaign attribution, deep link tracking, and push notification analytics. |
| `web3`       | Wallet connection events, transaction tracking, and on-chain activity. |

### GDPR Mode

When `gdprMode` is enabled in the privacy configuration, the SDK will not send any events until the user has explicitly granted consent for at least one purpose. Events generated before consent is granted are queued locally and sent once consent is provided.

```swift
// iOS
config.privacy.gdprMode = true
```

```kotlin
// Android
privacy = PrivacyConfig(gdprMode = true)
```

```tsx
// React Native
Aether.consent.grant(['analytics']);           // Grant analytics consent
Aether.consent.revoke(['marketing', 'web3']); // Revoke marketing and web3
const state = await Aether.consent.getState(); // { analytics: true, marketing: false, web3: false }
```

### IP Anonymization

IP anonymization is enabled by default (`anonymizeIP = true`). When active, the server strips the last octet of all collected IP addresses before storage.

### App Tracking Transparency (iOS)

On iOS, when `respectATT` is set to `true` (the default), the SDK checks the App Tracking Transparency authorization status and adjusts data collection accordingly.

---

## Event Batching and Offline Support

Events are queued in memory and sent in configurable batches (default: 10 events per batch). The SDK automatically flushes the queue:

- On a timed interval (default: every 5 seconds)
- When the batch size threshold is reached
- When the app moves to the background
- When the app is about to terminate (iOS)

If a batch fails to send (network error or HTTP 4xx/5xx), the events are re-enqueued and retried on the next flush cycle.

---

## License

Proprietary. All rights reserved.

This software is the confidential property of Aether Network. Unauthorized copying, distribution, or use of this SDK, in whole or in part, is strictly prohibited. Contact [sdk@aether.network](mailto:sdk@aether.network) for licensing inquiries.
