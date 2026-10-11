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
  "packages/shared/contracts/event-registry.json": "sha256:d7507199ec0837a4c77f7fe4d54d2590f4ad49d98b10c35fc3bbb9bddd37c64a"
---

# Canonical Event Model

416 events across 25 families in
`packages/shared/contracts/event-registry.json` (single source of truth;
`scripts/generate_contracts.py` emits TS/Python/doc artifacts). The
economic-interoperability families:

| Family | Events | Purpose | Silver projection |
|---|---|---|---|
| `stablecoin` | 30 | `economic_observability` | `stablecoin_facts` |
| `derivatives` | 52 | `financial_activity` | `derivatives_facts` |
| `interop` | 39 | `cross_chain_observability` | `interop_facts` |

Rules:

- `introducedVersion: "0.1.0-alpha.0"` on every new event.
- `privacyClass`: `financial` for facts, `sensitive_financial` for
  positions/P&L, `governance` for registry/ops events.
- `retentionClass`: `financial_7y` for facts; standard classes for ops.
- `graphProjection` only on material events.
- Projector routing is registry-derived
  (`services/api/ingestion/silver/projectors/registry_handles.py`) — adding an event
  to a family automatically routes it; a cross-cutting test asserts
  every declared `silverProjection` token maps to a registered projector.
- Metering uses ONLY the 8 canonical meter names validated by
  `scripts/validate_meter_names.py` against `MeteringEventType`.

External-agent task, outcome and delegation events may carry payment-intent,
settlement-event or delegation IDs as `SOURCE_REFERENCE` fields. These are
caller-reported references, not economic facts: payment amount, currency and
status come only from server-authoritative x402 records. The registry maps
`agent_delegated_task` to `REFERENCES_DELEGATION_RECORD`; this records an exact
same-tenant record reference and does not assert canonical party identity,
delegation authorization, or that the action occurred as reported.
