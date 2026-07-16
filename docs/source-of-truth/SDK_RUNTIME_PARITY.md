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
atomically; exhausted `429` and `5xx` deliveries are requeued, while terminal
client errors are dropped. The queue remains capped to prevent unbounded device
storage. The parity validator checks the durability and transient-retry contract
on both native implementations.
