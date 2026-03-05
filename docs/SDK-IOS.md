# Aether iOS SDK v7.0.0 — Integration Guide

## Installation

### Swift Package Manager (recommended)

Add to your `Package.swift`:

```swift
dependencies: [
    .package(url: "https://github.com/AetherSDK/aether-ios.git", from: "7.0.0")
]
```

Or in Xcode: File > Add Packages > enter the repository URL.

### CocoaPods

```ruby
pod 'AetherSDK', '~> 7.0'
```

## Quick Start

```swift
import AetherSDK

// In AppDelegate.application(_:didFinishLaunchingWithOptions:)
Aether.shared.initialize(config: AetherConfig(
    apiKey: "your-api-key",
    environment: .production,
    modules: ModuleConfig(screenTracking: true),
    privacy: PrivacyConfig(gdprMode: true, anonymizeIP: true)
))
```

## Core API

### Event Tracking

```swift
// Custom event
Aether.shared.track("button_tapped", properties: [
    "buttonId": "cta-hero",
    "screen": "home"
])

// Screen view (auto-tracked if screenTracking enabled)
Aether.shared.screenView("PricingScreen", properties: [
    "source": "navigation"
])

// Conversion
Aether.shared.conversion("purchase_completed", value: 29.99, properties: [
    "plan": "pro",
    "currency": "USD"
])
```

### Identity

```swift
// Identify user with traits
Aether.shared.hydrateIdentity(IdentityData(
    userId: "user-123",
    traits: [
        "email": "user@example.com",
        "plan": "enterprise"
    ]
))

// Get anonymous ID
let anonId = Aether.shared.getAnonymousId()

// Reset on logout
Aether.shared.reset()
```

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
    properties: ["token": "ETH"]
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
    "id": "sku-001",
    "name": "Widget Pro",
    "price": 29.99,
    "category": "tools"
])

// Add to cart
Aether.shared.trackAddToCart([
    "productId": "sku-001",
    "quantity": 2,
    "price": 29.99
])

// Purchase
Aether.shared.trackPurchase(
    orderId: "order-456",
    total: 29.99,
    currency: "USD",
    items: [
        ["productId": "sku-001", "quantity": 1, "price": 29.99]
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
    var walletTracking: Bool = true
    var purchaseTracking: Bool = true
    var errorTracking: Bool = true
    var experiments: Bool = false
}

struct PrivacyConfig {
    var gdprMode: Bool = false                   // Require consent before tracking
    var anonymizeIP: Bool = true                 // Hash IP addresses
    var respectATT: Bool = true                  // Respect App Tracking Transparency
}
```

## Architecture

The iOS SDK follows a **"Sense and Ship"** architecture:

```
UIKit Events / Wallet Interactions
        |
    Raw Events (screen views, taps, wallet connects)
        |
    Serial Dispatch Queue (thread-safe event buffering)
        |
    Timer-based batch flush (every 5 seconds)
        |
    POST /v1/batch -> Aether Backend
```

### What the SDK sends:
- Event type, name, and raw properties
- Minimal context: `{os: "iOS", osVersion, locale, timezone}`
- Session ID, anonymous ID, user ID
- SDK version identifier

### What the backend derives:
- Device model, screen size from User-Agent
- Traffic source classification
- ML predictions (intent, bot detection)
- Feature flag evaluation
- Funnel matching

## Auto Screen Tracking

When `screenTracking` is enabled, the SDK uses method swizzling on `UIViewController.viewDidAppear(_:)` to automatically track screen views. System view controllers (prefixed with `UI`, `_`, `SFSafari`) are filtered out.

To disable for a specific controller, override the class name check or disable `screenTracking` in config.

## Thread Safety

All event operations are dispatched to a private serial queue (`DispatchQueue(label: "io.aether.sdk")`). The SDK is safe to call from any thread.

## Data Persistence

- **Anonymous ID** and **User ID** are persisted in `UserDefaults` under `aether_` prefix
- **Event queue** is in-memory only (flushed on background/termination)
- No keychain usage in the base SDK
