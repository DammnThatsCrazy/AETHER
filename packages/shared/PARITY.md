# Aether SDK Runtime Parity Matrix

Truth Kernel §2.6 (SDK runtime parity), §2.8 (batch-response health metrics),
§2.9 (manifest signature verification).

This document is the human-readable companion to the machine-checkable
[`sdk-parity.json`](./sdk-parity.json). **`sdk-parity.json` is canonical** — a
validator reads it and fails if a cell claims `supported` while its evidence
file/symbol is missing. Keep both in sync when SDK behavior changes.

## Status legend

| Status | Meaning |
|---|---|
| `supported` | Implemented and exercised by tests in this SDK. |
| `partial` | Implemented with a documented limitation. |
| `delegated_native` | Surfaced by this SDK but enforced in the native iOS/Android layer it bridges to. |
| `not_applicable` | Out of scope for this SDK's role. |

## Capability matrix

| Capability (spec) | web | server | react-native | ios | android | python |
|---|---|---|---|---|---|---|
| observe(event) (§2.6) | supported | supported | supported | supported | supported | n/a |
| consent-gated enqueue (§2.6) | supported | partial | delegated | supported | supported | n/a |
| batching → /v1/batch (§2.6) | supported | supported | delegated | supported | supported | n/a |
| manifest fetch (§2.9) | supported | n/a | supported | supported | supported | n/a |
| manifest signature verify (§2.9) | supported | n/a | delegated | supported | supported | n/a |
| batch health metrics (§2.8) | supported | supported | supported | supported | supported | supported (parse-only) |
| retry / backoff (§2.6) | supported | supported | delegated | supported | supported | n/a |
| offline queue (§2.6) | supported | partial | delegated | supported | supported | n/a |

## Notes

- **server / consent-gating** — the server SDK tracks consent and forwards
  granted purposes to the backend as an ingestion hint; it does not drop events
  locally, so `BatchHealth.dropped_by_consent` is always `0`.
- **server / offline queue** — a bounded in-process queue with exponential
  backoff retry; there is no cross-restart disk persistence.
- **react-native** — the JS bridge exposes `observe`, `queueDepth`, and
  `onBatchResult`, but consent gating, batching, retry, offline persistence, and
  manifest signature verification are enforced in the native iOS/Android modules
  the bridge delegates to.
- **python** — an observation-envelope builder with no client-side emit
  pipeline; it can still parse the `/v1/batch` BatchResponse into a uniform
  `BatchHealth` via `parse_batch_health`.

## Batch health shape (§2.8)

Every SDK that reports batch health surfaces these five counters. `accepted` /
`duplicate` / `rejected` are parsed from the backend BatchResponse
(`packages/shared/ingestion-contract.ts`); `dropped_by_consent` and
`queue_depth` are SDK-side truths.

| Field | Source |
|---|---|
| `accepted` | BatchResponse |
| `duplicate` | BatchResponse (`duplicates` normalized to `duplicate`) |
| `rejected` | BatchResponse |
| `dropped_by_consent` | SDK-side consent gate |
| `queue_depth` | SDK-side local queue backlog |

## Manifest signature verification (§2.9)

- **Algorithm**: HMAC-SHA256 over a deterministic canonical serialization of the
  manifest (signature field excluded; top-level fields and feature keys sorted),
  hex-encoded signature, constant-time comparison.
- **Key source**: the tenant `SDK_CONFIG_SECRET`, provisioned out-of-band. On
  web/server this is `signingSecret`; on iOS/Android it is
  `AetherConfig.manifestVerificationKey`, forwarded to the health agent.
- **Fail-closed**: when a verification key is configured, an unsigned or
  invalid-signature manifest is rejected and the last-known-good manifest is
  kept. When no key is configured, the manifest is applied unverified
  (back-compat) — production tenants MUST configure a key.
