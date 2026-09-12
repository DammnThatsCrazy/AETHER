---
title: "ADR-0002: Thin SDK and Batch Ingestion"
slug: architecture/decisions/adr-0002-thin-sdk-batch-ingestion
section: architecture
visibility: P
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
---

# ADR-0002: Thin SDK and Batch Ingestion

## Status

Accepted

## Context

SDKs could embed complex logic (identity resolution, attribution, graph writes) or remain thin observation clients.

## Decision

SDKs are thin observation clients. They capture local observations, batch them, and emit canonical event envelopes to `/v1/batch`. All intelligence logic lives server-side.

## Consequences

- SDK updates are lightweight and low-risk
- Server-side logic can evolve without SDK updates
- SDKs cannot perform offline intelligence
- All observations require network delivery to be processed

## Enforcement

- `scripts/validate_sdk_import_boundary.py` prevents SDK packages from importing backend internals
- SDK parity validation ensures consistent capabilities across platforms
