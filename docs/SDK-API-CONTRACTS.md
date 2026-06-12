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
events). Each event carries an SDK-generated `id` for idempotency. The backend
validates against `packages/shared/events.ts`, enriches server-side, and publishes
to the event store. `/v1/ingest/events` and `/v1/ingest/events/batch` are reserved
for server-side ingestion/connectors and must not appear in SDK quickstarts. See
[Source of Truth: Ingestion Contract](source-of-truth/INGESTION_CONTRACT.md).

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
