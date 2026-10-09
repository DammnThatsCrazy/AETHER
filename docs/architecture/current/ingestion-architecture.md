---
title: "Ingestion Architecture"
slug: architecture/current/ingestion-architecture
section: architecture
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# Ingestion Architecture

## Entry Points

`POST /v1/batch` is the first-party SDK entry point (`services/backend/services/ingestion/batch.py`). Other sources have their own authenticated or verified entry paths:

- API feeds use `POST /v1/ingest/feed` (`services/backend/services/ingestion/routes.py`). The deprecated `/v1/ingest/events` aliases forward SDK events to the batch V1 ingestion function.
- Imports use the `/v1/imports` upload, validation, approval, and commit workflow (`services/backend/services/imports/routes.py`); commit enqueues an `import.commit` job.
- The Universal Provider Runtime uses `POST /v1/provider-connections/{connection_id}/sync` for tenant-initiated pulls and `POST /v1/provider-webhooks/{identity_key}` for provider deliveries when that runtime is enabled (`services/backend/services/provider_runtime/routes.py`). The public webhook route verifies provider credentials or signatures inside its gateway; a tenant header is only a routing hint.
- Legacy connectors continue to use `POST /v1/integrations/connectors/{connector_type}/sync` and verified `POST /v1/integrations/webhooks/{connector_type}` (`services/backend/services/integrations/connectors/routes.py`).

## Pipeline

These are processing stages, not one shared durable route for every source:

1. Source-specific authentication or webhook verification, contract checks, consent, privacy, and applicable data-rights decisions.
2. Accepted evidence is persisted through the source's Bronze path. SDK batch V1 uses `BronzeRepository("sdk_events")`; flag-enabled SDK V2 uses a typed Bronze and outbox transaction. Feeds, imports, and providers have distinct persistence mechanics.
3. Supported events are normalized into Silver facts and passed to backend identity resolution. A source family without a projector does not acquire fact, entity, or graph authority merely by being ingested.
4. Supported graph writers express governed mutations through `MutationIntent` and `GraphMutationGateway.apply`; outbox delivery and gateway enforcement depend on the specific path and rollout mode.

## Sources

- SDK observations (first-party)
- API feeds and reviewed imports
- Connector events (third-party provider data)
- Webhook payloads (verified provider webhooks)
- System events (internal runtime events)

## Current State

SDK, feed, import, and provider ingestion paths exist, with contract validation, Bronze persistence, Silver normalization, and identity resolution implemented for supported event families. `services/backend/services/ingestion/gateway.py` currently validates and stamps the universal observation envelope, but its consent, idempotency, sequencing, and durable-write gates are still adopted per path; SDK use of that envelope is flag-gated. There is not yet one canonical durable ingress path for every source.

[PR #733](https://github.com/DammnThatsCrazy/AETHER/pull/733), currently separate from this checkout, proposes provider raw-rights admission, source-revision handling, a canonical Bronze/outbox bridge, and provider replay. Those pending changes must be integrated and verified before this page can describe them as current behavior.
