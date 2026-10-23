---
title: SDK Intake Productization
slug: sdk-parity-productization
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: "0.1.0"
---

# SDK Intake Productization

## Architecture boundary

Web, Server, React Native, iOS, and Android SDKs are observation clients. They
send observations through the canonical `POST /v1/batch` contract. The backend
resolves the authenticated tenant and site scope, validates consent and event
contracts, scrubs sensitive fields, applies temporal and sequencing controls,
and persists accepted evidence before downstream publication. Clients may send
identity hints; they do not decide canonical identity, rights, or graph state.

Imports, providers, MCP observation, and CLI ingestion are other adapters to the
same source/intake and evidence authorities. They are not SDK variants and must
not gain independent graph or identity write paths. MCP/CLI query and action
calls belong to the Access Kit work orders, not this SDK target.

## Current code state

### Server intake

`services/api/ingestion/ingestion/batch.py` is the canonical SDK batch route and
returns per-event `accepted`, `duplicate`, or `rejected` outcomes. Validation
rejections carry reason codes. The route enforces write permission, shares
validation and consent logic across its V1 and V2 branches, and stamps identity
scope from the authenticated site binding or tenant; caller-supplied identity
scope is discarded.

The default V1 branch writes accepted events to Bronze before publishing the
validated event. The flag/canary V2 branch writes typed Bronze and the
transactional outbox in one `ingest_many` operation, using database uniqueness
for deduplication. Both return the same batch response shape. The deprecated
`/v1/ingest/events` aliases route through the V1 `ingest_events` spine while
they remain enabled.

Envelope-B creation and gateway validation remain independently feature-gated
and additive. A verified gap was that V2 accepted SDK events without the
optional `observation_envelope` even when V1 emitted it. Both branches now call
the same helper: when `AETHER_OBSERVATION_ENVELOPE_ENABLED` is off, payloads keep
their prior shape; when on, the SDK adapter adds Envelope-B; when
`AETHER_UNIVERSAL_INGRESS_GATEWAY_ENABLED` is also on, the gateway validates and
stamps it. A rejected envelope records degradation; an envelope that cannot be
built increments the skipped counter. In either case, the already accepted flat
event remains available, preserving the existing fail-open adoption contract.
The flat event remains the consumer compatibility surface.

Relevant implementation: `services/api/ingestion/ingestion/batch.py`,
`observation_envelope.py`, `adapters/sdk.py`, `gateway.py`, and
`bronze_bulk.py`.

### SDK surface inventory

| Capability | Web | Server | React Native | iOS | Android |
|---|---|---|---|---|---|
| Observation and batch delivery | Public `track` and canonical-type `observe`; batches to `/v1/batch` | Typed `track`/observation helpers; batches to `/v1/batch` | JS bridge delegates to native observation and batching | Native `track` and canonical-type `observe` | Native `track` and canonical-type `observe` |
| Consent and bounded queue | Consent-gated event queue; in-memory queue with delivery retry | Consent-gated queue; memory by default, optional disk-backed JSONL spool | Native consent and event queue are surfaced through the bridge | Native consent and persisted event queue | Native consent and persisted event queue; AES-GCM durable ack mode is opt-in |
| Fleet heartbeat | Health agent sends heartbeat and reports delivery diagnostics | Local flush counters exist; no equivalent remote fleet heartbeat is established by the SDK implementation | RN health agent sends heartbeat | Native health agent sends heartbeat | Native health agent sends heartbeat |
| Remote SDK manifest | Fetches, verifies, and applies manifest configuration | No manifest client established | Fetches and applies manifest values to JS feature flags, sampling, and endpoint overrides; signature verification is not available (the bridge reports `manifestSignatureVerification: false`) | Fetches and applies manifest; signature verification is supported when configured | Fetches and applies manifest; signature verification is supported when configured |

The code supports useful features on every client family. A versioned minimum
wire vector now pins the stable observation fields and `/v1/batch` envelope in
`packages/shared/contracts/sdk-batch-wire-v1.json`. Focused tests consume that
same file in Web, Server, React Native, iOS, and Android. Web and Server tests
exercise their HTTP senders; iOS and Android tests exercise the shared envelope
builders used by their production send modes; the React Native test verifies
that the canonical observation is delegated unchanged to native, where the
platform sender owns serialization.

This is deliberately a narrow wire conformance check. The vector permits the
existing optional outer `context` and `consents` fields. It does not standardize
consent decisions, client identity behavior, tenant/site scope, retry outcomes,
or graph results. Package presence and local conformance checks do not establish
publish readiness, device lifecycle behavior, or customer graph hydration.

Primary inspection points include `packages/sdk/web/src/index.ts`,
`packages/sdk/server/src/index.ts` and `durable-queue.ts`,
`packages/sdk/react-native/src/bridge.ts` and `modules/RemoteManifest.ts`,
`packages/sdk/ios/Sources/AetherSDK/Aether.swift` and `AetherHealthAgent.swift`,
and `packages/sdk/android/src/main/java/com/aether/sdk/Aether.kt` and
`AetherHealthAgent.kt`.

### Shared conformance vector coverage

`packages/shared/contracts/sdk-batch-wire-v1.json` pins one minimum observation
with its stable event fields, the `/v1/batch` path, and the required batch
fields. The consumers intentionally check the seam each package owns:

| SDK | Fixture-backed check | What it establishes |
|---|---|---|
| Web | `packages/sdk/web/test/sdk-batch-wire-contract.test.ts` | The `EventQueue` sends the vector unchanged in `batch` to `/v1/batch` and emits ISO-8601 `sentAt`. |
| Server | `packages/sdk/server/src/transport.test.ts` | `sendBatch` sends the vector in the canonical envelope; its optional `consents` hint remains an SDK input. |
| React Native | `packages/sdk/react-native/src/__tests__/Observe.test.ts` | `observe(type, properties)` forwards the canonical event and properties to native unchanged; native owns the wire sender. |
| iOS | `packages/sdk/ios/Tests/AetherSDKTests/AetherSDKTests.swift` | `AetherEvent` decodes/encodes the fixture through the same batch-envelope helper used by legacy and durable-ack senders. |
| Android | `packages/sdk/android/src/test/java/com/aether/sdk/AetherTest.kt` | The shared batch-envelope helper used by legacy and durable-ack senders preserves the event vector and required envelope fields. |

The vector is not a complete schema conformance suite: the iOS/Android checks
exercise serialization/envelope helpers, and the React Native check covers its
bridge handoff. None boots an installed mobile app or exercises a device queue.
Consent filtering, identity/retry policy, resolved tenant/site scope,
observation admission, and graph projection remain separate proof obligations.

## Remaining work and proof gates

1. **Shared wire conformance.** The v1 vector now covers the stable required
   event fields, canonical `/v1/batch` path, `batch`, and ISO-8601 `sentAt`;
   focused platform tests verify those values through each SDK's current
   transport or native handoff seam. The Server SDK may add its optional
   `consents` hint, Web may add batch context, and native platforms may attach
   platform-specific event context. Remaining proof: execute the iOS test with
   an XCTest-capable Xcode toolchain, execute the Android test with Gradle, and
   retain runtime/device evidence for installed clients. On the source-intake
   branch, focused Web, Server, and React Native Vitest files passed and
   `swift build --package-path packages/sdk/ios` passed. The focused `swift test`
   could not resolve `XCTest` under the active Command Line Tools selection, and
   Android execution was unavailable because neither `gradle` nor a wrapper is
   present. No identity or consent semantics are introduced by this fixture.
2. **V1/V2 intake proof.** Focused local route coverage now sends the same SDK
   event through V1 and V2 with Envelope-B and gateway flags on, then compares
   stable envelope fields in the V1 published payload and V2 Bronze/outbox
   payload. A separate local check proves the default-off helper leaves the
   legacy payload unchanged. Still retain route-level evidence for gateway
   rejection degradation, transactional Bronze/outbox retry after publish or
   relay failure, and provider-backed durable replay; these local in-memory
   checks do not prove those cases.
3. **Tenant graph hydration.** For each SDK family, use a real customer-style
   credential and tenant to send a consented source event, follow it through
   durable evidence, normalization and identity authority, then prove it is
   queryable in the governed tenant graph. Separately cover denied consent,
   cross-tenant isolation, duplicate replay, and a rejected event. A successful
   batch response proves intake acceptance only.
4. **Device lifecycle and privacy evidence.** Run iOS and Android integration
   on devices or simulators, and React Native in representative host apps.
   Cover install, foreground/background, process restart, offline recovery,
   queue bounds, opt-in encrypted persistence, manifest verification and
   failure behavior, kill switches, and consent revocation. Review platform
   privacy manifests and data disclosures before beta claims.
5. **Release and customer setup.** Build and inspect publishable package
   artifacts, validate the public-key/manifest configuration path and minimum
   supported versions, and walk the maintained examples from install through a
   tenant-visible graph result. Package builds and examples do not substitute
   for hosted, provider-backed, or device evidence.

Track these as separate evidence: focused repository checks, hosted PR checks,
live tenant/provider proof, and device/beta proof. Do not label an SDK customer
ready or mobile beta-ready based only on package existence or `/v1/batch`
acceptance.
