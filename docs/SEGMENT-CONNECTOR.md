---
title: Segment Connector
slug: operations/segment-connector
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
flags: [AETHER_CONNECTORS_ENABLED]
canonical_owner: platform@aether
estimated_read_minutes: 2
---

# Segment Connector

Ingests Segment track/identify/page events (`segment.track`, `segment.identify`,
`segment.page`).

- **Category**: product analytics · **Webhook**: yes · **Pull**: no · **Premium**: no
- **Auth**: Segment webhook shared secret (vault-stored); payloads HMAC-verified.

## Enable

`PUT /v1/integrations/connectors/segment` (`enabled: true`) → `/test`. Point a
Segment webhook destination at the ingest endpoint. Disabled by default. See
[Connectors](CONNECTORS.md) and [Webhook Ingestion](WEBHOOK-INGESTION.md).
