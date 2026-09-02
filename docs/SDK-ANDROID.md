---
title: Aether Android SDK — Integration Guide
slug: sdks/android
section: sdks
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "8.9.0"
source_files:
  - packages/android/src/main/java/com/aether/sdk/Aether.kt
  - packages/shared/events.ts
  - packages/shared/consent.ts
canonical_owner: sdk@aether
estimated_read_minutes: 10
toc_depth: 3
last_synced_commit: "4e6fdad"
---

# Aether Android SDK v8.12.0 — Integration Guide

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

`track()` is for **custom application events** — it ships as top-level type
`track` with the name in `properties.event`. To emit a **canonical backend
event type** directly, use `observe()` (unknown types are a production-safe
no-op; payloads asserting `execution_by_aether == true` are rejected — Aether
observes, it never executes).

```kotlin
// Custom event
Aether.track("button_clicked", mapOf(
    "buttonId" to "cta-hero",
    "screen" to "home"
))

// Canonical low-level observation (registry event types only)
Aether.observe("order_completed", mapOf("orderId" to "ord_1", "total" to 42.0))

// Current local queue depth
val depth = Aether.queueDepth()

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

The fingerprint is stamped as `context.fingerprint.id` — but stamping is
**consent-gated in GDPR mode**: until `analytics` consent is granted, the
fingerprint is omitted from event context (and from identity-resolve calls).
Only the composite hash is sent — raw device signals are never transmitted.

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

The platform's canonical consent registry
(`packages/shared/contracts/consent-registry.json`) defines **12 purposes**:
base purposes `analytics`, `marketing`, `personalization`, `web3`, `agent`,
`commerce`, plus explicit opt-in purposes `financial_activity`, `credit`,
`location`, `economic_observability`, `cross_chain_observability`, and
`fraud_prevention`, which always require separate opt-in and are never granted
by an accept-all path. Present each explicit opt-in purpose as a separate
consent choice in your UI.

The Android runtime exposes `canonicalConsentPurposes` (8 purposes, listed
below) with `explicitOptInPurposes = ["credit", "location"]`; the extended
purposes `financial_activity`, `economic_observability`, and
`cross_chain_observability` are used by the event gating map and stamped into
per-event `context.consent` for web ConsentState parity. The registry's
`fraud_prevention` purpose is not yet surfaced by the Android runtime lists
(grant it via `grantConsent` if your integration collects fraud-prevention
signals; it is never included in `grantAll()`).

```kotlin
// Grant specific purposes
Aether.grantConsent(listOf("analytics", "marketing"))

// Grant all non-explicit-opt-in purposes (excludes credit and location)
Aether.grantAll()

// Explicitly grant credit after showing separate consent UI
Aether.grantConsent(listOf("credit"))

// Revoke consent
Aether.revokeConsent(listOf("marketing"))

// Check current state
val state = Aether.getConsentState() // ["analytics", ...]

// Runtime canonical purposes
val purposes = Aether.canonicalConsentPurposes
// ["analytics", "marketing", "personalization", "web3", "agent", "commerce", "credit", "location"]
```

### Consent receipts

```kotlin
// Build a deterministic canonical receipt locally
val receipt = Aether.buildCanonicalConsentReceipt(input)

// Build AND persist it to the backend (POST /v1/consent/records); suspend fun
val recorded = Aether.recordConsentReceipt(input)
```

`tenantId` is required and must match the tenant resolved from the configured
API key; `subjectId` or `anonymousId` and at least one purpose are required.

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

Every attribution entry point is routed through the **canonical
acquisition-evidence parser** (shared `AcquisitionEvidence` schema v3): the URL
is sanitized, `entryMethod` and `destinationDomain` are set, and first-touch +
latest-touch evidence records are persisted. The active (unexpired)
latest-touch evidence rides on every event as `context.acquisitionEvidence`.
A deep link's host is the **destination** domain and is never written to
`referrerDomain` — `referrerDomain` is only populated from a real external
referrer (`Intent.EXTRA_REFERRER`).

All classification (organic, paid, social, email, direct) happens server-side via the backend `SourceClassifier` — the SDK ships raw signals only.

```kotlin
// In Activity.onCreate() — https links are recorded as verified-capable
// Android App Links ("android_app_link"); custom schemes as
// "manual_sdk_evidence"
override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    intent?.data?.let { uri ->
        Aether.handleDeepLink(uri.toString())
    }
}

// Warm-start deep links (singleTop / singleTask activities)
override fun onNewIntent(intent: Intent?) {
    super.onNewIntent(intent)
    Aether.onNewIntent(intent)
}

// QR codes the host app has already decoded (SDK never touches the camera).
// Parsed with entry method "qr_code"; emits qr_code_scanned.
Aether.handleQrScanResult(decodedUrl)

// NFC tag URIs the host app has already read (SDK never drives the radio).
// Parsed with entry method "nfc"; emits nfc_tag_read.
Aether.handleNfcUri(decodedUri)

// Stored evidence accessors (shared schema v3), null when absent/expired
val first = Aether.getFirstTouchAttribution()
val latest = Aether.getLatestTouchAttribution()
```

**Install referrer:** on first launch the SDK connects to the Play Install
Referrer API (when eligible) and routes the install referrer string through the
same canonical evidence parser, so install-time attribution and deep-link
attribution share one pipeline.

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
    val privacy: PrivacyConfig = PrivacyConfig(),
    val manifestVerificationKey: String? = null, // HMAC-SHA256 secret; when set,
                                             // unsigned/invalid remote manifests
                                             // are rejected (last-known-good kept)
    val autoResumeJourney: Boolean = true,   // Call /sdk/identity/resolve on init
    val onJourneyResumed:                    // Fires once when a prior session is matched
        ((resolvedAnonymousId: String, resolvedUserId: String?) -> Unit)? = null
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
    val experiments: Boolean = false,           // Removed in v7.0 — use feature flags
    val attributionEvidenceTtlDays: Int = 30    // First/latest-touch evidence TTL
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

### What the SDK sends (event context):
- Event type, name, and raw properties (sensitive fields scrubbed recursively,
  including nested maps/lists)
- `os` `{name: "Android", version, sdkInt}` and `device` `{manufacturer, model}`
- `locale`, `timezone`, plus temporal provenance captured at the event's
  occurrence instant: `utcOffsetMinutes` (zone-at-instant, DST-correct),
  `timeZoneSource: "device"`, `clockSource: "device"`
- `network.type`, `library` `{name: "aether-android", version}`
- Device fingerprint hash (consent-gated in GDPR mode)
- Campaign context `{source, medium, campaign, content, term, clickIds, referrerDomain}` and active `acquisitionEvidence` (schema v3)
- Active journey snapshot (`journeyId`/`journeyName`/`journeyType`) on every event
- Per-purpose `consent` booleans and a monotonic per-session
  `sequence.event` counter (reset on session rotation) for gap/reorder
  detection at ingest
- Session ID, anonymous ID, user ID

> Note: unlike the web/server SDKs, the Android SDK does not yet stamp the
> canonical envelope `context.surface` / `context.schemaVersion` fields;
> envelope population parity is limited to `sequence`, `os`, and journey
> context.

### What the backend derives:
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
- **Event queue** is persisted to `filesDir/aether_queue.json` (file-based, capped at 1000 events; flushed on foreground)
- **Server config** cached in memory (refreshed on each app launch)

## Health Agent

The health agent starts automatically after `initialize()`. It:
- POSTs a signed heartbeat to `/v1/diagnostics/sdk/heartbeat` every 60 seconds
- Fetches the remote manifest from `/v1/config/sdk/manifest` every 5 minutes
- Both are fire-and-forget; gated on analytics consent in GDPR mode (it starts
  when `analytics` is granted post-init)
- Applies the verified manifest natively: `rollout_percentage` gates event
  sampling and `features` merge into feature-flag resolution (previously the
  manifest was fetched and verified but never applied)

## Granular Agent Lifecycle Emitters

```kotlin
Aether.agentRegistered(agentId, properties)
Aether.agentTaskCreated(taskId, actorId, properties)
Aether.agentTaskCompleted(taskId, properties)
Aether.agentTaskFailed(taskId, reason, properties)
Aether.agentEscalatedToHuman(taskId, reason, properties)
Aether.agentOutcomeRecorded(taskId, outcome, properties)
// ... 13 more — see AetherHealthAgent for full list
```

## x402 Lifecycle Emitters

```kotlin
Aether.x402ResourceRequested(resourceId, properties)
Aether.x402PaymentRequired(resourceId, amount, currency, properties)
Aether.x402PaymentSettled(paymentId, properties)
Aether.x402AccessGranted(resourceId, properties)
// ... 10 more
```

## Rewards Emitters

```kotlin
Aether.rewardActionQueued(campaignId, ruleId, properties)
Aether.rewardProofGenerated(campaignId, proofId, properties)
Aether.rewardDelivered(campaignId, rewardId, properties)
Aether.rewardClaimSubmitted(campaignId, claimId, properties)
```

## Ecommerce Additions (8.9.0)

```kotlin
Aether.trackRemoveFromCart(mapOf("productId" to "sku-001", "quantity" to 1))
Aether.trackApplyCoupon(couponCode, properties)
Aether.trackBeginCheckout(cartValue, currency = "USD", properties)
```

## Payments & WalletConnect helpers

```kotlin
// status: "initiated" | "completed" | "failed" → payment_* canonical events
Aether.trackGooglePayPayment(status = "completed", amount = 29.99, currency = "USD")

// After a WalletConnect v2 session is established or resumed
Aether.trackWalletConnectSession(topic, address, chainId)
```

## UI Interaction Instrumentation

Native UI interaction capture (spec §12) emits the canonical
`ui_interaction_observed` event (`analytics` consent) through the shared
`observe()` path via the `AetherInteraction` / `AetherInteractionCompose`
helpers (View and Jetpack Compose). Interactions without a stable control ID
are dropped rather than emitted unlabeled. Related canonical event types
`qr_code_scanned`, `nfc_tag_read`, and `app_clip_invoked` are registered under
`analytics` consent.

## Journeys

Journey lifecycle parity with the web SDK: `startJourney`, `pauseJourney`,
`resumeJourney`, `continueJourney`, `checkpointJourney`, `completeJourney`,
`abandonJourney`, `getCurrentJourney`. The active journey snapshot is stamped
on every event's context.

## Reward Event Types (A6)

Four reward lifecycle events are supported via `Aether.track()`:

| Event type | When to emit |
|---|---|
| `reward_action_queued` | When a reward action has been queued for the user |
| `reward_proof_generated` | When an on-chain claim proof is ready for wallet submission |
| `reward_delivered` | When the tenant system confirms reward delivery |
| `reward_claim_submitted` | When the user submits a claim (on-chain or off-chain) |

Emit using `Aether.track()` with `campaignId`, `ruleId`, and `rewardIdempotencyKey` in properties. These events flow through `POST /v1/batch` and are processed by the reward eligibility pipeline on the backend. The SDK does not evaluate eligibility — that is handled server-side by the Aether reward policy engine.
