# SDK Runtime Parity — Source of Truth

Every Aether SDK must expose the same canonical runtime surface so that what a
subject observes, consents to, and has counted is identical regardless of
platform. Parity is enforced grep-based by `scripts/validate_sdk_parity.py`
(there are no generated native registries — a Truth Kernel non-goal); if an SDK
legitimately lacks a capability, the validator is updated in the same change.

## Canonical `observe()` (§2.6)

The canonical event-capture entry point is `observe(type, properties)`. It is a
client-capture surface present on **web**, **iOS**, **Android**, and
**React Native**. It ignores non-canonical event types and never sets
`execution_by_aether` (Aether observes, it never executes). The **server** SDK
captures via `track()` and is exempt from `observe()`.

| SDK | Entry point |
|---|---|
| web | `AetherClient.observe(type, properties)` |
| iOS | `func observe(_ type: String, properties:)` |
| Android | `fun observe(type: String, properties:)` |
| React Native | `observe(type, properties)` → bridged to native |
| server | `track(event)` (server-side capture) |

## Manifest signature verification (§2.9)

iOS and Android verify a fetched remote SDK manifest before applying it. When a
verification key is configured, an unsigned or invalid-signature manifest is
**rejected** and the SDK keeps last-known-good config (fail closed). Verification
is HMAC-SHA256 over the manifest's canonical serialization (signature field
excluded), compared constant-time; an empty signature or empty key verifies as
false. The entry point is `verifyManifestSignature(manifest, key)` on both
platforms' health agents.

## Batch-response health metrics (§2.8)

The batch-ingest response is surfaced to SDK consumers as a health record with
five counters:

- `accepted`, `duplicate`, `rejected` — parsed from the backend `BatchResponse`
  (`packages/shared/ingestion-contract.ts`);
- `dropped_by_consent` — events removed by SDK-side consent gating before they
  leave the device;
- `queue_depth` — the local queue backlog after the batch is sent.

| SDK | Surface |
|---|---|
| server | `BatchHealth` type (`dropped_by_consent`, `queue_depth`) |
| web | batch health on the flush result (`dropped_by_consent`, `queue_depth`) |
| iOS | `BatchHealth` struct + `onBatchResult` callback (`droppedByConsent`, `queueDepth`) |
| Android | `data class BatchHealth` + `onBatchResult` (`droppedByConsent`, `queueDepth`) |
| Python | `parse_batch_health(...)` (`dropped_by_consent`, `queue_depth`) |

## Gate

`scripts/validate_sdk_parity.py` runs in `make ci-check` via
`scripts/repo_doctor.py`. It greps each SDK subtree for the canonical tokens
above and fails if a required capability is absent. It also derives the
cross-SDK conformance matrix via `scripts/release/sdk_conformance.py`: every
claimed capability cell in `packages/shared/sdk-parity.json` must verify
against its declared evidence file/symbol on disk (fail-closed — a claim whose
evidence is absent fails the gate). The same derivation, including each SDK's
real test-manifest inventory, is embedded in the release evidence bundle by
`scripts/release/collect_evidence.py`.
## Durable native delivery queues

iOS and Android persist bounded, versioned queue envelopes with atomic file
replacement. They restore the queue after process restart and quarantine corrupt
state instead of crashing or silently accepting it. Flush removes a batch
atomically; exhausted `429`, `408`/`425`, and `5xx` deliveries are requeued,
while terminal client errors are dropped. The queue remains capped to prevent
unbounded device storage. The parity validator checks the durability and
transient-retry contract — including that `408 Request Timeout` and
`425 Too Early` are retryable, not silent data loss — on both native
implementations.

## Canonical envelope emission

Every SDK stamps the canonical envelope context v1 fields it has a genuine
source for (`packages/shared/events.ts`; backend acceptance pinned by
`tests/unit/test_ingestion_envelope_context.py`):

| SDK | Emits |
|---|---|
| web | `surface: 'web'`, `schemaVersion` (synced literal), `operatingSystem`, `application` (config), `sequence.event`, journey snapshot on every event |
| server | `surface: 'server'`, `schemaVersion` (shared import), `operatingSystem` (host OS), `application` (config), `sequence.event` |
| iOS | `sequence.event` (per-session, reset on rotation), journey block on every event, 11-purpose consent map |
| Android | `sequence.event` (per-session, reset on rotation), journey block on every event, 11-purpose consent map |

`sequence.event` is a monotonic per-session (native) / per-instance (TS)
counter for backend gap/reorder detection.

## Privacy parity

- **Recursive scrubbing** — sensitive-field redaction recurses into nested
  objects/maps and arrays on web, server, iOS, and Android (depth-capped,
  non-mutating). Top-level-only scrubbing leaks nested secrets and fails the
  gate.
- **Gated fingerprinting** — iOS stamps a device fingerprint only under
  analytics consent (gdprMode) AND — when `respectATT` is enabled — an
  `.authorized` App Tracking Transparency status (`gatedFingerprint`). Android
  gates stamping on analytics consent under gdprMode. Web gates on
  personalization consent.
- **App Store privacy manifest** — the iOS package ships
  `PrivacyInfo.xcprivacy` (tracking, accessed-API reasons, collected data
  types), bundled via `Package.swift` resources; presence is validated by the
  gate.
- **Canonical-id semantic collection** — the web and React Native semantic
  collectors consume canonical session/event ids passed by the caller and never
  mint their own.
