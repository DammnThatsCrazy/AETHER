---
title: Canonical Event Model (cross-domain)
slug: productization/economic-interoperability-intelligence/canonical-event-model
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [packages/shared/contracts/event-registry.json]
canonical_owner: platform@aether
source_hashes:
  "packages/shared/contracts/event-registry.json": "sha256:95f3b66f97a2e57e4466d18da534084a91b411a629c5b7a752788813701242e8"
---

# Canonical Event Model

403 events across 25 families in
`packages/shared/contracts/event-registry.json` (single source of truth;
`scripts/generate_contracts.py` emits TS/Python/doc artifacts). The
economic-interoperability families:

| Family | Events | Purpose | Silver projection |
|---|---|---|---|
| `stablecoin` | 30 | `economic_observability` | `stablecoin_facts` |
| `derivatives` | 52 | `financial_activity` | `derivatives_facts` |
| `interop` | 39 | `cross_chain_observability` | `interop_facts` |

Rules:

- `introducedVersion: "8.12.0"` on every new event.
- `privacyClass`: `financial` for facts, `sensitive_financial` for
  positions/P&L, `governance` for registry/ops events.
- `retentionClass`: `financial_7y` for facts; standard classes for ops.
- `graphProjection` only on material events.
- Projector routing is registry-derived
  (`services/silver/projectors/registry_handles.py`) — adding an event
  to a family automatically routes it; a cross-cutting test asserts
  every declared `silverProjection` token maps to a registered projector.
- Metering uses ONLY the 8 canonical meter names validated by
  `scripts/validate_meter_names.py` against `MeteringEventType`.
