---
title: SDK API Contracts
slug: api/sdk-api-contracts
section: reference
visibility: I
audience: [dev-senior, architect]
status: beta
since_version: 0.1.0
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# SDK API Contracts

The SDKs and backend share a single source of truth: `packages/shared`
(`@aether/shared`). All SDKs (Web/RN/iOS/Android) and the backend use the same
event, consent, identity, wallet, and commerce contracts so payloads round-trip.

## Ingestion contract

SDKs batch canonical event envelopes and POST to `POST /v1/batch` (1–500
events). The batch body is the canonical envelope `{ batch: [...], sentAt, consents? }`
(the field is `batch`, not `events`). Each event carries an SDK-generated `id`
for idempotency. API keys are sent in the `Authorization: Bearer <key>` header —
never in a query string. The backend validates against `packages/shared/events.ts`,
enriches server-side, and publishes to the event store. `/v1/ingest/events` and
`/v1/ingest/events/batch` are reserved for server-side ingestion/connectors and
must not appear in SDK quickstarts. See
[Source of Truth: Ingestion Contract](source-of-truth/INGESTION_CONTRACT.md).

## SDK identify retries

`POST /sdk/identify` requires a caller-supplied `idempotency_key` (1–255
characters). The backend scopes it to the authenticated tenant and fingerprints
the complete identify payload, including traits and consent assertions. Reusing
the key with a changed payload returns HTTP 409. Concurrent requests with the
same payload receive an `idempotency_status` of `in_progress`; after a completed
request, an identical retry receives the stored outcome with status `replayed`.
The response retains the submitted user and anonymous identifiers, while the
durable result record stores no traits or caller identifiers.

An interrupted request remains pending and is not automatically re-executed:
the identity repository and event broker do not share a transaction or durable
outbox for this route, so the server cannot safely tell whether every side
effect committed before a crash. In that case retries remain `in_progress` and
do not duplicate observations, merge decisions, restatement jobs, or event
publication. After 15 minutes without a state update, retries return
`idempotency_status: stale` with an explicit reconciliation reason. This age
check is a stale-state signal, not proof that the original worker has stopped.
An operator must inspect the durable claim, identity audit/source evidence,
restatement job, and broker publication evidence before handling the outcome.
The claim remains blocked; there is no automatic replay or claim-clear operation
in this slice. This is duplicate prevention with an explicit indeterminate
state, not restart recovery or an exactly-once delivery guarantee.
Database-backed deployments use the durable SQL table; local mode without a
database uses the repository's process-local memory backend and does not survive
a process restart.

The supported Web, Server, iOS, and Android SDK identity hydration methods emit
an `identify` event through `POST /v1/batch`; they do not call
`POST /sdk/identify`. Each emitted identify event carries
`properties.idempotency_key`, set to that event's top-level `id`. The event and
key are queued together, so retries and durable queue replay preserve the key;
a later hydration call creates a new event ID and key. React Native delegates
hydration to its native iOS/Android implementation. The Server SDK supports
identify events through `track({ type: 'identify', ... })`, not a dedicated
identity method. Batch event idempotency is governed by the top-level event ID;
the property does not replace the required request-body key for direct calls to
`POST /sdk/identify`.

For `/v1/batch`, the backend deduplicates canonical identify resolution using
the tenant-scoped top-level event ID claim. V1 uses Redis `SET NX` with a
24-hour TTL; it fails closed for identify events when that claim store is
unavailable. The resolver is scheduled only after the event claim succeeds and
the batch publish returns successfully, so a normal SDK retry cannot repeat
that resolver mutation. V1 does not persist a resolver work receipt: a process
failure after publish but before task scheduling, or a resolver error, can leave
the event accepted without a confirmed canonical resolution. The SDK queue key
does not provide exactly-once delivery or a durable resolver retry guarantee.

When ingestion V2 is enabled, the batch path persists Bronze and one outbox row
transactionally under the unique tenant/event/schema key. Outbox delivery is
at-least-once, so downstream consumers must tolerate replay. Neither path treats
the client property as authority independent of the event ID.

When the direct endpoint finds imported identity candidates, a `candidate` or
`blocked` result stops before canonical resolution. This prevents the fallback
create path from producing a second profile while imported evidence is awaiting
safe resolution. The backend upserts a tenant-scoped item in the admin identity
review queue using source-identity references and metadata-only evidence. It
does not store contact values in the queue. These late-binding entries are
review context only: approve/reject actions do not resolve them, and tenant
review or SDK consent assertions cannot authorize a link. A future link still
requires server-authoritative person-level consent and resolver policy. The
tenant-scoped `/v1/admin/identity/review-queue/{conflict_id}` detail response
identifies these as `late_binding_candidate`, includes source references,
reason codes, hashed evidence metadata and `authority: none`, and never returns
contact values or canonical entity IDs for those candidates.

Identity runtime rollout is controlled by `IDENTITY_RESOLUTION_ENABLED`,
`SDK_LATE_BINDING_ENABLED`, `ANONYMOUS_TO_KNOWN_BINDING_ENABLED`, and
`CONNECTOR_BACKFILL_IDENTITY_RESOLUTION_ENABLED` in the canonical identity
configuration. When identity resolution or SDK late binding is disabled, direct
SDK identify returns a blocked outcome before creating identity evidence. The
batch path accepts the event but does not schedule canonical identify resolution
when the overall resolver, SDK late binding, or connector backfill resolution is
disabled; the batch path has no safe connector-candidate review context yet. The legacy
`/sdk/alias` route reports `aliased: false` when anonymous-to-known binding is
disabled. Staging enables the proof controls; the production-lean profile keeps
them off.

Identity runtime rollout is controlled by `IDENTITY_RESOLUTION_ENABLED`,
`SDK_LATE_BINDING_ENABLED`, `ANONYMOUS_TO_KNOWN_BINDING_ENABLED`, and
`CONNECTOR_BACKFILL_IDENTITY_RESOLUTION_ENABLED` in the canonical identity
configuration. When identity resolution or SDK late binding is disabled, direct
SDK identify returns a blocked outcome before creating identity evidence. The
batch path accepts the event but does not schedule canonical identify resolution
when the overall resolver, SDK late binding, or connector backfill resolution is
disabled; the batch path has no safe connector-candidate review context yet. The legacy
`/sdk/alias` route reports `aliased: false` when anonymous-to-known binding is
disabled. Staging enables the proof controls; the production-lean profile keeps
them off.

**Emission API.** Official helpers emit **canonical top-level event types** via
the low-level `observe(type, properties)` API (available on Web, Server, and —
bridged — the native SDKs). `track(event, properties)` is reserved for custom
application events (top-level type `track`, name in `properties.event`) and must
not be used for canonical events. Canonical types and their required consent
purposes are registry-derived from `packages/shared/contracts/event-registry.json`.

**Health / manifest endpoints.** Canonical SDK health is
`POST /v1/diagnostics/sdk/heartbeat`; canonical manifest is
`GET /v1/config/sdk/manifest`. The retired `/v1/sdk/health` route and any
`?apiKey=` query-string form must not be used.

**Server SDK.** `@aether/server` is release-supported and version-aligned with
the monorepo. It sends the same canonical `{ batch, sentAt, consents }` envelope
with the write key in the `Authorization` header, with retry/backoff and safe
shutdown flush.

## Canonical consent receipt API

The shared, Web, React Native, iOS, and Android SDK surfaces can build the same
deterministic `CanonicalConsentReceipt` accepted by
`POST /v1/consent/records`. Web and React Native expose
`consent.recordReceipt(input)`; the native SDKs expose
`buildCanonicalConsentReceipt` for local construction and
`recordConsentReceipt` for authenticated persistence.

Receipt inputs include the authenticated `tenant_id`/`tenantId`, at least one
subject or anonymous identifier, one or more canonical purposes, state, source,
and policy version. The API sends the legacy compatibility fields alongside the
additive `canonical_receipt` envelope. Purpose order and duplicates are
normalized before hashing, optional fields remain empty in the preimage, UTF-8
byte length is used, and metadata keys are recursively sorted. The resulting
`sha256:` integrity hash deterministically derives the `ccr_` receipt ID and
`consent-receipt:` idempotency key. The backend recomputes all three and rejects
tenant mismatches or mutated evidence.

## Canonical envelope context (v1)

Every event carries a `context` object (`EventContext` in
`packages/shared/events.ts`). Beyond the core fields (library, page, device,
campaign, consent, provenance, journey, temporal provenance), SDKs MAY stamp the
optional **canonical envelope context v1** fields so the backend can attribute,
correlate, order, and quality-score any event without per-surface parsing. All
fields are optional and additive — existing SDKs and stored events keep
validating unchanged.

| Field | Shape | Purpose |
|---|---|---|
| `schemaVersion` | `string` | Envelope schema version the emitter conforms to. |
| `application` | `ApplicationContext` | Emitting product identity (name/version/build/environment/namespace) — distinct from the Aether `library`. |
| `surface` | `string` | Origin plane, e.g. `web`, `server`, `ios`, `home_feed`. |
| `operatingSystem` | `OperatingSystemContext` | OS name/version of the emitting device/host. |
| `network` | `NetworkContext` | Connection conditions at occurrence (effectiveType/downlink/rtt/saveData; mobile fills connectionType/carrier). |
| `semanticInput` | `SemanticInputContext` | Client-declared semantic input — a hint the backend MAY enrich; never authoritative (consent + classifier run first). |
| `semanticHints` | `SemanticHints` | Advisory `intent`/`friction`/`engagement` signals the backend reducers MAY weight. |
| `sampling` | `SamplingContext` | Client-side sampling decision (sampled/rate/reason). |
| `correlation` | `CorrelationContext` | Tracing/causation linkage (correlationId/causationId/traceId/spanId). |
| `dataQuality` | `DataQualityRecord` | Client-declared completeness/freshness/sourceTrust signals. |
| `sequence` | `SequenceContext` | Monotonic per-session event and per-install session counters for gap/reorder detection. |

The envelope types are exported from the `@aether/shared` barrel. Because every
field is optional, the backend treats them as hints layered on top of its own
server-authoritative enrichment, consent, and classification.

## Config contract

SDKs fetch a signed manifest from `/v1/config/sdk/manifest` (min SDK version,
schema version, rollout %, feature flags, endpoint overrides) and report health;
drift is tracked server-side (`sdk_drift`, `sdk_health`).

## Versioning

Contracts are versioned with the monorepo; breaking changes bump `schema_version`
in the manifest and follow the [SDK Release Checklist](SDK-RELEASE-CHECKLIST.md).

See [SDKs](SDKS.md) and [Event Schema Reference](EVENT-SCHEMA-REFERENCE.md).

## Journey lifecycle API

All SDKs expose platform-idiomatic equivalents of:

```ts
startJourney(nameOrType, properties?)
pauseJourney(reason?, properties?)
resumeJourney(reason?, properties?)
continueJourney(stepIdOrName, properties?)
completeJourney(reason?, properties?)
abandonJourney(reason?, properties?)
checkpointJourney(stepIdOrName, properties?)
getCurrentJourney()
onJourneyResumed(callback)
```

These APIs emit the canonical `journey_*` event family. Existing legacy `track` calls
with journey lifecycle names remain accepted during migration, but new SDK behavior must
prefer first-class `journey_*` event types so validators do not drop `journey_resumed`.

## Kyber Commerce Domain Schemas (v8.9.0)

The Kyber operator UI exposes modular Zod schema modules mirroring the x402 control
plane wire format. All schemas live in `apps/kyber-web/src/lib/schemas/` and
re-export from the consolidated `commerce.ts` module for tree-shaking:

| Module | Key exports |
|---|---|
| `schemas/approvals.ts` | `approvalRequestSchema`, `evidenceBundleSchema`, `ApprovalRequest`, `EvidenceBundle` |
| `schemas/entitlements.ts` | `entitlementSchema`, `Entitlement`, `EntitlementStatus` |
| `schemas/resources.ts` | `protectedResourceSchema`, `preflightResultSchema`, `ProtectedResource`, `PreflightResult` |
| `schemas/settlement.ts` | `settlementSchema`, `Settlement`, `SettlementState` |
| `schemas/policies.ts` | `policyDecisionSchema`, `PolicyDecision`, `PolicyOutcome` |
| `schemas/facilitators.ts` | `facilitatorSchema`, `stablecoinAssetSchema`, `Facilitator`, `StablecoinAsset` |

These schemas validate all responses from `/v1/x402/*`, `/v1/approvals/*`,
`/v1/entitlements/*`, and `/v1/diagnostics/commerce/*` at the network boundary.
Wire format mirrors backend Pydantic models in `services/api/value/x402/commerce_models.py`.
Breaking changes to backend models require coordinated updates to both files.
