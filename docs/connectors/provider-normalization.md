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

Provider plugins under `services/providers/` normalize provider-shaped
records into provider-neutral `AetherEvent` instances through the canonical
contract at `shared/integration_contracts/normalization.py`. This is the same
canonical contract layer the connector subsystem registry and capability
coverage docs point to — there is exactly one normalization contract for
provider plugins, and it is not duplicated elsewhere.

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

Both envelopes carry an `idempotency_key` so ingestion can dedupe exactly
once per `(tenant, provider, provider-record)` or
`(tenant, event_type, source-record)` pair.

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
- `AetherEvent.event_id` defaults to a random `uuid4().hex`, which is fine for
  general envelope construction but **must** be overridden by a normalizer
  with a value derived deterministically from the `RawProviderRecord` (for
  example, `raw.idempotency_key` or `f"{raw.record_id}:{event_type}"`), so
  re-normalizing the same record yields byte-identical output for
  replay/debug.
- Anything a normalizer cannot translate must be surfaced explicitly via
  `dropped` rather than silently skipped.

## How a plugin wires its normalizer

A provider plugin exposes its normalizer through a `normalizer()` accessor
(see `services/providers/shopify/plugin.py`), returning an object satisfying
`EventNormalizer`. `services/provider_runtime/normalization.py`
(`NormalizationEngine`) is the thin aggregation loop that applies a plugin's
`normalizer()` to a batch of raw records:

- It aggregates each record's `events` and `dropped` reasons verbatim.
- If the plugin exposes no `normalizer()`, every record is dropped with the
  explicit reason `"<record_id>:no_normalizer"` — never silently skipped.

## Reference implementation

`services/providers/shopify/normalizer.py` (`ShopifyOrderNormalizer`) maps a
`RawProviderRecord` whose payload is a Shopify order dict onto a single
`commerce.order.*` `AetherEvent`:

- Money fields are parsed via `Decimal(str(value))` — Shopify amounts are
  strings and are never routed through binary floats.
- The full raw payload is preserved under
  `AetherEvent.context["raw_provider_payload"]`, so no provider field is ever
  silently lost even when the canonical order model does not capture it;
  provider-specific fields are additionally surfaced under
  `data["provider"]`.
- `event_id` is set deterministically from `raw.record_id` and the resolved
  `event_type` (e.g. `"<record_id>:commerce.order.created"`).
- Unknown record types, and any parse or money-conversion failure, are
  reported through `dropped` rather than raised or silently zeroed.

New provider normalizers should follow this shape: deterministic `event_id`,
full raw-payload preservation in `context`, and explicit `dropped` reporting
for anything unparseable.

## Certification

`services/provider_runtime/certification.py` checks that a plugin's
normalizer never raises on an opaque `RawProviderRecord` — it must return a
`NormalizationResult` (events or drops) even for a record it does not
recognize.

## See Also

- [Provider Manifests](./provider-manifests.md)
- [Normalization](./normalization.md)
- [Provider vs Connector](./provider-vs-connector.md)
- [Connector Subsystem Registry](./subsystem-registry.md)
