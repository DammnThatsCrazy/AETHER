---
title: GA4 Connector
slug: operations/ga4-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
flags: [AETHER_CONNECTORS_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 2
---

# Google Analytics 4 Connector

Ingests GA4 events via the Data API (`ga4.event`).

- **Category**: product analytics · **Webhook**: no · **Pull**: yes · **Premium**: no
- **Auth**: Google service-account credentials + GA4 property ID (vault-stored).
- **Pull**: GA4 Data API report sync is a credential-gated TODO.

## Enable

`PUT /v1/integrations/connectors/ga4` (`enabled: true`) → `/test` → `/sync`.
Disabled by default. See [Connectors](CONNECTORS.md).
