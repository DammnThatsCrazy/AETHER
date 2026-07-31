---
title: Target Architecture — Economic & Interoperability Intelligence
slug: productization/economic-interoperability-intelligence/target-architecture
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/main.py
  - Backend Architecture/aether-backend/config/settings.py
canonical_owner: platform@aether
last_synced_commit: "ce23486e"
---

# Target Architecture

Three observation-only domains wired through EXISTING platform systems —
no parallel infrastructure was introduced. (Post-merge note: the
independently merged observer-stack implementations — `services/stablecoins`
at `/v1/stablecoin` and the derivatives ingestion/accounting layer at
`/v1/derivatives` — coexist with these domains; this branch's derivatives
runtime is namespaced under `/v1/derivatives/runtime`.)

A fourth observation-only slice, card-linked payment rails, follows the
same wiring pattern: `main.py` mounts
`services/card_linked_payments/routes.py` under
`/v1/integrations/providers/payment-rails/card-linked` when
`AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED` is on, and
`services/card_linked_payments/kyber_routes.py` under
`/v1/admin/kyber/payment-rails/card-linked` when either the master or
`KYBER_CARD_LINKED_PAYMENT_RAILS_ENABLED` flag is on. Its source of
truth is `docs/source-of-truth/CARD_LINKED_PAYMENT_RAILS.md`.

```
provider evidence (RPC logs / venue snapshots / simulator fixtures)
        │ read-only adapters (honest ImplementationStatus)
        ▼
domain services (services/{stablecoin,derivatives,interop})
        │ canonical events (registry families, 110 events)
        ▼
silver projectors (registry-derived handles) ──► silver_*_facts
        │                                              │
        ▼                                              ▼
graph mutations (flag-gated, idempotent)        gold materialization
        │                                       (ClickHouse DDL, no training)
        ▼
Profile360 sub-resources · Noesis intents · OODA suggestions · alerts
        ▼
Aether tenant pages · Kyber operator ops pages (flag-gated, honest states)
```

## Invariants

- `execution_by_aether = false` at every layer: DB CHECK constraints,
  `Literal[False]` model fields, `check_no_execution` on write routes,
  read-only adapter credentials, conformance assertions.
- Fail-closed flags: every capability defaults OFF
  (`AETHER_STABLECOIN_*`, `AETHER_DERIVATIVES_*`, `AETHER_INTEROP_*`,
  `KYBER_*_OPS_ENABLED`); `Settings.__post_init__` enforces coherence
  (LayerZero requires the adapters flag).
- Tenant isolation: every tenant table keyed and filtered by
  `tenant_id`; public reference data (registries, topology) in the
  public scope only.
- Decimal-only canonical finance: NUMERIC(38,18) + typed repositories
  preserving `Decimal`; validators reject floats and exponent forms.
