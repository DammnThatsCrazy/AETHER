---
title: Event Schema Reference
slug: api/event-schema-reference
section: api
visibility: I
audience: [dev-senior, ai, architect]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Event Schema Reference

Canonical event contracts live in `packages/shared` (events, consent, identity,
wallet, commerce, agent) and are mirrored into the generated artifacts
(`docs/_generated/events.json`, `consent.json`), validated cross-file by
`scripts/validate_contracts.py`.

## Ingestion envelope

SDK and connector events normalize to: `event_id`, `tenant_id`, `event_type`,
`session_id`, `user_id?`, `device_id?`, `properties`, `timestamp`,
`ingested_at`, plus IP enrichment. See [Data Ingestion Paths](DATA-INGESTION-PATHS.md)
and [SDK Event Schemas](SDK-EVENT-SCHEMAS.md).

## Consent mapping

Event families map to consent purposes (analytics / marketing / commerce / web3 /
agent); events outside the map are always allowed. The mapping is enforced in the
SDK and validated against the canonical consent set.

See [API Reference](API-REFERENCE.md) and [SDK API Contracts](SDK-API-CONTRACTS.md).
