# Aether iOS SDK v8.7.1 — Integration Guide

## Installation

### Swift Package Manager (recommended)

Add to your `Package.swift`:

```swift
dependencies: [
    .package(url: "https://github.com/AetherSDK/aether-ios.git", from: "8.3.1")
]
```

Or in Xcode: File > Add Packages > enter the repository URL.

### CocoaPods

```ruby
pod 'AetherSDK', '~> 8.0'
```

## Quick Start

```swift
import AetherSDK

// In AppDelegate.application(_:didFinishLaunchingWithOptions:)
Aether.shared.initialize(config: AetherConfig(apiKey: "your-api-key"))
```

## Core API

### Event Tracking

```swift
// Custom event
Aether.shared.track("button_tapped", properties: [
    "buttonId": AnyCodable("cta-hero"),
    "screen": AnyCodable("home")
])

// Screen view (auto-tracked if screenTracking enabled)
Aether.shared.screenView("PricingScreen", properties: [
    "source": AnyCodable("navigation")
])

// Conversion
Aether.shared.conversion("purchase_completed", value: 29.99, properties: [
    "plan": AnyCodable("pro"),
    "currency": AnyCodable("USD")
])
```

### Identity

```swift
// Identify user with traits
Aether.shared.hydrateIdentity(IdentityData(
    userId: "user-123",
    traits: [
        "email": AnyCodable("user@example.com"),
        "plan": AnyCodable("enterprise")
    ]
))

// Get anonymous ID
let anonId = Aether.shared.getAnonymousId()

// Reset on logout
Aether.shared.reset()
```

### Device Fingerprint

The SDK automatically generates a SHA-256 device fingerprint on initialization from: `identifierForVendor`, device model, system version, screen dimensions, scale, locale, timezone, processor count, and physical memory (via CryptoKit).

The fingerprint is included in every event's `context.fingerprint.id`. Only the composite hash is sent — raw device signals are never transmitted.

## Wallet Tracking

```swift
// Wallet connected
Aether.shared.walletConnected(
    address: "0x1234...abcd",
    walletType: "metamask",
    chainId: "eip155:1"
)

// Wallet disconnected
Aether.shared.walletDisconnected(address: "0x1234...abcd")

// Transaction sent
Aether.shared.walletTransaction(
    txHash: "0xabc123...",
    chainId: "eip155:1",
    value: "1.5",
    properties: ["token": AnyCodable("ETH")]
)
```

## Consent Management

```swift
// Grant consent
Aether.shared.grantConsent(categories: ["analytics", "marketing"])

// Revoke consent
Aether.shared.revokeConsent(categories: ["marketing"])

// Check current state
let state = Aether.shared.getConsentState() // ["analytics"]
```

## Ecommerce

```swift
// Product view
Aether.shared.trackProductView([
    "id": AnyCodable("sku-001"),
    "name": AnyCodable("Widget Pro"),
    "price": AnyCodable(29.99),
    "category": AnyCodable("tools")
])

// Add to cart
Aether.shared.trackAddToCart([
    "productId": AnyCodable("sku-001"),
    "quantity": AnyCodable(2),
    "price": AnyCodable(29.99)
])

// Purchase
Aether.shared.trackPurchase(
    orderId: "order-456",
    total: 29.99,
    currency: "USD",
    items: [
        ["productId": AnyCodable("sku-001"), "quantity": AnyCodable(1), "price": AnyCodable(29.99)]
    ]
)
```

## Feature Flags

Feature flags are fetched from the server on initialization and cached locally.

```swift
// Boolean check
if Aether.shared.isFeatureEnabled("dark-mode") {
    enableDarkMode()
}

// Get value with default
let limit = Aether.shared.getFeatureValue("upload-limit", default: 10)
```

## Deep Link Attribution

The SDK captures **12 ad platform click IDs** and all UTM parameters from deep links, storing them as campaign context that is included in every subsequent event via `buildContext()`.

**Supported click IDs:** `gclid`, `msclkid`, `fbclid`, `ttclid`, `twclid`, `li_fat_id`, `rdt_cid`, `scid`, `dclid`, `epik`, `irclickid`, `aff_id`

**Campaign context fields:** `source`, `medium`, `campaign`, `content`, `term`, `clickIds` (dictionary), `referrerDomain`

All classification (organic, paid, social, email, direct) happens server-side via the backend `SourceClassifier` — the SDK ships raw signals only.

```swift
// In SceneDelegate or AppDelegate
func scene(_ scene: UIScene, openURLContexts contexts: Set<UIOpenURLContext>) {
    if let url = contexts.first?.url {
        Aether.shared.handleDeepLink(url)
    }
}
```

## Push Notification Tracking

```swift
// In UNUserNotificationCenterDelegate
func userNotificationCenter(_ center: UNUserNotificationCenter,
                          didReceive response: UNNotificationResponse,
                          withCompletionHandler completionHandler: @escaping () -> Void) {
    Aether.shared.trackPushOpened(userInfo: response.notification.request.content.userInfo)
    completionHandler()
}
```

## Configuration Reference

```swift
struct AetherConfig {
    let apiKey: String
    var environment: Environment = .production   // .production, .staging, .development
    var debug: Bool = false                      // Console logging
    var endpoint: String = "https://api.aether.io"
    var modules: ModuleConfig = ModuleConfig()
    var privacy: PrivacyConfig = PrivacyConfig()
    var batchSize: Int = 10                      // Events per batch
    var flushInterval: TimeInterval = 5.0        // Seconds between flushes
}

struct ModuleConfig {
    var screenTracking: Bool = true              // Auto-track UIViewController appearances
    var deepLinkAttribution: Bool = true
    var pushNotificationTracking: Bool = true
    var walletTracking: Bool = true              // Wallet event tracking
    var purchaseTracking: Bool = true
    var errorTracking: Bool = true
    var experiments: Bool = false                 // Removed in v7.0 — use feature flags
}

struct PrivacyConfig {
    var gdprMode: Bool = false                   // Require consent before tracking
    var anonymizeIP: Bool = true                 // Hash IP addresses
    var respectATT: Bool = true                  // Respect App Tracking Transparency
}
```

## Architecture

```
UIKit Events / Wallet Interactions
        │
    Raw Events (screen views, taps, wallet connects)
        │
    Device Fingerprint (SHA-256 via CryptoKit)
        │
    Serial Dispatch Queue (thread-safe event buffering)
        │
    Timer-based batch flush (every 5 seconds)
        │
    POST /v1/batch → Aether Backend
```

### What the SDK sends:
- Event type, name, and raw properties
- Minimal context: `{os: "iOS", osVersion, locale, timezone}`
- Device fingerprint hash
- Campaign context: `{source, medium, campaign, content, term, clickIds, referrerDomain}` (from deep links)
- Session ID, anonymous ID, user ID

### What the backend derives:
- Device model, screen size from User-Agent
- IP geolocation (MaxMind GeoLite2)
- Identity resolution (cross-device matching)
- Traffic source classification (via `SourceClassifier` — 40+ social, 17+ search, 14 email domain tables)
- ML predictions (intent, bot detection)

## Auto Screen Tracking

When `screenTracking` is enabled, the SDK uses method swizzling on `UIViewController.viewDidAppear(_:)` to automatically track screen views. System view controllers (prefixed with `UI`, `_`, `NS`) are filtered out.

## Thread Safety

All event operations are dispatched to a private serial queue (`DispatchQueue(label: "com.aether.sdk.serial")`). The SDK is safe to call from any thread.

## Data Persistence

- **Anonymous ID** and **User ID** are persisted in `UserDefaults` under `com.aether.sdk` suite
- **Device fingerprint** is generated on each init (deterministic — same result for same device)
- **Event queue** is in-memory only (flushed on background/termination)
- **Server config** cached in memory (refreshed on each app launch)
