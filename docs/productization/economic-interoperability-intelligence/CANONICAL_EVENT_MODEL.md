---
title: Canonical Event Model (cross-domain)
slug: productization/economic-interoperability-intelligence/canonical-event-model
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - packages/shared/contracts/event-registry.json
canonical_owner: platform@aether
last_synced_commit: "c6d0e08"
---

# Canonical Event Model

110 events across three families in
`packages/shared/contracts/event-registry.json` (single source of truth;
`scripts/generate_contracts.py` emits TS/Python/doc artifacts):

| Family | Events | Purpose | Silver projection |
|---|---|---|---|
| `stablecoin` | 30 | `economic_observability` | `stablecoin_facts` |
| `derivatives` | 41 | `financial_activity` | `derivatives_facts` |
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
