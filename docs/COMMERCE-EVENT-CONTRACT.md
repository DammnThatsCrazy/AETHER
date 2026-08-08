---
title: Commerce Event Contract
slug: architecture/commerce-event-contract
section: architecture
visibility: I
audience: [dev-senior, architect]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/shared/commerce_contracts/
  - Backend Architecture/aether-backend/shared/integration_contracts/events.py
canonical_owner: platform@aether
estimated_read_minutes: 11
toc_depth: 3
last_synced_commit: "c6aa7606"
---

# Commerce Event Contract

This is the **canonical, provider-neutral commerce vocabulary** of the
Universal Provider Runtime (UPR). Provider adapters map their native shapes
onto these models; downstream consumers read only these shapes, so provider
churn stays behind the adapter seam.

## 1. `shared/commerce_contracts` — the vocabulary

`Backend Architecture/aether-backend/shared/commerce_contracts/` is fully
self-contained (stdlib + pydantic) and **never imports from**
`shared.integration_contracts` or any service/HTTP/DB layer.

### Money (`money.py`)

- `Money` — exact `decimal.Decimal` amount in a single ISO-4217 `currency`
  (`str`, so out-of-curated-set codes round-trip). Frozen and hashable.
  Negative amounts are legitimate (refunds/credits).
- `Currency` — minimal ISO-4217 enum (USD, EUR, GBP, CAD, AUD); a vocabulary,
  not a gate.
- Helpers: `sum_money` (raises `ValueError` on mixed currency),
  `money_from_cents`, `to_cents`.

### Order (`order.py`)

| Model | Closure | Notes |
|---|---|---|
| `OrderStatus` | enum | `created` / `updated` / `paid` / `fulfilled` / `cancelled` / `refunded` / `partially_refunded` |
| `OrderLineItem` | `extra="forbid"` | `line_item_id`, `product_id`, `variant_id`, `sku`, `title`, `quantity`, `unit_price: Money`, `line_total: Money`, `attributes` |
| `OrderTotals` | `extra="forbid"` | `subtotal` / `shipping` / `tax` / `discount` / `total` — all five must share one currency |
| `OrderCustomer` | `extra="forbid"` | `customer_id`, `email`, `phone`, `first_name`, `last_name` |
| `CommerceOrder` | `extra="allow"` | provider-neutral order; unknown provider fields are preserved in-transit; all `Money` shares one currency |
| `OrderSnapshot` | `extra="forbid"` | the canonical, self-contained projection used as an event payload |
| `order_to_snapshot(order)` | function | projects a `CommerceOrder` onto its `OrderSnapshot` |

Closure is deliberate: unknown fields **fail loudly** so drift in one
provider's payload cannot pass silently through a closed model.

## 2. Canonical event types (`COMMERCE_EVENT_FAMILIES`)

`shared/commerce_contracts/events.py` defines the provider-neutral
*classification* of commerce event types. The curated, canonical set:

```
commerce.order.created
commerce.order.updated
commerce.order.paid
commerce.order.cancelled
commerce.order.refunded
commerce.cart.updated
commerce.product.updated
commerce.customer.created
commerce.customer.updated
```

Helpers: `commerce_event_family(event_type)` (`"commerce"` iff the type starts
with `commerce.`), `is_commerce_event`, `is_canonical_commerce_event`
(membership in `COMMERCE_EVENT_FAMILIES`). This module is pure string
predicates over `event_type` — decoupled from any envelope — so it stays
importable everywhere.

## 3. The `AetherEvent` envelope

`AetherEvent` (`shared/integration_contracts/events.py`) is the
provider-neutral event handed to downstream consumers:

| Field | Meaning |
|---|---|
| `event_type` | **Provider-neutral** canonical type (e.g. `commerce.order.created`) |
| `event_family` | `"commerce"` / `"comms"` / ... |
| `provider` | provider **family** (`"shopify"`) — lineage, not classification |
| `provider_identity` | full `family.product.capability` |
| `tenant_id` | tenant scope (server-authoritative) |
| `source_record_id` | lineage → `RawProviderRecord.record_id` |
| `data` | canonical payload (e.g. an `OrderSnapshot`) |
| `context` | provider-specific detail: acquisition_mode, connection_id, raw provider event type, ... |
| `schema_version` | envelope version |

`event_type` is **never** provider-flavored; provider identity lives in
`provider` / `provider_identity` + `context`. Legacy connectors keep
namespaced event types during migration; only migrated plugins emit canonical
`commerce.*` events.

### 3.1 Idempotency keys

- `RawProviderRecord.idempotency_key` = `sha256(tenant_id | provider_identity |
  provider_record_id | schema_version)` — dedups raw ingestion.
- `AetherEvent.idempotency_key` = `sha256(tenant_id | event_type |
  source_record_id | schema_version)` — dedups event publication.

Both keys make ingestion and publication replay-safe: re-running a pull or
replaying a webhook never double-persists or double-publishes.

## 4. The normalizer contract

`EventNormalizer.normalize(raw: RawProviderRecord) -> NormalizationResult`
(`shared/integration_contracts/normalization.py`) maps one raw record to zero
or more `AetherEvent`s:

- **Deterministic** — no wall-clock, randomness, or provider I/O; the same raw
  record always yields the same events (idempotent re-normalization).
- **Network-free** — never calls the provider or a service.
- **`dropped` is never silent** — anything untranslatable appears in
  `result.dropped` (convention `f"{record_id}:{provider_record_type}"`) and
  counts in `result.skipped`.
- `NormalizationResult` carries `events`, `skipped`, `dropped`,
  `normalizer_version`.

## 5. Current mapping — Shopify order → event_type

The reference mapping (the Shopify plugin's normalizer,
`services/providers/shopify/normalizer.py`) is the pattern every commerce
plugin follows. It determines the canonical status in order, then emits the
event type:

| Shopify signal | Canonical status | `AetherEvent.event_type` |
|---|---|---|
| `cancelled_at` set | `OrderStatus.cancelled` | `commerce.order.cancelled` |
| `created_at == updated_at` | `OrderStatus.created` | `commerce.order.created` |
| `financial_status == refunded` | `OrderStatus.refunded` | `commerce.order.refunded` |
| otherwise | `OrderStatus.updated` | `commerce.order.updated` |
| unparseable payload / unknown record type | — | `dropped` (never silent) |

Note: in this reference mapping, `paid` / `fulfilled` / `partially_refunded`
orders fall through to `updated` — the canonical `OrderStatus` enum supports
more values, but the reference normalizer emits exactly these four event types.
The emitted `AetherEvent` carries `context.financial_status` and
`context.fulfillment_status`, and `data.provider` preserves selected raw
fields, so a more specific status is never lost in the fold.

## 6. Dotted `commerce.*` vs the SDK registry

The dotted `commerce.*` event types **live in the runtime domain** and are
**NOT (yet) merged into the SDK event registry**
(`packages/shared/events.ts`, generated from
`packages/shared/contracts/event-registry.json`). This deliberately mirrors
the `comms` precedent: runtime-domain dotted event types stay out of the SDK
`EventType` union until a convergence program merges them. The split means SDK
consumers must be bridged — see
[SDK-COMMERCE-BRIDGES](SDK-COMMERCE-BRIDGES.md) for the scoped follow-on.

## Related docs

- [UNIVERSAL-PROVIDER-RUNTIME](UNIVERSAL-PROVIDER-RUNTIME.md)
- [PROVIDER-PLUGIN-SPEC](PROVIDER-PLUGIN-SPEC.md)
- [PROVIDER-MIGRATION](PROVIDER-MIGRATION.md)
- [SDK-COMMERCE-BRIDGES](SDK-COMMERCE-BRIDGES.md)
- [ADR-009: Universal Provider Runtime](decisions/ADR-009-universal-provider-runtime.md)
