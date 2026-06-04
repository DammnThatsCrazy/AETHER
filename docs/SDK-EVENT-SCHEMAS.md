---
title: SDK Event Schemas
slug: sdks/sdk-event-schemas
section: sdks
visibility: I
audience: [dev-senior, ai]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# SDK Event Schemas

SDK events conform to the shared event contracts (`packages/shared/events.ts`),
the same set the backend validates and the generated `docs/_generated/events.json`
indexes.

## Envelope

`event_type`, `session_id`, `properties`, `timestamp?`, `user_id?`, `device_id?`
— normalized server-side to add `event_id`, `tenant_id`, `ingested_at`, and IP
enrichment.

## Families & consent

Events belong to declared families and map to consent purposes (analytics /
marketing / commerce / web3 / agent). The SDK gates capture by consent; events
outside the map are always allowed. Cross-file consistency is enforced by
`scripts/validate_contracts.py`.

## Versioning

The active `schema_version` is delivered via the signed SDK manifest; breaking
schema changes bump it and follow the [SDK Release Checklist](SDK-RELEASE-CHECKLIST.md).

See [Event Schema Reference](EVENT-SCHEMA-REFERENCE.md) and [SDKs](SDKS.md).
