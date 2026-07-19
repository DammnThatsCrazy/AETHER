---
title: SDK API Contracts
slug: api/sdk-api-contracts
section: api
visibility: I
audience: [dev-senior, architect]
status: beta
since_version: "8.9.0"
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
plane wire format. All schemas live in `frontend/kyber/src/lib/schemas/` and
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
Wire format mirrors backend Pydantic models in `services/x402/commerce_models.py`.
Breaking changes to backend models require coordinated updates to both files.
