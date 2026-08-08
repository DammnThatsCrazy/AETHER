---
title: Connectors
slug: operations/connectors
section: operations
visibility: I
audience: [architect, dev-senior, ops]
status: beta
since_version: "8.9.0"
flags:
  - AETHER_CONNECTORS_ENABLED
  - KYBER_CONNECTOR_HEALTH_ENABLED
canonical_owner: platform@aether
estimated_read_minutes: 6
---

# Connectors

Aether enriches the intelligence graph from **SDKs or direct platform
connectors** — the SDK is not required. Connectors are inbound adapters that
pull or receive events from external SaaS platforms and normalize them into the
Aether event envelope.

## Framework

`services/integrations/connectors/` provides:
- `BaseConnector` — descriptor + `test_connection` + `pull` + `parse_webhook`.
- 14 adapters (`adapters.py`), registered in `registry.py`.
- `ConnectorService` (`service.py`) — tenant-scoped config, connection test,
  sync, and authenticated webhook ingest, with best-effort **audit** (audit
  ledger), **metering** (`connector_sync`, `webhook_ingested`), and sync-status
  health. Secrets are never persisted in config or returned by the API.

## Feature flags (default OFF)

| Flag | Effect |
| --- | --- |
| `AETHER_CONNECTORS_ENABLED` | Mounts `/v1/integrations/connectors/*` |
| `KYBER_CONNECTOR_HEALTH_ENABLED` | Mounts `/v1/admin/kyber/connectors/*` (aggregate) |

Per-connector enablement is **per-tenant config** (also off by default). Provider
credentials are required only when a connector is enabled for a tenant.

## Available connectors

Messaging: Slack · Webhook (generic signed) · Commerce: Shopify · Billing:
Stripe · CRM: HubSpot, Salesforce · Marketing: Klaviyo · Product analytics:
Segment, PostHog, GA4 · Project: Jira, Linear · Support: Zendesk, Intercom.

See per-connector pages: [Slack](SLACK-CONNECTOR.md),
[Webhook](WEBHOOK-INGESTION.md), [Shopify](SHOPIFY-CONNECTOR.md),
[Stripe](STRIPE-CONNECTOR.md), [HubSpot](HUBSPOT-CONNECTOR.md),
[Salesforce](SALESFORCE-CONNECTOR.md), [Klaviyo](KLAVIYO-CONNECTOR.md),
[Segment](SEGMENT-CONNECTOR.md), [PostHog](POSTHOG-CONNECTOR.md),
[GA4](GA4-CONNECTOR.md), [Jira & Linear](JIRA-LINEAR-CONNECTORS.md),
[Zendesk & Intercom](ZENDESK-INTERCOM-CONNECTORS.md).

## Routes

- Tenant: `GET /v1/integrations/connectors`, `GET/PUT /{type}`,
  `POST /{type}/test`, `POST /{type}/sync`, `POST /{type}/webhook` (authenticated).
- Kyber: `GET /v1/admin/kyber/connectors/overview` (aggregate-only, operator-gated).

## Outbound delivery capabilities (9.1.0+)

Connectors now support bidirectional operation:

- **Slack, Linear, Jira** — full outbound delivery: `DeliveryWorker` calls the concrete provider API, persists a `ProviderReceipt` with a real `external_id`, and creates an `ExternalResourceLink`. Provider webhooks feed back as `ExternalOutcomeEvent` records that update the suggestion outcome state and emit graph edges.
- **Generic signed webhook** — versioned, HMAC-SHA256-signed outbound POST. Outcome callbacks return via `POST /v1/webhooks/aether/callback`.
- **CRM / Marketing** — fail-closed. Require a concrete `crm_provider` / `marketing_provider` config; planned for a future release.
- **Agent Assist** — publishes a Kafka `AGENT_ASSIST_ACTION_QUEUED` event and records a receipt with an internal `agent-assist:{id}` external ID.

All inbound webhook routes persist to `WebhookInbox` before any business processing. Provider-native signature verification is enforced for every connector that supports signed webhooks. See [Connector Support Matrix](CONNECTOR-SUPPORT-MATRIX.md).

## Delivery runbooks

- [Delivery Failures](runbooks/DELIVERY-FAILURES.md)
- [Credential Rotation](runbooks/CREDENTIAL-ROTATION.md)
- [Reconciliation](runbooks/RECONCILIATION.md)

## Implementation status

Inbound adapters: connector config, connection test, sync, webhook parsing, audit/metering/health hooks, and `WebhookInbox` persistence are fully implemented. Real provider API calls require credentials. See [Data Ingestion Paths](DATA-INGESTION-PATHS.md).

Outbound adapters: Slack, Linear, Jira, and signed webhook are **release-ready** (readiness scorecard 4/5 for connectors). The canonical readiness authority is `make production-status`; connector readiness is not a claim that live provider sends are certified with production credentials or that the platform is production + scale ready (5/5) overall. See [Connector Support Matrix](CONNECTOR-SUPPORT-MATRIX.md).
