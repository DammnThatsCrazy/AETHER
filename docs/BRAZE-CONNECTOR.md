---
title: Braze Connector
slug: operations/braze-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.12.0"
flags: [AETHER_CONNECTORS_ENABLED, AETHER_COMMS_INGESTION_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 3
source_files:
  - Backend Architecture/aether-backend/services/integrations/connectors/braze.py
---

# Braze Connector

Observes the Braze email lifecycle for Communications Intelligence
(pull-model-first). Aether never sends through this connector (ADR-C1) —
Braze keeps composition, scheduling, sending, templates, and suppression
execution. This adapter never calls Braze write endpoints (no
`POST /subscription/status/set`, no blocklist, no spam-list removal).

- **Category**: marketing · **Webhook**: yes (pushed REST events) ·
  **Pull**: yes · **Historical backfill**: yes · **Premium**: no
- **Auth**: REST API key, vault-stored (`Authorization: Bearer <key>`),
  resolved through the connector vault — never in config. `CREDENTIAL_GATED`
  until the key is configured.

## Pull-model-first

Braze does not sign REST webhooks with a provider-native HMAC, and its
durable email lifecycle surfaces (hard bounces, unsubscribes) export through
the REST API — so this adapter's primary ingest path is a **REST pull with a
durable cursor**:

- `GET /email/hard_bounces` — hard-bounce export entries
  (`email` + `hard_bounced_at`) → `email_bounced` (`bounce_type="hard"`)
- `GET /email/unsubscribes` — unsubscribe export entries
  (`email` + `unsubscribed_at`) → `unsubscribe_observed`
  (`unsubscribe_scope="marketing_channel"`)
- `GET /campaigns/list` and `GET /canvas/list` — campaign + canvas catalog
  sync (`braze.campaign` / `braze.canvas`)

Both email-list exports run over the recency window: the durable cursor
(`since`) seeds `start_date`, and the window ends today. The cursor advances
**only after durable acceptance** — Bronze + canonical comms ingest must
succeed before the service layer upserts `ConnectorCursor`; a failed or
rate-limited run (HTTP 429) leaves the cursor put and the next run resumes
from the same position. Pagination walks the exports in 500-entry pages,
bounded per sync run.

Because a provider-native webhook signature scheme does not exist, the
webhook path verifies through Aether's generic timestamped HMAC (the honest
`hmac` scheme in the integration catalog) — deliberately **not** a
Braze-native scheme. Pushed message-event payloads (Currents-style
`users.messages.email.*` records and `/users/track`-recorded custom events)
map through the same canonical table below.

## What it ingests

| Braze event | Canonical event |
|---|---|
| `users.messages.email.Send` / `email_sent` | `email_sent` |
| `users.messages.email.Delivered` / `email_delivered` | `email_delivered` |
| `users.messages.email.Open` / `email_opened` | `email_opened` |
| `users.messages.email.Click` / `email_clicked` | `email_clicked` |
| `users.messages.email.Bounce` / `email_bounced` | `email_bounced` (hard) |
| `users.messages.email.SoftBounce` | `email_bounced` (soft — never a hard suppression) |
| `users.messages.email.DeliveryFailure` / `email_dropped` | `email_dropped` |
| `users.messages.email.Spam` / `email_spam` | `email_spam_complaint` |
| `users.messages.email.Unsubscribe` / `email_unsubscribed` | `unsubscribe_observed` (scoped) |
| hard-bounce list export (`hard_bounced_at`) | `email_bounced` (`bounce_type="hard"`) |
| unsubscribe list export (`unsubscribed_at`) | `unsubscribe_observed` (`unsubscribe_scope="marketing_channel"`) |

Event records are keyed by a deterministic `br-<hash>` id when Braze supplies
none (idempotent replay), with the recipient email surfaced as
`recipient_email` (hashed/normalized downstream); campaign, canvas, dispatch,
template, link, and user-agent evidence is extracted into canonical
properties. Hard bounces and unsubscribes flow into
`suppression_authority.record_from_event()` downstream.

## Enable

`PUT /v1/integrations/connectors/braze` (`enabled: true`) → store the REST
API key in the connector vault, then `POST /v1/integrations/connectors/braze/test`
for the connection probe (`GET /campaigns/list`). Pull sync runs on the
connector sync schedule; a durable cursor and sync-run ledger track each run.
Pushed message events can land on the connector webhook route and flow
through the durable Bronze → Silver pipeline. See
[Connectors](CONNECTORS.md) and
[Communications Intelligence Overview](comms/COMMUNICATIONS_INTELLIGENCE_OVERVIEW.md).
