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

## Implementation status

These are **production-shaped, disabled-by-default adapters**: config,
connection test, sync, webhook parsing, and the audit/metering/health hooks are
implemented and mocked locally; real provider API calls are credential-gated
TODOs noted in each adapter. See [Data Ingestion Paths](DATA-INGESTION-PATHS.md).
