---
title: Customer.io Connector
slug: operations/customerio-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.12.0"
flags: [AETHER_CONNECTORS_ENABLED, AETHER_COMMS_INGESTION_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 3
source_files:
  - Backend Architecture/aether-backend/services/integrations/connectors/customerio.py
---

# Customer.io Connector

Observes the Customer.io email lifecycle for Communications Intelligence.
Aether never sends through this connector (ADR-C1) — Customer.io keeps
composition, scheduling, sending, and suppression execution.

- **Category**: marketing · **Webhook**: yes · **Pull**: no ·
  **Historical backfill**: no · **Premium**: no
- **Auth**: webhook-only. Inbound events are verified with the Customer.io
  HMAC-SHA256 scheme (`X-CIO-Signature` / `X-CIO-Timestamp`) over
  `v0:<ts>:` + the raw body (vault-stored webhook signing secret).
  `CREDENTIAL_GATED` until the secret is configured.

## What it ingests

| Customer.io event | Canonical event |
|---|---|
| `email_sent` | `email_sent` |
| `email_delivered` | `email_delivered` |
| `email_opened` | `email_opened` |
| `email_clicked` | `email_clicked` |
| `email_bounced` | `email_bounced` (hard/soft) |
| `email_spammed` | `email_spam_complaint` |
| `email_dropped` | `email_dropped` |
| `unsubscribed` | `unsubscribe_observed` |

Unknown Customer.io event types are skipped (no synthetic canonical event).
Recipient, campaign, and delivery ids are read from `data{email_address,
campaign_id, delivery_id, link}`; unix timestamps are converted to ISO
occurrence times.

## Enable

`PUT /v1/integrations/connectors/customerio` (`enabled: true`) → point the
provider's webhook at the server-controlled endpoint
(`POST /comms/customerio/{endpoint_id}`). Configure the webhook signing
secret in the connector vault, then
`POST /comms/customerio/{endpoint_id}/test` for the verification probe.
Webhooks land on the connector webhook route and flow through the durable
Bronze → Silver pipeline. See [Connectors](CONNECTORS.md) and
[Communications Intelligence Overview](comms/COMMUNICATIONS_INTELLIGENCE_OVERVIEW.md).
