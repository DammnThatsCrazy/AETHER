---
title: Salesforce Connector
slug: operations/salesforce-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
flags: [AETHER_CONNECTORS_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Salesforce Connector

Ingests Salesforce leads, accounts, and opportunities
(`salesforce.lead`, `salesforce.account`, `salesforce.opportunity`).

- **Category**: crm · **Webhook**: no · **Pull**: yes · **Premium**: yes
- **Auth**: Salesforce connected-app OAuth credentials (vault-stored).
- **Pull**: SOQL/Bulk API sync is a credential-gated TODO.

## Enable

`PUT /v1/integrations/connectors/salesforce` (`enabled: true`) → `/test` →
`/sync`. Disabled by default. See [Connectors](CONNECTORS.md).
