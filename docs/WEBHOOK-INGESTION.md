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

- **Public external delivery** (requires `AETHER_CONNECTORS_ENABLED=true`):
  `POST /v1/integrations/webhooks/{connector_type}`
  — unauthenticated, HMAC-SHA256 verified. Tenant resolved from the
  `X-Aether-Tenant-ID` header. The connector must be enabled for that tenant
  and its secret must be configured. Required headers:
  - `X-Aether-Tenant-ID: <tenant_id>` — set when registering the webhook with the provider
  - `X-Aether-Signature: <hmac_sha256_hex>`
  - `X-Aether-Timestamp: <unix_epoch>`
  Replay prevention: 5-minute timestamp window. Duplicate `webhook_event_id` is skipped.
  This path is listed in `PUBLIC_PATH_PREFIXES` so the middleware skips API-key auth;
  security is enforced entirely by HMAC verification inside the handler.

  **Comms connectors are the exception**: they never accept a tenant header.
  Communications providers use server-controlled durable endpoint ids —
  `POST /v1/integrations/webhooks/comms/{connector}/{endpoint_id}` — resolved
  server-side (see `docs/comms/COMMS_GENERIC_WEBHOOK.md`). The header path above
  is a permanent denial for comms connectors.

- **Authenticated (testing/manual)**: `POST /v1/integrations/connectors/{type}/webhook`
  — tenant from the authenticated context; used for testing and first-party
  delivery. Verifies the signature when a secret is configured; in local/mocked
  mode it accepts and flags `verified: false`.

## Safety

- Connector must be enabled for the tenant or the webhook is rejected.
- Invalid signature → rejected + audit event (`connector_webhook_ingested`,
  outcome `blocked`).
- Accepted events are metered (`webhook_ingested`) and audited; no secrets are
  logged.

See [Connectors](CONNECTORS.md) and [Data Ingestion Paths](DATA-INGESTION-PATHS.md).
