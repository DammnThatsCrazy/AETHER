---
title: Verify iOS SDK Installation — Aether
slug: developers/sdk/ios/verify-installation
section: developer
visibility: P
audience: [dev-junior, dev-senior]
status: experimental
since_version: 0.1.0
---

# Verify iOS SDK Installation

This guide walks through installing the Aether iOS SDK, adding your key, initializing, emitting a heartbeat, tracking a screen view, identifying a user, and verifying the result in the Aether UI. It is the practical companion to the [iOS SDK reference](/docs/sdks/ios.md) and the [Mobile Device Testing](/docs/testing/dev-senior-device-testing.md) checklist.

Related tickets: FPS-012 (iOS SDK smoke), FPS-022 (dev-senior device checklist), FPS-028 (connector activation E2E where iOS is in scope).

## Install the SDK

### Swift Package Manager

Add the Aether iOS SDK to your `Package.swift` dependencies:

```swift
dependencies: [
    .package(url: "https://github.com/aether/ios-sdk", from: "0.1.0-alpha.0")
]
```

Then add the product to your target:

```swift
targets: [
    .target(
        name: "MyApp",
        dependencies: [
            .product(name: "Aether", package: "aether-ios-sdk")
        ]
    )
]
```

### CocoaPods

If your project uses CocoaPods, add the pod to your `Podfile`:

```ruby
pod 'Aether', '~> 0.1.0-alpha.0'
```

Then run `pod install`.

The exact source URL and version are determined by the release artifact. For a proof run, use the version that matches the release candidate you are verifying.

## Add your key

You need a tenant ID and an API key for the environment you are targeting. For a proof run, use the proof tenant credentials from the staging environment. For local development, use your local tenant credentials. API keys are provisioned per tenant. See [Tenant Setup](/docs/developer/tenant-setup.md).

Do not commit API keys to the repository. Read them from the environment, your app's secret store, or the build configuration that supplies secrets at build time.

## Initialize

Initialize the SDK early in your app's lifecycle, typically in `application(_:didFinishLaunchingWithOptions:)` or your app's entry point.

```swift
import Aether

Aether.initialize(
    tenantId: "aether-proof-tenant",
    apiKey: Secrets.aetherApiKey,
    appId: "my-ios-app"
)
```

Initialization configures the SDK with your tenant, app, and site metadata. The SDK does not start emitting until you call the tracking methods, but it does validate the configuration and prepare the batch queue.

If initialization fails, the SDK surfaces a clear error. A failure to initialize is a reportable failure in the proof spine, with reason `INITIALIZATION_FAILED` and likely owning subsystem iOS SDK.

## Emit a heartbeat

Every Aether SDK emits periodic heartbeat events to confirm liveness and session continuity. The iOS SDK emits the first heartbeat on initialization and subsequent heartbeats at the configured interval.

The heartbeat includes session state, SDK version, and contract version. See [SDK Heartbeat](/docs/sdks/heartbeat.md) for the full heartbeat contract.

In a proof run, the heartbeat is verified by the proof iOS app's heartbeat control, by the SDK's health surface where applicable, and by confirmation in the proof tenant's ingestion surface. A missing heartbeat is a reportable failure with reason `HEARTBEAT_NOT_SENT` and likely owning subsystem iOS SDK.

## Track a screen view

The canonical screen view entry point is `observe(type, properties)` with a canonical screen view type.

```swift
Aether.observe("screen_view", [
    "screen_name": "Home",
    "screen_class": "HomeViewController"
])
```

The event type must be a canonical type from the event registry. Non-canonical types are ignored at ingestion. See [SDK Ingestion Contract](/docs/sdks/ingestion-contract.md) and [Event Contracts](/docs/sdks/event-contracts.md).

In a proof run, the tracked screen view is verified by the proof iOS app's track control and by confirmation in the proof tenant's ingestion surface. A screen view that is not tracked is a reportable failure with reason `EVENT_NOT_TRACKED` and likely owning subsystem iOS SDK.

## Identify a user

Attach an identity hint so the graph can associate events with a known user.

```swift
Aether.identify("user_123", [
    "email": "user@example.com",
    "name": "Example User"
])
```

Identity hints are not identity resolution. They are hints the SDK sends so the backend can associate events. See [Tenant Setup](/docs/developer/tenant-setup.md) for identity merge rules.

In a proof run, the identity hint is verified by the proof iOS app's identify control and by confirmation that the identity appears in the Profile 360 or the graph. An identity that is not attached is a reportable failure with reason `IDENTITY_NOT_ATTACHED` and likely owning subsystem iOS SDK.

## Verify in the Aether UI

After emitting a heartbeat and tracking a screen view, verify that the proof tenant received them.

1. Open the Aether Console or Kyber Operator Console on staging.
2. Navigate to the proof tenant's ingestion or SDK health surface.
3. Confirm the heartbeat is present with the expected session state and SDK version.
4. Confirm the tracked screen view is present with the expected type and properties.
5. If you identified a user, confirm the identity hint is associated with the events.

The verification path for a proof run is described in [Mobile Device Testing](/docs/testing/dev-senior-device-testing.md) and the E2E flows where iOS is in scope. A heartbeat or event that is not visible in the Aether UI is a reportable failure with the appropriate reason code and likely owning subsystem.

## App Store privacy and ATT

The iOS SDK ships a privacy manifest (`PrivacyInfo.xcprivacy`) that describes the tracking and data collection behavior. The manifest is bundled via `Package.swift` resources. Its presence is validated by the SDK parity gate.

If your app uses App Tracking Transparency, the iOS SDK gates device fingerprinting on analytics consent and, when `respectATT` is enabled, on an `.authorized` ATT status. This is part of the privacy parity contract described in [SDK Runtime Parity](/docs/source-of-truth/SDK_RUNTIME_PARITY.md).

In a proof run, ATT gating is verified on a physical device where ATT is enabled. A fingerprinting behavior that does not match the documented gating is a reportable failure with reason `ATT_GATING_WRONG` and likely owning subsystem iOS SDK.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| SDK does not initialize | Missing or invalid tenant ID or API key | Check the API key and tenant ID. Confirm the SDK is initialized early in the app lifecycle. |
| No heartbeat in the Aether UI | SDK did not emit a heartbeat, or the event did not reach ingestion | Check the SDK's health surface where applicable. Confirm the SDK is initialized. |
| Screen view not in the Aether UI | Event type is non-canonical, or the event did not reach ingestion | Confirm the event type is canonical. Check the ingestion surface. |
| Identity not associated | Identity hint not sent, or identity resolution not configured | Confirm the identify call fired. Check the tenant's identity merge rules. |
| Fingerprinting gated incorrectly | ATT status or consent state not as documented | Check the ATT status and the analytics consent state. Review the privacy parity contract. |
| Build fails with privacy manifest error | Privacy manifest missing or malformed | Confirm the privacy manifest is bundled via `Package.swift` resources. |
| `queue_depth` growing | Network issue or endpoint down | Check the API key and endpoint URL. Check the SDK's offline spool. |
| `ingestion_success_rate` below 1.0 | Schema validation failures | Check the event types and properties against the event registry. |

For the full heartbeat troubleshooting table, see [Verify Heartbeat](/docs/developer/verify-heartbeat.md).

## Next steps

- [Install the SDK](/docs/developer/install-the-sdk.md)
- [Send Your First Event](/docs/developer/send-first-event.md)
- [Verify Heartbeat](/docs/developer/verify-heartbeat.md)
- [Mobile Device Testing](/docs/testing/dev-senior-device-testing.md)
- [SDK Testing](/docs/testing/sdk-testing.md)
- [iOS SDK Smoke](/docs/testing/staging-smoke-testing.md)
