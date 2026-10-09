---
title: Target Architecture — Economic & Interoperability Intelligence
slug: productization/economic-interoperability-intelligence/target-architecture
section: operations
visibility: I
audience: [architect, ops, buyer]
status: stable
since_version: 0.1.0
source_files: [services/backend/main.py, services/backend/config/settings.py]
canonical_owner: platform@aether
source_hashes:
  "services/backend/config/settings.py": "sha256:4c31fc9dd1fc2b5512d5207fa5ea61d8f961a37138912a924523856efdb6f4bf"
  "services/backend/main.py": "sha256:b52515d9eda1a3262b5b766fb5cc46368ad6c2a1998f9ee32c66f8574353f583"
---

# Target Architecture

Three observation-only domains wired through EXISTING platform systems —
no parallel infrastructure was introduced. (Post-merge note: the
independently merged observer-stack implementations — `services/backend/services/stablecoins`
at `/v1/stablecoin` and the derivatives ingestion/accounting layer at
`/v1/derivatives` — coexist with these domains; this branch's derivatives
runtime is namespaced under `/v1/derivatives/runtime`.)

A fourth observation-only slice, card-linked payment rails, follows the
same wiring pattern: `main.py` mounts
`services/backend/services/card_linked_payments/routes.py` under
`/v1/integrations/providers/payment-rails/card-linked` when
`AETHER_CARD_LINKED_PAYMENT_RAILS_ENABLED` is on, and
`services/backend/services/card_linked_payments/kyber_routes.py` under
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
