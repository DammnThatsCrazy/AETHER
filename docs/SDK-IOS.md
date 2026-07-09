---
title: Aether iOS SDK — Integration Guide
slug: sdks/ios
section: sdks
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "8.9.0"
source_files:
  - packages/ios/Sources/AetherSDK/Aether.swift
  - packages/shared/events.ts
  - packages/shared/consent.ts
canonical_owner: sdk@aether
estimated_read_minutes: 10
toc_depth: 3
last_synced_commit: cb00c2e3
---

# Aether iOS SDK v8.12.0 — Integration Guide

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

Eight canonical purposes: `analytics`, `marketing`, `personalization`, `web3`, `agent`, `commerce`,
`credit`, `location`. `credit` and `location` **always require explicit opt-in** — they are never
granted by `grantAll()` and must be presented as separate consent choices in your UI.

```swift
// Grant specific purposes
Aether.shared.grantConsent(categories: ["analytics", "marketing"])

// Grant all non-sensitive purposes (excludes credit and location)
Aether.shared.grantAll()

// Explicitly grant credit after showing separate consent UI
Aether.shared.grantConsent(categories: ["credit"])

// Revoke consent
Aether.shared.revokeConsent(categories: ["marketing"])

// Check current state
let state = Aether.shared.getConsentState() // ["analytics", ...]

// All canonical purposes
let purposes = AetherSDK.canonicalConsentPurposes
// ["analytics", "marketing", "personalization", "web3", "agent", "commerce", "credit", "location"]
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
    var autoResumeJourney: Bool = true           // Call /sdk/identity/resolve on init
    var onJourneyResumed:                        // Fires once when a prior session is matched
        ((_ resolvedAnonymousId: String,
          _ resolvedUserId: String?) -> Void)? = nil
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
- **Event queue** is persisted to `Application Support/aether_queue.json` (file-based, capped at 1000 events; flushed on foreground)
- **Server config** cached in memory (refreshed on each app launch)

## Health Agent

The health agent starts automatically after `initialize()`. It:
- POSTs a signed heartbeat to `/v1/sdk/health` every 60 seconds
- Fetches the remote manifest from `/v1/config` every 5 minutes
- Both are fire-and-forget; gated on analytics consent in GDPR mode

## Granular Agent Lifecycle Emitters

```swift
Aether.shared.agentRegistered(agentId:, properties:)
Aether.shared.agentTaskCreated(taskId:, actorId:, properties:)
Aether.shared.agentTaskCompleted(taskId:, properties:)
Aether.shared.agentTaskFailed(taskId:, reason:, properties:)
Aether.shared.agentEscalatedToHuman(taskId:, reason:, properties:)
Aether.shared.agentOutcomeRecorded(taskId:, outcome:, properties:)
// ... 13 more — see AetherHealthAgent for full list
```

## x402 Lifecycle Emitters

```swift
Aether.shared.x402ResourceRequested(resourceId:, properties:)
Aether.shared.x402PaymentRequired(resourceId:, amount:, currency:, properties:)
Aether.shared.x402PaymentSettled(paymentId:, properties:)
Aether.shared.x402AccessGranted(resourceId:, properties:)
// ... 10 more
```

## Rewards Emitters

```swift
Aether.shared.rewardActionQueued(campaignId:, ruleId:, properties:)
Aether.shared.rewardProofGenerated(campaignId:, proofId:, properties:)
Aether.shared.rewardDelivered(campaignId:, rewardId:, properties:)
Aether.shared.rewardClaimSubmitted(campaignId:, claimId:, properties:)
```

## Ecommerce Additions (8.9.0)

```swift
Aether.shared.trackRemoveFromCart(productId:, quantity:, properties:)
Aether.shared.trackApplyCoupon(couponCode:, properties:)
Aether.shared.trackBeginCheckout(cartValue:, currency:, properties:)
```

## Reward Event Types (A6)

Four reward lifecycle events are supported via `Aether.shared.track()`:

| Event type | When to emit |
|---|---|
| `reward_action_queued` | When a reward action has been queued for the user |
| `reward_proof_generated` | When an on-chain claim proof is ready for wallet submission |
| `reward_delivered` | When the tenant system confirms reward delivery |
| `reward_claim_submitted` | When the user submits a claim (on-chain or off-chain) |

Emit using `Aether.shared.track()` with `campaignId`, `ruleId`, and `rewardIdempotencyKey` in properties. These events flow through `POST /v1/batch` and are processed by the reward eligibility pipeline on the backend. The SDK does not evaluate eligibility — that is handled server-side by the Aether reward policy engine.

## Agentic Observability Event Types

47 new event types support passive observation of external agentic activity. All are registered in the SDK's `eventConsentPurpose` map and flow through `POST /v1/batch` like any other event.

**Consent purpose:** `"agent"` for all agentic observation events; `"commerce"` for x402 protocol observation events.

**Agentic account / MCP / tool (12 types):**

```swift
// Emit via Aether.shared.track("agentic_account_observed", properties: [...])
// agentic_account_observed, agentic_account_connected_observed, agentic_account_disconnected_observed
// agent_budget_observed, agent_budget_changed_observed, agent_permission_observed
// agent_mcp_connection_observed, agent_tool_observed, agent_tool_invocation_observed
// agent_activity_observed, agent_risk_signal_observed, agent_notification_observed
```

**Robinhood-style trading observation (9 types):**

```swift
// agent_strategy_observed, agent_trade_intent_observed, agent_trade_order_observed
// agent_trade_fill_observed, agent_trade_rejection_observed, agent_position_observed
// agent_portfolio_snapshot_observed, agent_performance_snapshot_observed, agent_disconnect_observed
```

**AgentMail-style communication observation (15 types):**

```swift
// agent_inbox_observed, agent_email_address_observed, agent_thread_observed
// agent_message_received_observed, agent_message_sent_observed, agent_reply_observed
// agent_attachment_observed, agent_attachment_parsed_observed
// agent_otp_detected_observed, agent_invoice_detected_observed, agent_receipt_detected_observed
// agent_calendar_intent_observed, agent_support_route_observed
// agent_semantic_search_observed, agent_data_extraction_observed
```

**x402 protocol observation (11 types, consent purpose: `"commerce"`):**

```swift
// x402_resource_request_observed, x402_challenge_observed, x402_payment_requirement_observed
// x402_signature_observed, x402_verification_observed, x402_settlement_observed
// x402_resource_access_observed, x402_resource_access_denied_observed
// x402_failure_observed, x402_replay_risk_observed, x402_provider_observed
```

> **INVARIANT:** All observation payloads must include `execution_by_aether: false`. AETHER observes external agentic activity — it never originates, signs, executes, or settles on behalf of the caller.
