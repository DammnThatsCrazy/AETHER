---
title: HubSpot Connector
slug: operations/hubspot-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
flags: [AETHER_CONNECTORS_ENABLED, AETHER_COMMS_INGESTION_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 4
source_files:
  - Backend Architecture/aether-backend/services/integrations/connectors/adapters.py
---

# HubSpot Connector

Ingests HubSpot CRM objects — contacts, companies, deals
(`hubspot.contact`, `hubspot.company`, `hubspot.deal`) — **and** observes
HubSpot Marketing Hub email lifecycle for Communications Intelligence.
Aether never sends through this connector (ADR-C1) — HubSpot keeps
composition, scheduling, sending, templates, and suppression execution.

- **Category**: crm · **Webhook**: yes · **Pull**: yes · **Premium**: yes
- **Auth**: HubSpot private-app token + webhook client secret (vault-stored).
  Inbound events are verified with HubSpot's native
  `hubspot_signature_v3` scheme (`X-HubSpot-Signature-v3` /
  `X-HubSpot-Request-Timestamp`). `CREDENTIAL_GATED` until configured.
- **Premium**: metered as `premium_connector_used` where applicable.

## What it ingests (comms surface)

Marketing Email event webhooks map to the canonical communication taxonomy
(ADR-C2). The raw recipient address transits in memory only and is hashed
tenant-scoped before any storage (ADR-C10).

| HubSpot Marketing event | Canonical event |
|---|---|
| `SENT` | `email_sent` |
| `PROCESSED` | `email_processed` |
| `DEFERRED` | `email_deferred` |
| `DELIVERED` | `email_delivered` |
| `OPEN` | `email_opened` |
| `CLICK` | `email_clicked` (link + campaign evidence) |
| `BOUNCE` | `email_bounced` (`PERMANENT` → hard, else soft) |
| `DROPPED` | `email_dropped` |
| `SPAMREPORT` | `email_spam_complaint` |
| `UNSUBSCRIBE` | `unsubscribe_observed` (marketing-channel scope) |

Events are keyed by the HubSpot event `id` with the recipient email; click
evidence (`url`) and campaign id are extracted into link/campaign properties.
Suppression-bearing events flow through the canonical suppression authority
(ADR-C7): unsubscribe and hard bounce map to `unsubscribe` / `hard_bounce`
suppressions; a soft bounce is not a suppression.

`pull` adds a Marketing Hub campaign sync (`GET /marketing/v3/emails/`,
`hubspot.campaign`) behind the same durable cursor as CRM contact sync, so
marketing emails register in the canonical campaign registry (ADR-C9).

The existing CRM webhook verification (`X-HubSpot-Signature-v3` HMAC) is
unchanged and shared by both surfaces.

## Enable

`PUT /v1/integrations/connectors/hubspot` (`enabled: true`). For comms
webhooks, point the provider's Marketing Email event webhook at the
server-controlled endpoint `POST /comms/hubspot/{endpoint_id}` (tenant
ownership resolves server-side — never an `X-Aether-Tenant-ID` header,
ADR-C11). Configure the private-app token and webhook client secret in the
connector vault, then `/sync` for the pull. See
[Connectors](CONNECTORS.md) and
[Communications Intelligence Overview](comms/COMMUNICATIONS_INTELLIGENCE_OVERVIEW.md).
