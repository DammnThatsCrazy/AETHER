---
title: "ADR-0003: Provider vs Connector Boundary"
slug: architecture/decisions/adr-0003-provider-vs-connector-boundary
section: architecture
visibility: P
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
---

# ADR-0003: Provider vs Connector Boundary

## Status

Accepted

## Context

External data sources could be integrated ad hoc or through a governed connector pattern.

## Decision

Providers are external systems. Connectors are Aether-managed integrations that handle auth, sync, webhooks, normalization, and graph projection. Connectors emit canonical contracts — they do not bypass the contract spine.

## Consequences

- Every new provider integration requires a connector
- Connectors must implement the full lifecycle (auth, sync, normalize, project)
- Ad hoc provider integrations are not allowed

## Enforcement

- Connector manifest validation
- Normalizer output validated against canonical contracts
