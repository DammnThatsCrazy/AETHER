---
title: "Provider Normalization"
slug: connectors/provider-normalization
section: reference
visibility: P
audience: [dev-senior]
status: stable
since_version: "0.1.0"
---

# Provider Normalization

Provider plugins under `services/backend/services/providers/` normalize
provider-shaped records into provider-neutral `AetherEvent` instances through
`shared/integration_contracts/normalization.py`. This describes the native UPR
plugin path. Legacy integration, measurement, communications, import, and
specialized financial connectors may retain their own normalization and
persistence contracts while migration proceeds.

## The two envelopes

`shared/integration_contracts/events.py` defines the two envelopes every
provider signal passes through:

- `RawProviderRecord` — the provider-shaped unit an adapter returns (poll
  rows, webhook deliveries, report rows, stream records). It preserves the
  provider's own ids, timestamps, and payload, plus a `checksum` (sha256 of
  the canonical JSON form of `payload`) so the record is tamper-evident from
  the moment an adapter produces it.
- `AetherEvent` — the normalized unit downstream consumers receive. Its
  `event_type` is provider-neutral (e.g. `commerce.order.created`); all
  provider-specific detail lives under `context`.

The envelopes have versioned idempotency behavior. Raw schema v1 preserves the
historical provider-record key; raw schema v2 keys a source-account/realm,
object, and source revision. `AetherEvent` schema v1 preserves its historical
event-type/source-record key. Schema v2 uses `event_id == event_revision_id`
as an immutable interpretation key while `logical_event_id` identifies the
stable source fact. A durable logical-fact ledger and v1-to-v2 migration map
remain future work.

## The `EventNormalizer` contract

`shared/integration_contracts/normalization.py` defines:

- `EventNormalizer` — a `Protocol` with one method,
  `normalize(raw: RawProviderRecord) -> NormalizationResult`.
- `NormalizationResult` — `events` (list of `AetherEvent`), `skipped` (count
  of records the normalizer chose not to emit), `dropped` (list of
  `"<record_id>:<reason>"` strings for anything that could not be normalized
  — never silent), and `normalizer_version`.

### Determinism

Normalization is a deterministic, network-free translation seam:

- A normalizer must never depend on wall-clock time, randomness, or provider
  I/O — the same raw record always yields the same events.
- Schema-v1 normalizers must supply a deterministic `event_id` rather than
  rely on the envelope's random `uuid4().hex` default. Schema-v2 normalizers
  supply a stable `logical_event_id`, pinned mapping and normalizer versions,
  a canonical payload digest, and source revision; the contract derives a
  full SHA-256 `event_revision_id` and requires `event_id` to equal it.
- Anything a normalizer cannot translate must be surfaced explicitly via
  `dropped` rather than silently skipped.

## How a plugin wires its normalizer

A provider plugin exposes its normalizer through a `normalizer()` accessor
(see `services/backend/services/providers/shopify/plugin.py`), returning an object satisfying
`EventNormalizer`. `services/backend/services/provider_runtime/normalization.py`
(`NormalizationEngine`) is the thin aggregation loop that applies a plugin's
`normalizer()` to a batch of raw records:

- It aggregates each record's `events` and `dropped` reasons verbatim.
- If the plugin exposes no `normalizer()`, every record is dropped with the
  explicit reason `"<record_id>:no_normalizer"` — never silently skipped.

## Reference implementation

`services/backend/services/providers/shopify/normalizer.py`
(`ShopifyOrderNormalizer`) maps a `RawProviderRecord` to a `commerce.order.*`
`AetherEvent`:

- Money fields are parsed via `Decimal(str(value))` — Shopify amounts are
  strings and are never routed through binary floats.
- REST mode remains schema v1 and preserves the historical full provider
  payload under `AetherEvent.context["raw_provider_payload"]` for compatibility.
  Provider fields not in the order model are also selectively surfaced under
  `data["provider"]`.
- GraphQL mode retains the original provider payload in protected raw Bronze,
  emits narrower event data/context, and uses a PII-free economic revision to
  compute `logical_event_id`. `event_id` equals a full SHA-256
  `event_revision_id` over the logical ID, event schema, mapping, normalizer,
  and canonical payload digest.
- Unknown record types, and any parse or money-conversion failure, are
  reported through `dropped` rather than raised or silently zeroed.

New provider normalizers should use the schema appropriate to the migration:
preserve v1 compatibility where existing consumers depend on it, but keep raw
provider payloads in protected raw storage for new v2 mappings. Derive stable
logical identities and immutable interpretation revisions for v2, and return
explicit `dropped` reasons for anything unparseable.

## Certification

`services/backend/services/provider_runtime/certification.py` checks that a plugin's
normalizer never raises on an opaque `RawProviderRecord` — it must return a
`NormalizationResult` (events or drops) even for a record it does not
recognize.

## See Also

- [Provider Manifests](./provider-manifests.md)
- [Normalization](./normalization.md)
- [Provider vs Connector](./provider-vs-connector.md)
- [Connector Subsystem Registry](./subsystem-registry.md)
