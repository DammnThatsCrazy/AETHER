---
title: SendGrid Connector
slug: operations/sendgrid-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.12.0"
flags: [AETHER_CONNECTORS_ENABLED, AETHER_COMMS_INGESTION_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 3
source_files:
  - Backend Architecture/aether-backend/services/integrations/connectors/sendgrid.py
---

# SendGrid Connector

Observes the SendGrid (Twilio) email lifecycle for Communications
Intelligence. Aether never sends through this connector (ADR-C1) — SendGrid
keeps composition, scheduling, sending, templates, and suppression
execution.

- **Category**: marketing · **Webhook**: yes · **Pull**: no ·
  **Historical backfill**: no · **Premium**: no
- **Auth**: webhook-only. Inbound events are verified with the SendGrid
  ECDSA signature (`X-Twilio-Email-Event-Webhook-Signature` /
  `X-Twilio-Email-Event-Webhook-Timestamp`) against the account public key
  (vault-stored). `CREDENTIAL_GATED` until the signing key is configured.

## What it ingests

| SendGrid event | Canonical event |
|---|---|
| `processed` | `email_processed` |
| `deferred` | `email_deferred` |
| `delivered` | `email_delivered` |
| `open` | `email_opened` |
| `click` | `email_clicked` |
| `bounce` | `email_bounced` (hard/soft from SMTP status) |
| `dropped` | `email_dropped` |
| `spamreport` | `email_spam_complaint` |
| `unsubscribe` / `group_unsubscribe` | `unsubscribe_observed` (scoped) |

Event records are keyed by `sg_event_id` with the recipient `email`; click
evidence (`url`, `useragent`) is extracted into link and user-agent
properties. Events are deduplicated by the namespaced `sendgrid:<sg_event_id>`
id at ingest.

## Enable

`PUT /v1/integrations/connectors/sendgrid` (`enabled: true`) → point the
provider's webhook at the server-controlled endpoint
(`POST /comms/sendgrid/{endpoint_id}`). Configure the ECDSA verification
key in the connector vault, then `POST /comms/sendgrid/{endpoint_id}/test`
for the verification probe. Webhooks land on the connector webhook route and
flow through the durable Bronze → Silver pipeline. See
[Connectors](CONNECTORS.md) and
[Communications Intelligence Overview](comms/COMMUNICATIONS_INTELLIGENCE_OVERVIEW.md).
