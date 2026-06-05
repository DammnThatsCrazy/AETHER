---
title: Klaviyo Connector
slug: operations/klaviyo-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
flags: [AETHER_CONNECTORS_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 2
---

# Klaviyo Connector

Ingests Klaviyo profiles and metric events (`klaviyo.profile`, `klaviyo.metric`).

- **Category**: marketing · **Webhook**: yes · **Pull**: yes · **Premium**: no
- **Auth**: Klaviyo private API key (vault-stored).

## Enable

`PUT /v1/integrations/connectors/klaviyo` (`enabled: true`) → `/test` → `/sync`.
Metric/profile sync via the Klaviyo API is a credential-gated TODO. Disabled by
default. See [Connectors](CONNECTORS.md).
