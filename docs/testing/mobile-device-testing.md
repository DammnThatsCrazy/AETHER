---
title: Mobile Device Testing — Functionality Proof Spine
slug: testing/mobile-device-testing
section: concepts
visibility: I
audience: [dev-junior, dev-senior]
status: experimental
since_version: 0.1.0
---

# Mobile Device Testing — Functionality Proof Spine

## Scope

This doc is the real-device checklist for the iOS and Android proof apps. It covers simulator and emulator steps, physical device steps, internal distribution paths, and the screenshots and logs required to record pass/fail evidence. Mobile device testing is the point where the SDK contract and parity tests meet a real runtime on a real device, and it is the layer that exposes platform-specific behavior such as App Tracking Transparency on iOS and background lifecycle on Android.

Tickets referenced: FPS-012 (iOS SDK smoke), FPS-013 (Android SDK smoke), FPS-022 (dev-senior device checklist).

## Why dev-senior device testing is separate

The web and React proof apps run in a browser or a desktop runtime that is easy to automate and screenshot. Mobile proof apps run on platforms where the runtime is a phone, the distribution path is slower, and the observable state requires a physical or virtual device screen. Mobile device testing exists so a human can verify the SDK in the environment where it will actually run, including platform behaviors that are hard to simulate on desktop.

## iOS Simulator steps

These steps use the iOS proof app in the simulator. They are the fastest path to verifying the iOS SDK and are appropriate for most development-loop checks.

1. Install the iOS proof app in the simulator. If the app is not already installed, build and run it from Xcode or `xcodebuild` against the proof tenant credentials.
2. Open the proof app. Confirm the app launches without crashing and shows the initialization screen.
3. Verify the SDK key is set. The proof app should display the tenant ID and confirm initialization, or surface a clear error if the key is missing or invalid.
4. Emit a heartbeat. Use the proof app's heartbeat control and confirm the SDK emits a heartbeat event. Verify in the proof app's visible state that the heartbeat was sent.
5. Track an event. Use the proof app's track control to emit a canonical event. Confirm the event appears in the proof app's event log or visible state.
6. Identify a user. Use the proof app's identify control to attach an identity hint. Confirm the identity is reflected in the visible state.
7. Verify in the Aether UI. On staging, confirm the proof tenant received the heartbeat and the tracked event. The verification path is described in the SDK verification guides.
8. Take screenshots. Capture the simulator screen at initialization, after heartbeat, after track, and after identify. Save the screenshots with the run metadata.

iOS Simulator steps are repeatable and do not require a physical device. They are sufficient for verifying the SDK surface, but they do not cover ATT prompts, background/foreground lifecycle, or device-level network conditions.

## Physical iPhone steps

These steps use a physical iPhone with the iOS proof app installed. They are required for verifying platform-specific behavior that the simulator does not fully replicate.

1. Distribute the iOS proof app to the physical iPhone. Use TestFlight for external-like distribution or an internal build for faster iteration. The distribution path is described below.
2. Install the app and open it. Confirm it launches on the device and shows the initialization screen.
3. Complete the same verification sequence as the simulator: initialize, emit heartbeat, track an event, identify a user, verify in the Aether UI.
4. If the SDK uses App Tracking Transparency, verify the ATT prompt behavior. On a device with ATT enabled, confirm the prompt appears when expected and that fingerprinting is gated on the user's choice, per the privacy parity requirements in `docs/source-of-truth/SDK_RUNTIME_PARITY.md`.
5. Exercise app lifecycle. Send the app to the background, wait for the configured interval, and bring it back to the foreground. Confirm the SDK handles the lifecycle transition and continues to emit heartbeats or queue events as expected.
6. Exercise network conditions if relevant. Toggle airplane mode or switch between Wi-Fi and cellular, trigger an event, and confirm the SDK queues the event and flushes when connectivity returns.
7. Take screenshots and logs. Capture the device screen at each step. Collect device logs (e.g., `log collect` or Xcode console) for the run and save them with the run metadata.

Physical iPhone steps are mandatory before a release that includes iOS SDK changes. They are also mandatory when the SDK's platform-specific behavior changes, such as ATT gating, fingerprint stamping, or background queue persistence.

## Android Emulator steps

These steps use the Android proof app in an emulator. They are the fastest path to verifying the Android SDK and are appropriate for most development-loop checks.

1. Install the Android proof app in the emulator. If the app is not already installed, build and run it from Android Studio or Gradle against the proof tenant credentials.
2. Open the proof app. Confirm the app launches without crashing and shows the initialization screen.
3. Verify the SDK key is set. The proof app should display the tenant ID and confirm initialization, or surface a clear error if the key is missing or invalid.
4. Emit a heartbeat. Use the proof app's heartbeat control and confirm the SDK emits a heartbeat event. Verify in the proof app's visible state that the heartbeat was sent.
5. Track an event. Use the proof app's track control to emit a canonical event. Confirm the event appears in the proof app's event log or visible state.
6. Identify a user. Use the proof app's identify control to attach an identity hint. Confirm the identity is reflected in the visible state.
7. Verify in the Aether UI. On staging, confirm the proof tenant received the heartbeat and the tracked event.
8. Take screenshots. Capture the emulator screen at initialization, after heartbeat, after track, and after identify. Save the screenshots with the run metadata.

Android Emulator steps are repeatable and do not require a physical device. They are sufficient for verifying the SDK surface, but they do not cover device-level background lifecycle, battery optimization behavior, or network transitions that differ on physical hardware.

## Physical Android steps

These steps use a physical Android device with the Android proof app installed. They are required for verifying platform-specific behavior that the emulator does not fully replicate.

1. Distribute the Android proof app to the physical device. Use the internal distribution path described below for faster iteration.
2. Install the app and open it. Confirm it launches on the device and shows the initialization screen.
3. Complete the same verification sequence as the emulator: initialize, emit heartbeat, track an event, identify a user, verify in the Aether UI.
4. Exercise app lifecycle. Send the app to the background, wait for the configured interval, and bring it back to the foreground. Confirm the SDK handles the lifecycle transition and persists queued events across the background period.
5. Exercise network conditions if relevant. Toggle airplane mode or switch between Wi-Fi and dev-senior data, trigger an event, and confirm the SDK queues the event and flushes when connectivity returns.
6. Verify durable queue behavior. If the SDK persists a queue across process restart, kill the app process, restart it, and confirm the queued events are flushed. This verifies the durable native delivery queue contract described in `docs/source-of-truth/SDK_RUNTIME_PARITY.md`.
7. Take screenshots and logs. Capture the device screen at each step. Collect device logs (e.g., `adb logcat`) for the run and save them with the run metadata.

Physical Android steps are mandatory before a release that includes Android SDK changes. They are also mandatory when the SDK's platform-specific behavior changes, such as background queue persistence, fingerprinting gating, or lifecycle handling.

## TestFlight and internal iOS distribution path

For iOS, the proof app is distributed through one of two paths:

- **Internal build (fast iteration).** Build the proof app from source and install it on a physical device via Xcode or `ideviceinstaller`-style tooling. This path is for development-loop checks and does not require App Store review. It is appropriate for simulator-verified changes that need a physical-device confirmation.
- **TestFlight (pre-release).** Archive the proof app, upload it to App Store Connect, and distribute it through TestFlight. This path exercises the release artifact and is mandatory before a release that includes iOS SDK changes. It is also the path that surfaces packaging, privacy manifest, and App Store-related issues that an internal build may not expose.

When documenting a run, record which distribution path was used. A TestFlight run is stronger evidence than an internal build run because it validates the distributed artifact.

## Android internal distribution path

For Android, the proof app is distributed through one of two paths:

- **Internal build (fast iteration).** Build the proof app from source and install it on a physical device or emulator via `adb install` or Android Studio. This path is for development-loop checks.
- **Internal track (pre-release).** Build the release artifact and distribute it through an internal track or artifact share. This path exercises the release artifact and is mandatory before a release that includes Android SDK changes. It surfaces packaging and release-artifact issues that a debug build may not expose.

When documenting a run, record which distribution path was used. An internal track run is stronger evidence than a debug build run.

## Required screenshots and logs

Every dev-senior device run must capture enough evidence to reproduce the pass/fail decision. At minimum, record:

- **Screenshots** of the proof app at initialization, after heartbeat, after track, after identify, and after any platform-specific step (e.g., ATT prompt, background/foreground transition).
- **Device logs** for the run: Xcode console or `log collect` on iOS, `adb logcat` on Android. Capture enough log to show SDK initialization, event emission, and any errors.
- **Run metadata**: device model, OS version, app version/build, distribution path, proof tenant ID, and the time window of the run.
- **Verification evidence**: confirmation in the Aether UI that the proof tenant received the heartbeat and tracked events, including timestamps that match the device run.

Screenshots and logs are not optional. A dev-senior device run without them is not evidence; it is an anecdote.

## Pass/fail evidence

A dev-senior device run passes when:

- The proof app launches on the target device without crashing.
- The SDK initializes with the proof tenant credentials and emits a heartbeat.
- A canonical event is tracked and appears in the proof tenant.
- An identity hint is attached and reflected in the visible state or the graph.
- Any platform-specific behavior under test (ATT gating, background queue persistence, durable queue across restart, network transition flush) behaves as documented.
- The required screenshots and logs are captured and saved with the run metadata.

A dev-senior device run fails when any of the above does not hold, and the failure is recorded with a typed reason and a likely owning subsystem. Common dev-senior failure reasons include:

- **SDK initialization crash** — likely owning subsystem: SDK initialization path on the platform.
- **Missing heartbeat in the proof tenant** — likely owning subsystem: SDK batch emission or staging ingestion.
- **Event not appearing in the proof tenant** — likely owning subsystem: SDK event emission, ingestion contract, or graph projection.
- **Identity hint not reflected** — likely owning subsystem: SDK identity attachment or graph identity resolution.
- **ATT gating not behaving as documented** — likely owning subsystem: iOS SDK privacy/fingerprinting path.
- **Queued events lost after process restart** — likely owning subsystem: Android SDK durable queue path.

## How dev-senior device testing relates to the other layers

Mobile device testing is the runtime confirmation that sits above contract tests, parity tests, and smoke tests. A change to the iOS or Android SDK should pass the contract tests and parity validator locally, then be confirmed on a simulator or emulator, then on a physical device before release. The dev-senior device checklist is the human-in-the-loop layer that verifies the SDK in the environment where platform-specific behavior matters.
