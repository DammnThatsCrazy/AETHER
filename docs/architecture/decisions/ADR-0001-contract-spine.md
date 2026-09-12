---
title: "ADR-0001: Contract Spine"
slug: architecture/decisions/adr-0001-contract-spine
section: architecture
visibility: P
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
---

# ADR-0001: Contract Spine

## Status

Accepted

## Context

Data enters Aether from multiple sources (SDKs, connectors, webhooks, system events). Without a canonical contract layer, each source would define its own schema, making normalization and graph projection unreliable.

## Decision

All data entering Aether must conform to canonical contracts. Contracts are versioned. Ingestion validates contracts before persistence.

## Consequences

- Every new event type requires a contract definition
- Contract changes require version bumps and compatibility analysis
- Ingestion rejects payloads that fail contract validation

## Enforcement

- `scripts/validate_contracts.py` validates contract consistency
- Ingestion pipeline rejects non-conforming payloads
- CI gate prevents merging without contract validation
