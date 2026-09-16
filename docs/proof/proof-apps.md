---
title: Proof Apps
slug: proof/proof-apps
section: testing
visibility: I
audience: [dev-junior, dev-senior, qa, mobile]
status: experimental
since_version: 0.1.0
---

# Proof Apps

## Purpose

Proof apps are minimal consumer apps that exercise an SDK through a real UI. They exist so a human or automated step can observe SDK behavior in a runtime that matches a real integration. A proof app is not a demo app and not a sandbox. It is the smallest app that proves the SDK's required behaviors for a proof run.

Each proof app targets one SDK platform. The proof apps are:

- `apps/proof-web` — Web SDK proof app.
- `apps/proof-react` — React SDK proof app.
- `apps/proof-ios` — iOS SDK proof app.
- `apps/proof-android` — Android SDK proof app.
- `apps/proof-connectors` — Connector proof app (where a connector needs a UI to exercise its flow).

The SDK proof apps are described here. The connector proof app is described in [Connector Testing](./testing/connector-testing.md) where relevant.

## Purpose of each app

### Proof web app

The proof web app proves that the Web SDK can be initialized, can emit a heartbeat, can track a canonical event, and can attach an identity hint, all through a browser UI. It is the fastest path to verifying the Web SDK in a real browser runtime.

### Proof React app

The proof React app proves that the React SDK can be initialized through the provider, can use the hooks to track and identify, and can emit a heartbeat, all through a React UI. It is the fastest path to verifying the React SDK in a real React runtime.

### Proof iOS app

The proof iOS app proves that the iOS SDK can be initialized, can emit a heartbeat, can track a screen view or event, and can identify a user, all through a real iOS UI. It is the fastest path to verifying the iOS SDK on a simulator or physical device.

### Proof Android app

The proof Android app proves that the Android SDK can be initialized, can emit a heartbeat, can track an activity or event, and can identify a user, all through a real Android UI. It is the fastest path to verifying the Android SDK on an emulator or physical device.

## Required UI controls per app

Every SDK proof app must expose the same set of controls, so a tester or the proof runner can exercise the same behaviors on every platform.

| Control | Purpose |
|---|---|
| Initialize / config display | Show the tenant ID and API key status, or an error if initialization failed. |
| Emit heartbeat | Trigger a heartbeat event and show that it was sent. |
| Track event | Trigger a canonical event and show that it was sent. |
| Identify user | Attach an identity hint and show that it was attached. |
| Event log / visible state | Show the events that were sent, or the visible state the tester can verify. |
| Reset / clear | Clear the local state so the app can be re-run from a clean baseline. |

The controls must be usable by a human operator and, where applicable, by the proof runner. A control that exists but does nothing is not a control. A control that crashes the app is worse than no control.

## Required visible state per app

Every SDK proof app must show the visible state a tester can verify. The visible state is what proves the SDK behaved correctly, not just that the app did not crash.

| Visible state | What it proves |
|---|---|
| Initialized | The SDK initialized with the proof tenant credentials. |
| Heartbeat sent | The SDK emitted a heartbeat. |
| Event tracked | The SDK tracked a canonical event. |
| Identity attached | The SDK attached an identity hint. |
| Error (if any) | The SDK surfaced a clear error when initialization or emission failed. |

The visible state must be observable in the app's UI. A state that is only logged to the console is not a visible state for a human tester. A state that is only available through a debugger is not a visible state for a proof run.

## Pass conditions per app

Each proof app passes when:

- The app launches without crashing.
- The SDK initializes with the proof tenant credentials and shows the initialized state.
- The heartbeat control emits a heartbeat and shows the heartbeat sent state.
- The track control emits a canonical event and shows the event tracked state.
- The identify control attaches an identity hint and shows the identity attached state.
- The event log or visible state is accurate and complete for the actions taken.
- The app's visible state matches what the proof tenant received, where verification is applicable.

If any of these does not hold, the proof app fails for that platform, and the failure is reported with a typed reason and likely owning subsystem. Common failure reasons include:

- **Initialization failed** — likely owning subsystem: SDK initialization path on the platform.
- **Heartbeat not sent** — likely owning subsystem: SDK heartbeat emission.
- **Event not tracked** — likely owning subsystem: SDK event emission or ingestion contract.
- **Identity not attached** — likely owning subsystem: SDK identity attachment or graph identity resolution.
- **Visible state wrong** — likely owning subsystem: proof app UI or SDK state surface.

## How proof apps relate to the rest of the proof spine

Proof apps are the runtime confirmation that the SDK's contract tests and parity tests hold up in a real runtime with a real UI. A change to an SDK should pass the contract tests and parity validator locally, then be confirmed in the proof app before it is pointed at staging. The proof app is also the app that the staging smoke test and the mobile device checklist exercise, so it is the bridge between local verification and staging verification.

A proof app that does not expose the required controls or show the required visible state cannot be used in a proof run, because there is nothing to verify. A proof app that crashes on the required actions cannot be used in a proof run, because the behaviors cannot be proven.
