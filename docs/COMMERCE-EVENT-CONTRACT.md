---
title: Commerce Event Contract
slug: architecture/commerce-event-contract
section: architecture
visibility: I
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
source_files:
  - services/backend/shared/commerce_contracts/
  - services/backend/shared/integration_contracts/events.py
canonical_owner: platform@aether
estimated_read_minutes: 11
toc_depth: 3
source_hashes:
  "services/backend/shared/commerce_contracts/": "sha256:b2bce635d1c6472fdf0bdccd842098fb601a8a72362521d82fe582f1d536b013"
  "services/backend/shared/integration_contracts/events.py": "sha256:3db66be3c58959b1ac01cebaee21559d19069abf617ed8086c474f3161f5a80e"
---

# Commerce Event Contract

This is the **canonical, provider-neutral commerce vocabulary** of the
Universal Provider Runtime (UPR). Provider adapters map their native shapes
onto these models; downstream consumers read only these shapes, so provider
churn stays behind the adapter seam.

## 1. `shared/commerce_contracts` — the vocabulary

`services/backend/shared/commerce_contracts/` is fully
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

### 3.1 Raw and canonical idempotency

- Legacy raw v1 uses tenant, provider identity, native provider record ID,
  and envelope version. It is safe for immutable deliveries but can collapse
  updates if an adapter uses a mutable object ID alone.
- Raw v2 uses the verified source account, live/test realm, object type and
  native ID, and raw source revision. Bronze retains two changed acquisitions
  of one order while a retry returns the original raw lineage ID.
- `AetherEvent.idempotency_key` retains its legacy tenant/event type/raw
  lineage/version formula for compatibility. The typed Bronze/outbox bridge
  deduplicates on the producer's stable `event_id`. A provider mapping must
  derive that ID from a reviewed logical fact revision and semantic slot, so
  a contact-only raw change does not create a second economic fact.

These keys prevent transport duplicates. They do not decide source authority,
refund equivalence, or whether two providers describe one sale; those remain
reconciliation decisions before graph or revenue projection.

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

The historical REST v1 mapping in the Shopify normalizer determines status in
order and emits the event type:

| Shopify signal | Canonical status | `AetherEvent.event_type` |
|---|---|---|
| `cancelled_at` set | `OrderStatus.cancelled` | `commerce.order.cancelled` |
| `created_at == updated_at` | `OrderStatus.created` | `commerce.order.created` |
| `financial_status == refunded` | `OrderStatus.refunded` | `commerce.order.refunded` |
| otherwise | `OrderStatus.updated` | `commerce.order.updated` |
| unparseable payload / unknown record type | — | `dropped` (never silent) |

In this REST v1 mapping, `paid` / `fulfilled` / `partially_refunded`
orders fall through to `updated` — the canonical `OrderStatus` enum supports
more values, but the reference normalizer emits exactly these four event types.
The emitted `AetherEvent` carries `context.financial_status` and
`context.fulfillment_status`, and `data.provider` preserves selected raw
fields, so a more specific status is never lost in the fold.

The opt-in GraphQL v2 pull reads complete order **snapshots**, not a creation
or processor-settlement event stream. It emits `commerce.order.updated` for a
non-cancelled snapshot and `commerce.order.cancelled` when Shopify records
`cancelledAt`. Shopify's display financial status remains a labeled
store-reported observation; it does not emit `commerce.order.paid` or a
processor refund/settlement fact. Contact-only source edits retain distinct
protected raw revisions but share one PII-free logical fact ID. REST v1 remains
the default compatibility path until a reviewed tenant migration.

## 6. Dotted `commerce.*` vs the SDK registry

The dotted `commerce.*` event types **live in the runtime domain** and are
**NOT (yet) merged into the SDK event registry**
(`packages/shared/events.ts`, generated from
`packages/shared/contracts/event-registry.json`). This deliberately mirrors
the `comms` precedent: runtime-domain dotted event types stay out of the SDK
`EventType` union until a convergence program merges them. The split means SDK
consumers must be bridged — see
[SDK-COMMERCE-BRIDGES](SDK-COMMERCE-BRIDGES.md) for the scoped follow-on.

**Convergence status (WS4 — tracker-only, SHIPPED):** the follow-on program
records this split in the event registry's bookkeeping note
(`packages/shared/contracts/event-registry.json`) — runtime-domain
`commerce.*` status is documented mirroring the `comms` precedent, with **no**
`EventType`-union edits. The merge stays deferred to a dedicated convergence
program.

## Related docs

- [UNIVERSAL-PROVIDER-RUNTIME](UNIVERSAL-PROVIDER-RUNTIME.md)
- [PROVIDER-PLUGIN-SPEC](PROVIDER-PLUGIN-SPEC.md)
- [PROVIDER-MIGRATION](PROVIDER-MIGRATION.md)
- [SDK-COMMERCE-BRIDGES](SDK-COMMERCE-BRIDGES.md)
- [ADR-009: Universal Provider Runtime](decisions/ADR-009-universal-provider-runtime.md)
