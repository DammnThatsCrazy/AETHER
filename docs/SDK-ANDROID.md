# Aether Android SDK v7.0.0 — Integration Guide

## Installation

### Gradle (Kotlin DSL)

```kotlin
// build.gradle.kts
dependencies {
    implementation("io.aether:sdk-android:7.0.0")
}
```

### Gradle (Groovy)

```groovy
// build.gradle
implementation 'io.aether:sdk-android:7.0.0'
```

## Quick Start

```kotlin
import com.aether.sdk.Aether
import com.aether.sdk.AetherConfig
import com.aether.sdk.ModuleConfig

// In Application.onCreate()
class MyApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Aether.initialize(this, AetherConfig(
            apiKey = "your-api-key",
            environment = AetherConfig.Environment.PRODUCTION,
            modules = ModuleConfig(activityTracking = true),
            debug = false
        ))
    }
}
```

## Core API

### Event Tracking

```kotlin
// Custom event
Aether.track("button_clicked", mapOf(
    "buttonId" to "cta-hero",
    "screen" to "home"
))

// Screen view (auto-tracked if activityTracking enabled)
Aether.screenView("PricingActivity", mapOf(
    "source" to "navigation"
))

// Conversion
Aether.conversion("purchase_completed", 29.99, mapOf(
    "plan" to "pro",
    "currency" to "USD"
))
```

### Identity

```kotlin
// Identify user
Aether.hydrateIdentity(IdentityData(
    userId = "user-123",
    traits = mapOf(
        "email" to "user@example.com",
        "plan" to "enterprise"
    )
))

// Get anonymous ID
val anonId = Aether.getAnonymousId()

// Reset on logout
Aether.reset()
```

## Wallet Tracking

```kotlin
// Wallet connected
Aether.walletConnected(
    address = "0x1234...abcd",
    walletType = "metamask",
    chainId = "eip155:1"
)

// Wallet disconnected
Aether.walletDisconnected(address = "0x1234...abcd")

// Transaction sent
Aether.walletTransaction(
    txHash = "0xabc123...",
    chainId = "eip155:1",
    value = "1.5",
    properties = mapOf("token" to "ETH")
)
```

## Consent Management

```kotlin
// Grant consent
Aether.grantConsent(listOf("analytics", "marketing"))

// Revoke consent
Aether.revokeConsent(listOf("marketing"))

// Check current state
val state = Aether.getConsentState() // ["analytics"]
```

## Ecommerce

```kotlin
// Product view
Aether.trackProductView(mapOf(
    "id" to "sku-001",
    "name" to "Widget Pro",
    "price" to 29.99,
    "category" to "tools"
))

// Add to cart
Aether.trackAddToCart(mapOf(
    "productId" to "sku-001",
    "quantity" to 2,
    "price" to 29.99
))

// Purchase
Aether.trackPurchase(
    orderId = "order-456",
    total = 29.99,
    currency = "USD",
    items = listOf(
        mapOf("productId" to "sku-001", "quantity" to 1, "price" to 29.99)
    )
)
```

## Feature Flags

Feature flags are fetched from the server on initialization and cached locally.

```kotlin
// Boolean check
if (Aether.isFeatureEnabled("dark-mode")) {
    enableDarkMode()
}

// Get value with default
val limit = Aether.getFeatureValue("upload-limit", default = 10)
```

## Deep Link Attribution

```kotlin
// In Activity.onCreate() or onNewIntent()
override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    intent?.data?.let { uri ->
        Aether.handleDeepLink(uri.toString())
    }
}
```

## Push Notification Tracking

```kotlin
// In FirebaseMessagingService or notification click handler
override fun onMessageReceived(message: RemoteMessage) {
    Aether.trackPushOpened(message.data)
}
```

## Configuration Reference

```kotlin
data class AetherConfig(
    val apiKey: String,
    val environment: Environment = Environment.PRODUCTION,
    val debug: Boolean = false,
    val endpoint: String = "https://api.aether.io",
    val modules: ModuleConfig = ModuleConfig(),
    val privacy: PrivacyConfig = PrivacyConfig(),
    val batchSize: Int = 10,
    val flushIntervalSeconds: Long = 5
) {
    enum class Environment { PRODUCTION, STAGING, DEVELOPMENT }
}

data class ModuleConfig(
    val activityTracking: Boolean = true,
    val deepLinkAttribution: Boolean = true,
    val pushTracking: Boolean = true,
    val walletTracking: Boolean = true,
    val purchaseTracking: Boolean = true,
    val errorTracking: Boolean = true,
    val experiments: Boolean = false
)

data class PrivacyConfig(
    val gdprMode: Boolean = false,
    val anonymizeIP: Boolean = true
)
```

## Architecture

The Android SDK follows a **"Sense and Ship"** architecture:

```
Activity Lifecycle / User Interactions
        |
    Raw Events (screen views, taps, wallet connects)
        |
    ConcurrentLinkedQueue (thread-safe event buffer)
        |
    Coroutine-based batch flush (every 5 seconds)
        |
    POST /v1/batch -> Aether Backend
```

### What the SDK sends:
- Event type, name, and raw properties
- Minimal context: `{os: "Android", osVersion, locale, timezone}`
- Session ID, anonymous ID, user ID
- SDK version identifier

### What the backend derives:
- Device model, manufacturer, screen size from User-Agent
- Traffic source classification
- ML predictions (intent, bot detection)
- Feature flag evaluation
- Funnel matching

## Auto Activity Tracking

When `activityTracking` is enabled, the SDK registers an `Application.ActivityLifecycleCallbacks` to automatically track Activity changes via `onActivityResumed()`. The activity's class simple name is used as the screen name.

## Lifecycle Integration

The SDK integrates with `ProcessLifecycleOwner` to:
- Emit `app_foreground` / `app_background` events
- Start new sessions on foreground
- Flush events on background

## Error Tracking

When `errorTracking` is enabled, the SDK installs a global `Thread.UncaughtExceptionHandler` that:
- Captures the stack trace (truncated to 2000 chars)
- Enqueues an error event
- Forwards to the default handler

## Thread Safety

- Event queue uses `ConcurrentLinkedQueue` (lock-free, thread-safe)
- Network operations run on `Dispatchers.IO` coroutine scope
- SharedPreferences access is atomic

## Data Persistence

- **Anonymous ID** and **User ID** persisted in `SharedPreferences` under `aether_prefs`
- **Event queue** is in-memory only (flushed on background/termination)
- **Server config** cached in memory (refreshed on each app launch)
