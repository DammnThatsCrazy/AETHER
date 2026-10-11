---
title: SDK Intake Productization
slug: sdk-parity-productization
section: architecture
visibility: I
audience: [architect, dev-senior, product]
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
| Remote SDK manifest | Fetches, verifies, and applies manifest configuration | No manifest client established | Fetches and applies manifest values to JS feature flags, sampling, and endpoint overrides; signature verification is owned by native code | Fetches and applies manifest; signature verification is supported when configured | Fetches and applies manifest; signature verification is supported when configured |

The code supports useful features on every client family, but there is no
single cross-platform conformance fixture proving API, consent, schema,
retry/idempotency, and failure-outcome parity. Package presence and local
source-level behavior do not establish publish readiness or customer graph
hydration.

Primary inspection points include `packages/sdk/web/src/index.ts`,
`packages/sdk/server/src/index.ts` and `durable-queue.ts`,
`packages/sdk/react-native/src/bridge.ts` and `modules/RemoteManifest.ts`,
`packages/sdk/ios/Sources/AetherSDK/Aether.swift` and `AetherHealthAgent.swift`,
and `packages/sdk/android/src/main/java/com/aether/sdk/Aether.kt` and
`AetherHealthAgent.kt`.

## Remaining work and proof gates

1. **Shared contract conformance.** Define a versioned fixture set consumed by
   each supported SDK implementation. Cover canonical event typing, envelope
   fields, server-owned tenant/site scope, consent gating, stable retry identity,
   and parsing of accepted, duplicate, rejected, and transport-failure outcomes.
   Keep platform-specific APIs where appropriate; prove their wire behavior
   against the same contract rather than requiring identical surface methods.
2. **V1/V2 intake proof.** Exercise both route branches with the envelope and
   gateway flags off and on. Retain evidence for additive payload compatibility,
   gateway acceptance/stamping, gateway rejection degradation, transactional
   Bronze/outbox idempotency, and retry after publish or relay failure. The code
   change that aligned Envelope-B emission is not itself execution evidence.
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
