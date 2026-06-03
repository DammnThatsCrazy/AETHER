---
title: PostHog Connector
slug: operations/posthog-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
flags: [AETHER_CONNECTORS_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 2
---

# PostHog Connector

Ingests PostHog product-usage events and persons (`posthog.event`,
`posthog.person`).

- **Category**: product analytics · **Webhook**: yes · **Pull**: yes · **Premium**: no
- **Auth**: PostHog personal/project API key (vault-stored).

## Enable

`PUT /v1/integrations/connectors/posthog` (`enabled: true`) → `/test` → `/sync`.
Event/persons sync via the PostHog API is a credential-gated TODO. Disabled by
default. See [Connectors](CONNECTORS.md).
