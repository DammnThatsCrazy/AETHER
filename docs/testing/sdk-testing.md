---
title: SDK Testing — Functionality Proof Spine
slug: testing/sdk-testing
section: concepts
visibility: I
audience: [dev-junior, dev-senior]
status: experimental
since_version: 0.1.0
---

# SDK Testing — Functionality Proof Spine

## Scope

This doc covers how the Functionality Proof Spine validates the Aether SDKs. SDK testing in the FPS combines four layers: proof apps, contract tests, parity tests, and smoke tests. Each layer answers a different question, and together they cover the path from "the SDK initializes" to "events land in the graph and appear in a 360."

Tickets referenced: FPS-011 (web SDK smoke), FPS-012 (iOS SDK smoke), FPS-013 (Android SDK smoke), FPS-016 (SDK contract tests), FPS-017 (SDK parity tests).

## The four layers

### 1. Proof apps

Proof apps are minimal consumer apps that exercise an SDK through a real UI. They exist so a human or automated step can observe SDK behavior in a runtime that matches a real integration, not just through unit-test mocks.

- `apps/proof-web` — Web SDK proof app.
- `apps/proof-react` — React SDK proof app.
- `apps/proof-ios` — iOS SDK proof app.
- `apps/proof-android` — Android SDK proof app.

Each proof app is described in detail in [Proof Apps](../proof/proof-apps.md). The short version: every proof app must expose the controls needed to initialize the SDK, emit a heartbeat, track an event, identify a user, and surface the visible state a tester can verify.

### 2. Contract tests

Contract tests verify that an SDK obeys the ingestion contract documented in `docs/sdks/ingestion-contract.md` and the event contracts in `packages/shared/contracts/`. They run as part of the package's own test suite and are not staging-dependent.

Contract tests cover:

- Batch shape: the SDK emits a batch that matches the `POST /v1/batch` contract.
- Event type registry: the SDK only emits canonical event types from `packages/shared/events.ts`.
- Consent gating: events are dropped or emitted according to the declared consent state.
- Envelope context: the SDK stamps the canonical envelope context fields it genuinely has a source for.
- Batch health surface: the SDK surfaces `accepted`, `duplicate`, `rejected`, `dropped_by_consent`, and `queue_depth` through the expected surface for its platform.
- Offline spool and retry: queued events survive process restart and are flushed when connectivity returns.

Contract tests should pass in local development and in CI. They are the first line of defense before a proof app is even pointed at staging.

### 3. Parity tests

Parity tests verify that all SDKs expose the same canonical runtime surface, as defined in `docs/source-of-truth/SDK_RUNTIME_PARITY.md` and enforced by `scripts/validate_sdk_parity.py`.

Parity is not about identical implementation. It is about identical *observable surface*:

- The same entry point for observation (`observe(type, properties)` on web, iOS, Android, React Native).
- The same batch health counters surfaced to the caller.
- The same privacy behavior (recursive scrubbing, gated fingerprinting, App Store privacy manifest on iOS).
- The same durable queue contract on native platforms (bounded envelopes, atomic flush, transient retry including `408` and `425`, quarantine of corrupt state).

When an SDK legitimately lacks a capability, the parity validator is updated in the same change. Parity tests fail closed: a claimed capability whose evidence is absent fails the gate.

See `docs/sdks/parity-matrix.md` for the current capability matrix.

### 4. Smoke tests

Smoke tests exercise an SDK against staging through `pnpm smoke:<platform>`. They are the bridge between "the contract tests pass on my machine" and "the proof tenant receives the expected data."

Smoke tests cover:

- Initialization with staging credentials.
- A canonical event sequence through the SDK.
- Basic lifecycle: init, track, flush, reset.
- Verification that the events arrived in the proof tenant.

The staging smoke command is described in [Staging Smoke Testing](./staging-smoke-testing.md). SDK smoke tests are owned by the platform team and currently exist as stubs pending real staging access, per FPS-011, FPS-012, FPS-013.

## Required SDK behaviors

For the FPS to pass, every SDK must demonstrably do the following in the proof tenant:

1. **Initialize** with a valid tenant ID and API key and emit a first heartbeat.
2. **Emit heartbeat events** at the configured interval and include session state, SDK version, and contract version.
3. **Track canonical events** through `observe(type, properties)` (or the platform equivalent) and have them appear in the ingestion pipeline.
4. **Support identity hints** so the graph can associate events with a known user.
5. **Surface batch health** through the platform-appropriate API or callback, including `dropped_by_consent` and `queue_depth`.
6. **Respect consent gating** by dropping events that do not have the required consent purpose.
7. **Recurse into nested structures** when scrubbing sensitive fields, not just top-level keys.
8. **Persist queued events** across process restart on native platforms and flush them when connectivity returns.
9. **Retry transient failures correctly**, including `408 Request Timeout` and `425 Too Early`, without silent data loss.
10. **Stamp sequence counters** so the backend can detect gaps and reorder events.

## How the layers relate

```
contract tests (local, package-level)
    → parity tests (local + CI, cross-SDK surface)
        → proof apps (runtime behavior with real UI)
            → smoke tests (staging integration)
                → E2E flows (full tenant proof)
```

A change to an SDK should move the lowest applicable layer first. A new event type, for example, should add contract tests and update the parity surface before it is exercised in a proof app. A fix to consent gating should add a contract test that fails before the fix and passes after, and then be confirmed in the proof app's visible state.

## Pass condition

SDK testing passes when:

- All contract tests in the affected SDK package pass.
- The parity validator reports no missing required capabilities for the SDK.
- The proof app for that SDK exposes the required controls and shows the required visible state.
- The staging smoke test for that SDK emits the expected 24-line PASS output (or the current approved smoke output) with no FAIL lines for that platform.

If any layer fails, the failure is typed with a reason and a likely owning subsystem, per the report format in [Proof Report Format](../proof/proof-report-format.md).
