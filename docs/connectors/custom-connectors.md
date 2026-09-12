---
title: Custom Connectors
slug: custom-connectors
section: reference
visibility: P
audience: [dev-senior, architect]
status: experimental
since_version: "0.1.0"
---

# Custom Connectors

## Overview

Custom connectors allow tenants to integrate proprietary or unsupported
data sources into the Aether intelligence graph using the connector
framework.

## Building a Custom Connector

A custom connector implements the connector lifecycle interface:

1. **Configure**: define connection parameters and credentials.
2. **Authenticate**: establish authenticated session with the source.
3. **Normalize**: translate source payloads into canonical observation
   envelopes.
4. **Sync**: implement cursor-based incremental sync and/or webhook
   handling.
5. **Monitor**: report health metrics to Kyber diagnostics.

## Normalizer Contract

Every custom connector must include a normalizer that outputs canonical
Aether observation envelopes. The normalizer must:

- Map source fields to canonical event types.
- Preserve source metadata for audit.
- Handle missing/null fields according to the three-state rule
  (missing ≠ empty ≠ zero).

## Deployment

Custom connectors run within the tenant's connector runtime. They do
not have direct access to the graph — all data flows through the
standard ingestion pipeline.

## Status

Framework planned. See `docs/connectors/overview.md` for the connector
architecture overview.
