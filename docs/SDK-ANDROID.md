# Aether Android SDK v8.7.1 — Integration Guide

## Installation

### Gradle (Kotlin DSL)

```kotlin
// build.gradle.kts
dependencies {
    implementation("io.aether:sdk-android:8.3.1")
}
```

### Gradle (Groovy)

```groovy
// build.gradle
implementation 'io.aether:sdk-android:8.3.1'
```

## Quick Start

```kotlin
import com.aether.sdk.Aether
import com.aether.sdk.AetherConfig

// In Application.onCreate()
class MyApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Aether.initialize(this, AetherConfig(apiKey = "your-api-key"))
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

### Device Fingerprint

The SDK automatically generates a SHA-256 device fingerprint on initialization from: `ANDROID_ID`, `Build.MODEL`, `Build.MANUFACTURER`, OS version, display metrics (width, height, density), locale, timezone, and available processors (via `MessageDigest`).

The fingerprint is included in every event's `context.fingerprint.id`. Only the composite hash is sent — raw device signals are never transmitted.

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

The SDK captures **12 ad platform click IDs** and all UTM parameters from deep links, storing them as campaign context that is included in every subsequent event via `buildContext()`.

**Supported click IDs:** `gclid`, `msclkid`, `fbclid`, `ttclid`, `twclid`, `li_fat_id`, `rdt_cid`, `scid`, `dclid`, `epik`, `irclickid`, `aff_id`

**Campaign context fields:** `source`, `medium`, `campaign`, `content`, `term`, `clickIds` (JSONObject), `referrerDomain`

All classification (organic, paid, social, email, direct) happens server-side via the backend `SourceClassifier` — the SDK ships raw signals only.

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
    val batchSize: Int = 10,
    val flushIntervalMs: Long = 5000L,
    val modules: ModuleConfig = ModuleConfig(),
    val privacy: PrivacyConfig = PrivacyConfig()
) {
    enum class Environment { PRODUCTION, STAGING, DEVELOPMENT }
}

data class ModuleConfig(
    val activityTracking: Boolean = true,      // Auto-track Activity changes
    val deepLinkAttribution: Boolean = true,
    val pushTracking: Boolean = true,
    val walletTracking: Boolean = false,       // Wallet event tracking
    val purchaseTracking: Boolean = true,
    val errorTracking: Boolean = true,
    val experiments: Boolean = false            // Removed in v7.0 — use feature flags
)

data class PrivacyConfig(
    val gdprMode: Boolean = false,             // Require consent before tracking
    val anonymizeIP: Boolean = true             // Hash IP addresses
)
```

## Architecture

```
Activity Lifecycle / User Interactions
        │
    Raw Events (screen views, taps, wallet connects)
        │
    Device Fingerprint (SHA-256 via MessageDigest)
        │
    ConcurrentLinkedQueue (thread-safe event buffer)
        │
    Coroutine-based batch flush (every 5 seconds)
        │
    POST /v1/batch → Aether Backend
```

### What the SDK sends:
- Event type, name, and raw properties
- Minimal context: `{os: "Android", osVersion, locale, timezone}`
- Device fingerprint hash
- Campaign context: `{source, medium, campaign, content, term, clickIds, referrerDomain}` (from deep links)
- Session ID, anonymous ID, user ID

### What the backend derives:
- Device model, manufacturer, screen size from User-Agent
- IP geolocation (MaxMind GeoLite2)
- Identity resolution (cross-device matching)
- Traffic source classification (via `SourceClassifier` — 40+ social, 17+ search, 14 email domain tables)
- ML predictions (intent, bot detection)

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

- **Anonymous ID** and **User ID** persisted in `SharedPreferences` under `com.aether.sdk`
- **Device fingerprint** is generated on each init (deterministic — same result for same device)
- **Event queue** is in-memory only (flushed on background/termination)
- **Server config** cached in memory (refreshed on each app launch)
