---
title: Iterable Connector
slug: operations/iterable-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.12.0"
flags: [AETHER_CONNECTORS_ENABLED, AETHER_COMMS_INGESTION_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 3
source_files:
  - Backend Architecture/aether-backend/services/integrations/connectors/iterable.py
---

# Iterable Connector

Observes the Iterable email lifecycle for Communications Intelligence
(webhook + REST pull). Aether never sends through this connector (ADR-C1) —
Iterable keeps composition, scheduling, sending, templates, and suppression
execution.

- **Category**: marketing · **Webhook**: yes · **Pull**: yes ·
  **Historical backfill**: yes · **Premium**: no
- **Auth**: inbound events are verified with Iterable's webhook HMAC
  (`iterable_hmac_query` — HMAC-SHA256 over the raw body, with the
  `signature` and optional `ts` signing timestamp carried in the webhook
  URL's query params) against the vault-stored `webhook_signing_secret`.
  Pull authenticates with the `api_key` (the Iterable Export API `Api-Key`
  header). `CREDENTIAL_GATED` until both credentials are configured.

## What it ingests

| Iterable event | Canonical event |
|---|---|
| `emailSend` | `email_sent` |
| `emailDelivered` | `email_delivered` |
| `emailOpen` | `email_opened` |
| `emailClick` | `email_clicked` |
| `emailBounce` | `email_bounced` (hard/soft from `bounceType`) |
| `emailComplaint` | `email_spam_complaint` |
| `emailUnsubscribe` | `unsubscribe_observed` (list-scoped when a `listId` is present, else `marketing_channel`) |

`emailSubscribe` has no canonical lifecycle event — a resubscription is not a
communication fact Aether observes today, so the record is dropped (mirrors
SendGrid's `group_resubscribe` disposition). `identify` / `userNew` /
`userUpdate` payloads are ingested as `iterable.profile` identity evidence
only — never a touchpoint.

Event records are keyed by `messageId` (falling back to a stable id and
timestamp composite) with the recipient `email`; campaign/flow/message/template
references, click `url`, and `userAgent` are extracted into properties. Events
are deduplicated by the namespaced `iterable:<id>` id at ingest.

## Pull (cursor)

`pull` streams the Iterable Export API (`/api/export/data.json`) for the email
lifecycle data types (`emailSend`, `emailDelivered`, `emailOpen`, `emailClick`,
`emailBounce`, `emailComplaint`, `emailUnSubscribe`) plus `userNew`/`userUpdate`
profile evidence, bounded by `startDateTime` (the durable cursor) and
`endDateTime`. The cursor advances only after the batch is durably accepted
(ConnectorCursorRepository); rate-limit (HTTP 429) leaves the cursor in place
for the next run.

## Enable

`PUT /v1/integrations/connectors/iterable` (`enabled: true`) → point the
provider's webhook at the server-controlled endpoint
(`POST /comms/iterable/{endpoint_id}`) and configure the signing secret + API
key in the connector vault, then `POST /comms/iterable/{endpoint_id}/test`
for the verification probe. Webhooks land on the connector webhook route and
flow through the durable Bronze → Silver pipeline. See
[Connectors](CONNECTORS.md) and
[Communications Intelligence Overview](comms/COMMUNICATIONS_INTELLIGENCE_OVERVIEW.md).
