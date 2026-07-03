---
title: Klaviyo Connector
slug: operations/klaviyo-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.11.0"
flags: [AETHER_CONNECTORS_ENABLED, AETHER_COMMS_INGESTION_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 3
source_files:
  - Backend Architecture/aether-backend/services/integrations/connectors/klaviyo.py
---

# Klaviyo Connector

Observes the full Klaviyo email lifecycle for Communications Intelligence.
Aether never sends through this connector (ADR-C1) — Klaviyo keeps
composition, scheduling, sending, templates, and suppression execution.

- **Category**: marketing · **Webhook**: yes · **Pull**: yes ·
  **Historical backfill**: yes · **Premium**: no
- **Auth**: Klaviyo private API key (vault-stored). Live API calls are
  credential-gated (`CREDENTIAL_GATED`); local mode exercises webhook
  parsing only.

## What it ingests

| Klaviyo metric | Canonical event |
|---|---|
| Sent Email | `email_sent` |
| Delivered / Received Email | `email_delivered` |
| Opened Email | `email_opened` |
| Clicked Email | `email_clicked` |
| Bounced Email | `email_bounced` (hard/soft) |
| Dropped Email | `email_dropped` |
| Marked Email as Spam | `email_spam_complaint` |
| Unsubscribed (from List) | `unsubscribe_observed` (scoped) |
| Replied to Email | `email_replied` |
| Sent/Received SMS | `message_sent/received_observed` |

Catalog sync: campaigns and flows register in the canonical campaign
registry (`channel=email`, one canonical UUID per external campaign — never
a second registry); messages land in the `campaign_messages` dimension.
Profiles feed identity evidence — raw emails are hashed tenant-scoped
before any storage.

## Enable

`PUT /v1/integrations/connectors/klaviyo` (`enabled: true`) → `/test` →
`/sync` (incremental with persisted cursor; bounded to 25 event pages per
run — repeat for backfill, see
[Backfill runbook](comms/COMMS_BACKFILL_RUNBOOK.md)). Webhooks land on the
connector webhook route and flow through the durable Bronze → Silver
pipeline. See [Connectors](CONNECTORS.md) and
[Communications Intelligence Overview](comms/COMMUNICATIONS_INTELLIGENCE_OVERVIEW.md).
