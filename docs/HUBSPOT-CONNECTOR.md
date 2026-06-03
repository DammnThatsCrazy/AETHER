---
title: HubSpot Connector
slug: operations/hubspot-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
flags: [AETHER_CONNECTORS_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# HubSpot Connector

Ingests HubSpot contacts, companies, and deals
(`hubspot.contact`, `hubspot.company`, `hubspot.deal`).

- **Category**: crm · **Webhook**: yes · **Pull**: yes · **Premium**: yes
- **Auth**: HubSpot private-app token / webhook secret (vault-stored).
- **Premium**: metered as `premium_connector_used` where applicable.

## Enable

`PUT /v1/integrations/connectors/hubspot` (`enabled: true`) → `/test` → `/sync`.
CRM object sync via the HubSpot API is a credential-gated TODO. Disabled by
default. See [Connectors](CONNECTORS.md).
