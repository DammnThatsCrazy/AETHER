---
title: HubSpot Connector
slug: hubspot-connector
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: "0.1.0"
---

# HubSpot Connector

## Overview

The repository contains a legacy `HubSpotConnector` under
`services/api/connectors/integrations/connectors/adapters.py`. It has a
credential-gated CRM contacts pull, a Marketing Hub campaign pull, and a
webhook parser for CRM and marketing email events. It has not migrated to the
native UPR provider plugin path.

## Data Flow

```
HubSpot API/webhook → legacy connector normalizer
→ legacy connector persistence and communications integration paths
```

## Supported Entities

| HubSpot Object | Aether Mapping |
|---|---|
| Contacts | `hubspot.contact` from the implemented contacts pull |
| Campaigns | `hubspot.campaign` from the Marketing Hub email campaign pull |
| CRM webhook events | Generic legacy webhook normalization; payload coverage depends on event type |
| Marketing email webhooks | Mapped to communications event types by the implemented event map |

## Sync Strategy

- Contact pull requests a bounded page of 50 rows and applies the supplied
  `since` value as `updatedAfter`.
- Marketing email campaign pull requests a bounded page and uses `since` as
  `createdAt`.
- Webhook signature verification and replay-window behavior remain part of
  the legacy connector route. The documented implementation currently
  simplifies HubSpot's v3 signature inputs and needs provider-backed
  conformance before it can be treated as certified.

## Status

Implemented as a credential-gated legacy connector. The class advertises pull
and webhook support, but that does not establish complete contacts/companies/
deals/engagement coverage, native UPR migration, graph projection, or live
certification. HubSpot remains a candidate for a later capability-by-capability
migration.
