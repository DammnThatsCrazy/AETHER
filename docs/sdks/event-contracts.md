---
title: SDK Event Contracts
slug: sdks/event-contracts
section: reference
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: 0.1.0
---

# SDK Event Contracts

All SDK events conform to canonical observation envelope contracts.

## Envelope Structure

Every event emitted by an Aether SDK includes:

- Event type identifier
- Contract version
- Tenant ID
- App/site context
- Session context
- Timestamp
- SDK version metadata
- Optional identity hints
- Event-specific payload

## Canonical Events

See `docs/source-of-truth/EVENT_REGISTRY.md` for the full event registry.

## Contract Versioning

SDK event contracts are versioned independently. The contract version is included in every emitted event envelope.
