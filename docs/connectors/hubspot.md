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

The HubSpot connector syncs CRM contact, company, deal, and engagement
data from HubSpot into the Aether intelligence graph.

## Data Flow

```
HubSpot CRM → API polling + webhook events
→ HubSpot normalizer
→ canonical observation envelopes
→ /v1/batch ingestion
→ graph projection
```

## Supported Entities

| HubSpot Object | Aether Mapping |
|---|---|
| Contacts | Entity (person) |
| Companies | Entity (organization) |
| Deals | Value / pipeline activity |
| Engagements | Communication / interaction |

## Sync Strategy

- Initial full sync via HubSpot search API with cursor pagination.
- Incremental sync via `lastmodifieddate` filter.
- Real-time updates via HubSpot webhook subscriptions.

## Status

Planned. Not yet implemented.
