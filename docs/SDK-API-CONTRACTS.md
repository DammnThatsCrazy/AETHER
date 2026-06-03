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

SDKs batch events and POST to `/v1/ingest/events` (single) and
`/v1/ingest/events/batch` (1–500). Each event carries an `event_id` (idempotency).
The backend validates, enriches, and publishes to the event store. See
[Data Ingestion Paths](DATA-INGESTION-PATHS.md).

## Config contract

SDKs fetch a signed manifest from `/v1/config/sdk/manifest` (min SDK version,
schema version, rollout %, feature flags, endpoint overrides) and report health;
drift is tracked server-side (`sdk_drift`, `sdk_health`).

## Versioning

Contracts are versioned with the monorepo; breaking changes bump `schema_version`
in the manifest and follow the [SDK Release Checklist](SDK-RELEASE-CHECKLIST.md).

See [SDKs](SDKS.md) and [Event Schema Reference](EVENT-SCHEMA-REFERENCE.md).
