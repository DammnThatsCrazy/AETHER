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
| **Public webhook** | Provider pushes HMAC-signed events (unauthenticated, tenant-resolved) | `POST /v1/integrations/webhooks/{connector_type}` | `webhook_ingested` |
| **Authenticated webhook** | Tenant-authenticated manual/test webhook ingest | `POST /v1/integrations/connectors/{type}/webhook` | `webhook_ingested` |
| **External API feed** | Server-to-server batch/import feeds (requires `external_id`) | `POST /v1/ingest/feed` | `event_ingested` |
| **Internal replay** | Operator replay only — `EventPipelineEnvelope` path | `POST /v1/events/ingest` | n/a |

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

## Durability and idempotency

- **SDK (`/v1/batch`)**: Events are written to Bronze before acknowledgment. Idempotency key: `SHA256(tenant_id:event_id:schema_version)` — 24-hour dedup window. Duplicate events return `status: "duplicate"` and are not re-billed.
- **Connector/webhook**: Idempotency via `tenant_id:connector_type:webhook_event_id:schema_version`.
- **Feed**: Idempotency via `tenant_id:source:external_id:schema_version`. `external_id` is required.
- **All paths**: Accepted events survive process restart via Bronze persistence or durable event bus (Kafka/SQS). In-memory event bus is blocked in staging/production.

## Deprecated routes (internal only)

```
POST /v1/ingest/events        — deprecated; server-to-server only
POST /v1/ingest/events/batch  — deprecated; server-to-server only
```

SDKs **must** use `/v1/batch`. The deprecated paths still apply tenant scoping, validation, and metering but are not part of the SDK contract.

See [Connectors](CONNECTORS.md), [Webhook Ingestion](WEBHOOK-INGESTION.md),
[SDKs](SDK-WEB.md), and [OODA & Outcome Usage Dimensions](OODA-USAGE-DIMENSIONS.md).
