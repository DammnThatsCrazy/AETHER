---
title: Zendesk & Intercom Connectors
slug: operations/zendesk-intercom-connectors
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
flags: [AETHER_CONNECTORS_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Zendesk & Intercom Connectors

Support connectors that ingest ticket/conversation events as graph signals.

## Zendesk

- Events: `zendesk.ticket`, `zendesk.comment`.
- Category: support · Webhook: yes · Pull: yes · Premium: no.
- Auth: Zendesk webhook signing secret / API token (vault-stored).

## Intercom

- Events: `intercom.conversation`, `intercom.contact`.
- Category: support · Webhook: yes · Pull: yes · Premium: no.
- Auth: Intercom access token / webhook secret (vault-stored).

## Enable

`PUT /v1/integrations/connectors/{zendesk|intercom}` (`enabled: true`) → `/test`
→ `/sync`. Provider API sync is a credential-gated TODO. Disabled by default.
See [Connectors](CONNECTORS.md) and [Webhook Ingestion](WEBHOOK-INGESTION.md).
