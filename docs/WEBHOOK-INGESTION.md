---
title: Webhook Ingestion
slug: operations/webhook-ingestion
section: operations
visibility: I
audience: [dev-senior, security, ops]
status: beta
since_version: "8.9.0"
flags:
  - AETHER_CONNECTORS_ENABLED
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Webhook Ingestion

The generic **signed webhook** connector ingests events from any system via an
HMAC-signed POST. It is also the verification primitive shared by other
connectors (Slack, Stripe, Segment, …).

## Signature scheme

HMAC-SHA256 over `"{timestamp}." + body`, verified by
`services/security/integration_security.verify_signature` with a ±5-minute
tolerance. Headers: `X-Aether-Timestamp`, `X-Aether-Signature` (`v1=...`).
Secrets are generated via `generate_webhook_secret()` and stored in the vault —
never in connector config or API responses.

## Endpoints

- **Authenticated (shipped today)**: `POST /v1/integrations/connectors/{type}/webhook`
  — tenant from the authenticated context; used for testing and first-party
  delivery. Verifies the signature when a secret is configured; in local/mocked
  mode it accepts and flags `verified: false`.
- **Public external delivery (activation step)**: a production
  `POST /v1/integrations/webhooks/{connector}` endpoint (unauthenticated,
  HMAC-verified, tenant resolved from the signature/route) is a credential-gated
  TODO — it requires adding the path to the middleware `PUBLIC_PATHS` allowlist
  and per-tenant routing. Disabled by default.

## Safety

- Connector must be enabled for the tenant or the webhook is rejected.
- Invalid signature → rejected + audit event (`connector_webhook_ingested`,
  outcome `blocked`).
- Accepted events are metered (`webhook_ingested`) and audited; no secrets are
  logged.

See [Connectors](CONNECTORS.md) and [Data Ingestion Paths](DATA-INGESTION-PATHS.md).
