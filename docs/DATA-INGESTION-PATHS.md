---
title: Data Ingestion Paths
slug: operations/data-ingestion-paths
section: operations
visibility: I
audience: [architect, dev-senior, ops, ai]
status: stable
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Data Ingestion Paths

Aether supports multiple ingestion paths into the intelligence graph. **The SDK
is one option, not a requirement.**

| Path | How | Endpoint | Metering dimension |
| --- | --- | --- | --- |
| **SDK** | Web/iOS/Android/React Native SDK batches events | `POST /v1/batch` | `sdk_event_ingested` |
| **Connector pull** | Provider sync (Shopify, HubSpot, GA4, …) | `POST /v1/integrations/connectors/{type}/sync` | `connector_sync` |
| **Signed webhook** | Provider/system pushes HMAC-signed events | `POST /v1/integrations/connectors/{type}/webhook` (auth) / public endpoint | `webhook_ingested` |
| **External API feed** | Batch/import feeds | `POST /v1/ingest/feed` | `event_ingested` |
| **Manual / demo** | Synthetic/seeded events | Demo seed (Phase 3) | n/a |

## Normalization

All paths normalize to the Aether event envelope (`event_type`, `source`,
`external_id`, `occurred_at`, `properties`) and are tenant-scoped. Connector
events are mapped per provider (`BaseConnector.parse_webhook` / `pull`).

## Choosing a path

- Use the **SDK** for first-party web/app telemetry (identity, consent,
  device, wallet signals).
- Use **connectors/webhooks** to enrich the graph from existing SaaS systems
  with no code change in the customer's app.
- Both can run together; events de-duplicate via `external_id`/event identity.

See [Connectors](CONNECTORS.md), [Webhook Ingestion](WEBHOOK-INGESTION.md),
[SDKs](SDK-WEB.md), and [OODA & Outcome Usage Dimensions](OODA-USAGE-DIMENSIONS.md).
