---
title: Postmark Connector
slug: operations/postmark-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.12.0"
flags: [AETHER_CONNECTORS_ENABLED, AETHER_COMMS_INGESTION_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 3
source_files:
  - Backend Architecture/aether-backend/services/integrations/connectors/postmark.py
---

# Postmark Connector

Observes the Postmark email lifecycle for Communications Intelligence.
Aether never sends through this connector (ADR-C1) — Postmark keeps
composition, scheduling, sending, and suppression execution.

- **Category**: marketing · **Webhook**: yes · **Pull**: no ·
  **Historical backfill**: no · **Premium**: no
- **Auth**: endpoint-secret. Postmark sends no body signature, so the
  server-controlled durable endpoint id (`POST /comms/postmark/{endpoint_id}`)
  is the credential (verified by possession). No vault secret is required.
  Ready once the connector is enabled.

## What it ingests

| Postmark RecordType | Canonical event |
|---|---|
| `Delivery` | `email_delivered` |
| `Open` | `email_opened` |
| `Click` | `email_clicked` |
| `Bounce` | `email_bounced` (`Type=Transient` → `email_deferred`, `Type=Unsubscribe` → `unsubscribe_observed`) |
| `SpamComplaint` | `email_spam_complaint` |
| `SubscriptionChange` | `email_suppressed` when `SuppressSending=true` |

Hard-bounce classification follows Postmark's `Type` field; reactivation
(`SuppressSending=false`) and unknown record types are dropped. RFC3339
timestamps are normalized to `+00:00` occurrence times.

## Enable

`PUT /v1/integrations/connectors/postmark` (`enabled: true`) → point the
provider's webhook at the server-controlled endpoint
(`POST /comms/postmark/{endpoint_id}`). No vault secret is needed. Webhooks
land on the connector webhook route and flow through the durable Bronze →
Silver pipeline. See [Connectors](CONNECTORS.md) and
[Communications Intelligence Overview](comms/COMMUNICATIONS_INTELLIGENCE_OVERVIEW.md).
