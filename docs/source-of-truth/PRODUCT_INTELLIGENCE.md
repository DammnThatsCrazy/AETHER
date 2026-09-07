---
title: Product & Experience Intelligence Source of Truth
status: stable
source_files:
  - packages/shared/contracts/interaction-vocabulary.json
  - packages/shared/interaction-contract.ts
  - Backend Architecture/aether-backend/shared/product/models.py
  - Backend Architecture/aether-backend/shared/product/generated_vocabulary.py
  - Backend Architecture/aether-backend/services/product_catalog/models.py
  - Backend Architecture/aether-backend/services/product_catalog/mapping.py
  - Backend Architecture/aether-backend/services/product_catalog/manifest.py
  - Backend Architecture/aether-backend/services/product_catalog/store.py
  - Backend Architecture/aether-backend/services/product_catalog/routes.py
last_synced_commit: a500f1f
---

# Product & Experience Intelligence Plane (PR 1 scope)

Separates three truths that must never collapse: **interaction** (what
happened in an interface), **domain action** (what the application
attempted), and **outcome** (what verifiably occurred). `action_*` events
carry attempt/result semantics only — a click is never revenue, a signature
is never settlement.

## Ownership

| Concern | Canonical owner |
|---|---|
| Interaction event lifecycle (12 `interaction`-family events) | `packages/shared/contracts/event-registry.json` (via `scripts/generate_contracts.py`) |
| Interaction types / result states / evidence basis / actor kinds (+ registered custom namespaces `tenant.* wallet.* dapp.* agent.* financial_rail.*`) | `packages/shared/contracts/interaction-vocabulary.json` → generated TS/Py twins |
| Canonical interaction payload | `shared/product/models.py::InteractionPayload` ↔ `interaction-contract.ts` (parity-tested) |
| Product → Area → Feature → FeatureVersion → Surface → Control catalog + mapping rules + proposals + instrumentation-as-code manifests | `services/product_catalog/` (`/v1/product-catalog`, flag `AETHER_PRODUCT_CATALOG_ENABLED`, default off) |
| Mapping precedence | `services/product_catalog/mapping.py`: explicit_instrumentation > tenant_catalog > verified_framework > reviewed_discovery > inferred > unmapped; every resolution records `mapping_source`/`mapping_confidence`/`mapping_version` |

## Non-negotiables

- Behavioral similarity is never identity evidence; no raw interaction graph
  (interaction events declare no direct `graphProjection`).
- Unregistered custom interaction types stay in Bronze and never enter
  stable Gold metrics.
- Discovery may only create reviewable proposals — never silent promotion
  into the permanent catalog.
- Silver projectors (`product_interaction_facts`, `surface_interval_facts`,
  `feature_transition_facts`), active-time state machine, Gold metrics, and
  surfaces land in PR 2/3 of the program; until then the events' Silver
  projection targets are declared but not yet materialized.
