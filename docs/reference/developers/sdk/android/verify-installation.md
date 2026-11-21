---
title: Verify Android SDK Installation — Aether
slug: developers/sdk/android/verify-installation
section: developer
visibility: P
audience: [dev-junior, dev-senior]
status: experimental
since_version: 0.1.0
---

# Verify Android SDK Installation

This guide walks through installing the Aether Android SDK, adding your key, initializing, emitting a heartbeat, tracking an activity, identifying a user, and verifying the result in the Aether UI. It is the practical companion to the [Android SDK reference](/docs/sdks/android.md) and the [Mobile Device Testing](/docs/testing/dev-senior-device-testing.md) checklist.

Related tickets: FPS-013 (Android SDK smoke), FPS-022 (dev-senior device checklist), FPS-028 (connector activation E2E where Android is in scope).

## Install the SDK

### Gradle dependency

Add the Aether Android SDK to your app module's `build.gradle`:

```gradle
implementation 'com.olympuslabsml:aether-android:0.1.0-alpha.0'
```

The exact version is determined by the release artifact. For a proof run, use the version that matches the release candidate you are verifying.

The SDK is published to Maven Central, which Android projects include by default (`mavenCentral()` in `settings.gradle`). The Kotlin package is `com.aether.sdk`.

## Add your key

You need the SDK key Aether issued for this app or site in the environment you are targeting (onboarding issues one per SDK; browser SDKs get a site-bound publishable `pk_` key). The key identifies the tenant, so there is no separate tenant ID. For a proof run, use the proof tenant credentials from the staging environment. For local development, use your local tenant credentials. API keys are provisioned per tenant. See [Tenant Setup](/docs/developer/tenant-setup.md).

Do not commit API keys to the repository. Read them from the environment, your app's secret store, or the build configuration that supplies secrets at build time.

## Initialize

Initialize the SDK early in your app's lifecycle, typically in `onCreate` of your application class or your first activity.

```kotlin
import com.aether.sdk.Aether
import com.aether.sdk.AetherConfig

class MyApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        Aether.initialize(this, AetherConfig(apiKey = BuildConfig.AETHER_API_KEY))

        // Events are gated by consent. Grant the purposes your consent UI collected.
        Aether.grantConsent(listOf("analytics"))
    }
}
```

`AetherConfig(apiKey = ...)` takes the key Aether issued for this app; the tenant is derived from the key on the server, so there is no tenant ID to pass. The ingestion endpoint defaults to `https://api.olympuslabsml.com` (override with `endpoint = ...`). `initialize` needs the `Application` instance because the SDK observes the process lifecycle. Events are sent once you call the tracking methods below.

If initialization fails, the SDK surfaces a clear error. A failure to initialize is a reportable failure in the proof spine, with reason `INITIALIZATION_FAILED` and likely owning subsystem Android SDK.

## Emit a heartbeat

Every Aether SDK emits periodic heartbeats to confirm liveness. The Android SDK sends the first heartbeat when `initialize` runs and then every 60 seconds. With `privacy.gdprMode` enabled, heartbeats start only once `analytics` consent is granted.

The heartbeat includes session state, SDK version, and contract version. See [SDK Heartbeat](/docs/sdks/heartbeat.md) for the full heartbeat contract.

In a proof run, the heartbeat is verified by the proof Android app's heartbeat control, by the SDK's health surface where applicable, and by confirmation in the proof tenant's ingestion surface. A missing heartbeat is a reportable failure with reason `HEARTBEAT_NOT_SENT` and likely owning subsystem Android SDK.

## Track an activity

Use `screenView(screenName, properties)`. For other canonical event types, use `Aether.observe(type, properties)`.

```kotlin
import com.aether.sdk.Aether

Aether.screenView("Home", mapOf(
    "screen_class" to HomeActivity::class.java.name
))
```

The event type must be a canonical type from the event registry. Non-canonical types are ignored at ingestion. See [SDK Ingestion Contract](/docs/sdks/ingestion-contract.md) and [Event Contracts](/docs/sdks/event-contracts.md).

In a proof run, the tracked activity is verified by the proof Android app's track control and by confirmation in the proof tenant's ingestion surface. An activity that is not tracked is a reportable failure with reason `EVENT_NOT_TRACKED` and likely owning subsystem Android SDK.

## Identify a user

Attach an identity hint so the graph can associate events with a known user.

```kotlin
import com.aether.sdk.Aether
import com.aether.sdk.IdentityData

Aether.hydrateIdentity(IdentityData(
    userId = "user_123",
    email = "user@example.com",
    traits = mapOf("name" to "Example User")
))
```

Identity hints are not identity resolution. They are hints the SDK sends so the backend can associate events. See [Tenant Setup](/docs/developer/tenant-setup.md) for identity merge rules.

In a proof run, the identity hint is verified by the proof Android app's identify control and by confirmation that the identity appears in the Profile 360 or the graph. An identity that is not attached is a reportable failure with reason `IDENTITY_NOT_ATTACHED` and likely owning subsystem Android SDK.

## Verify durable queue behavior

The Android SDK persists a bounded, versioned queue envelope with atomic file replacement. It restores the queue after process restart and quarantines corrupt state instead of crashing or silently accepting it. Flush removes a batch atomically; exhausted `429`, `408`/`425`, and `5xx` deliveries are requeued, while terminal client errors are dropped. The queue remains capped to prevent unbounded device storage.

This behavior is part of the durable native delivery queue contract described in [SDK Runtime Parity](/docs/source-of-truth/SDK_RUNTIME_PARITY.md).

In a proof run, durable queue behavior is verified by:

1. Triggering an event while the device is offline or the app is backgrounded.
2. Killing the app process.
3. Restarting the app.
4. Confirming the queued event is flushed when connectivity returns.

A queued event that is lost on process restart is a reportable failure with reason `QUEUE_LOST_ON_RESTART` and likely owning subsystem Android SDK.

## Verify in the Aether UI

After emitting a heartbeat and tracking an activity, verify that the proof tenant received them.

1. Open the Aether Console or Kyber Operator Console on staging.
2. Navigate to the proof tenant's ingestion or SDK health surface.
3. Confirm the heartbeat is present with the expected session state and SDK version.
4. Confirm the tracked activity is present with the expected type and properties.
5. If you identified a user, confirm the identity hint is associated with the events.

The verification path for a proof run is described in [Mobile Device Testing](/docs/testing/dev-senior-device-testing.md) and the E2E flows where Android is in scope. A heartbeat or event that is not visible in the Aether UI is a reportable failure with the appropriate reason code and likely owning subsystem.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|---|
| SDK does not initialize | Missing or invalid API key | Check the API key issued for this app. Confirm `Aether.initialize` runs in `Application.onCreate`. |
| No heartbeat in the Aether UI | SDK did not emit a heartbeat, or the event did not reach ingestion | Confirm the SDK is initialized. In GDPR mode, confirm `analytics` consent was granted. |
| Activity not in the Aether UI | Consent not granted, or the event did not reach ingestion | Confirm `analytics` consent is granted. Call `Aether.flush()` and check the ingestion surface. |
| Identity not associated | Identity hint not sent, or identity resolution not configured | Confirm the identify call fired. Check the tenant's identity merge rules. |
| Queued events lost after process restart | Durable queue not persisting or restoring correctly | Review the durable queue implementation. Check the queue file and atomic replacement. |
| `queue_depth` growing | Network issue or endpoint down | Check the API key and endpoint URL. Check the SDK's offline spool. |
| `ingestion_success_rate` below 1.0 | Schema validation failures | Check the event types and properties against the event registry. |

For the full heartbeat troubleshooting table, see [Verify Heartbeat](/docs/developer/verify-heartbeat.md).

## Next steps

- [Install the SDK](/docs/developer/install-the-sdk.md)
- [Send Your First Event](/docs/developer/send-first-event.md)
- [Verify Heartbeat](/docs/developer/verify-heartbeat.md)
- [Mobile Device Testing](/docs/testing/dev-senior-device-testing.md)
- [SDK Testing](/docs/testing/sdk-testing.md)
- [Android SDK Smoke](/docs/testing/staging-smoke-testing.md)
