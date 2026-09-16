# Android Kotlin Example

Kotlin wrapper reference for the Aether Android SDK. This directory points to the canonical native SDK usage in `apps/proof-android/`, which is an Expo/React Native app that surfaces the full first-value journey on Android devices.

## What this is

`apps/proof-android/` is the Android proof harness — it uses `@aether/react-native` (the React Native bridge that wraps the native Android SDK) and exercises every signal in the canonical first-value lifecycle: init, heartbeat, consent, event, identify, journey, commerce, flush, reset.

This `examples/android-kotlin/` directory provides a Kotlin-oriented README that explains how the native SDK is used under the hood, so Kotlin/Android developers can see the native SDK surface without needing to dig through the React Native bridge code.

## Native SDK surface (Kotlin)

The native Aether Android SDK exposes the following surface (used by the React Native bridge and available directly to Kotlin/Android apps):

| Capability | Kotlin API | First-value role |
|------------|-----------|------------------|
| Initialize | `Aether.initialize(config: AetherConfig)` | Install → init |
| Heartbeat | `Aether.heartbeat()` | Proves SDK live, backend reachable |
| Track event | `Aether.track(event: AEEvent)` | Behavioral signal |
| Identify | `Aether.identify(userId: String, traits: Map<String, Any>?)` | Identity linkage |
| Consent | `Aether.consent.grant(purposes: List<String>)` / `revoke` | GDPR/consent gate |
| Journey | `Aether.journey.start(name: String, properties: Map<String, Any>?)` + lifecycle methods | Journey lifecycle |
| Commerce | `Aether.commerce.track(event: AECommerceEvent)` | Revenue-bearing event |
| Flush | `Aether.flush()` | Queue drain → backend acceptance |
| Reset | `Aether.reset()` | Fresh session |
| Debug state | `Aether.debugState()` | SDK state snapshot |

## Using the native SDK directly in a Kotlin/Android app

1. Add the Aether Android SDK to your project (via Gradle dependency).
2. Configure `AetherConfig` with your write key and endpoint.
3. Call `Aether.initialize(config:)` at app launch (e.g. in `Application.onCreate()`).
4. Grant consent before sending any events.
5. Use `Aether.track()`, `Aether.identify()`, `Aether.commerce.track()`, `Aether.journey.start()` as needed.
6. Call `Aether.flush()` to drain the queue and confirm backend acceptance.

## First-value journey (native Android path)

| Step | Native call | Proof |
|------|------------|-------|
| Install | SDK linked in Gradle project | Native SDK available on device |
| Init | `Aether.initialize(config:)` | Session + anonymousId minted |
| Heartbeat | `Aether.heartbeat()` | Heartbeat delivered to POST /v1/batch |
| Consent | `Aether.consent.grant([…])` | Consent granted — events will deliver |
| Event | `Aether.track(event:)` | Custom event delivered |
| Identify | `Aether.identify(userId:traits:)` | Identity attached |
| Journey | `Aether.journey.start(name:…)` | Journey lifecycle started |
| Commerce | `Aether.commerce.track(event:)` | Revenue event delivered, Kyber-visible |
| Flush | `Aether.flush()` | Queue flushed — backend acceptance proven |
| Reset | `Aether.reset()` | Session cleared |
| Backend acceptance | POST /v1/batch returns 200 | Events visible in Aether dashboard & Kyber |
| Activation milestone | First valid event accepted → device activated | Check activation status |
| Kyber/Aether visibility | Events appear in economic graph & Aether analytics | Verify in Kyber observability |

## Manual smoke testing on Android

See `docs/examples/README.md` for the manual device smoke test procedure for Android. In short:

1. Build and run `apps/proof-android/` on a physical Android device or emulator.
2. Tap through the first-value journey tabs in the app.
3. Verify each step delivers an event (check the Debug Console).
4. Verify the final flush shows `accepted=N` from the backend.
5. Confirm events appear in the Aether dashboard and Kyber observability.

## Related

- `apps/proof-android/` — the full Expo/React Native proof harness for Android.
- `examples/react-native/` — the shared React Native example.
- `scripts/smoke/android-sdk.ts` — automated smoke tests for the Android SDK.
