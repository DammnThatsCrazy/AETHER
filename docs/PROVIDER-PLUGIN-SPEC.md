---
title: Provider Plugin Spec
slug: architecture/provider-plugin-spec
section: architecture
visibility: I
audience: [dev-senior, architect]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/shared/integration_contracts/plugin.py
  - Backend Architecture/aether-backend/shared/integration_contracts/capabilities.py
  - Backend Architecture/aether-backend/shared/integration_contracts/results.py
  - Backend Architecture/aether-backend/shared/integration_contracts/normalization.py
  - Backend Architecture/aether-backend/shared/integration_contracts/events.py
  - Backend Architecture/aether-backend/shared/integration_contracts/identity.py
  - Backend Architecture/aether-backend/services/provider_runtime/
  - Backend Architecture/aether-backend/services/providers/shopify/
canonical_owner: platform@aether
estimated_read_minutes: 15
toc_depth: 3
last_synced_commit: "3b86a445"
---

# Provider Plugin Spec

A **provider plugin** is the self-contained unit the Universal Provider
Runtime (UPR) executes. This spec is the contract for writing one. Reference
implementation: `services/providers/shopify/`.

## 1. The plugin contract

A plugin satisfies the structural `ProviderPlugin` protocol
(`shared/integration_contracts/plugin.py`). It exposes:

- `identity() -> ProviderIdentity` — the per-capability identity.
- `manifest() -> ProviderManifest` — what the capability is and needs (see
  [PROVIDER-MANIFEST-SPEC](PROVIDER-MANIFEST-SPEC.md)).
- Eight optional capability adapter accessors, one per capability:
  `auth()`, `account()`, `pull()`, `webhook()`, `report()`, `stream()`,
  `reconciliation()` — each returns the adapter or `None` when the capability
  is not implemented.
- `normalizer() -> EventNormalizer` — always present (the plugin may return a
  no-op normalizer, but the accessor must exist).

`BaseProviderPlugin` provides the **honest defaults**: every adapter accessor
returns `None` and `normalizer()` returns a pass-through. A plugin subclass
overrides only what it genuinely implements — it can never accidentally claim
a capability it does not implement.

```python
@runtime_checkable
class ProviderPlugin(Protocol):
    def identity(self) -> ProviderIdentity: ...
    def manifest(self) -> ProviderManifest: ...
    def auth(self) -> Optional[AuthAdapter]: ...
    def account(self) -> Optional[AccountAdapter]: ...
    def pull(self) -> Optional[PullAdapter]: ...
    def webhook(self) -> Optional[WebhookAdapter]: ...
    def report(self) -> Optional[ReportAdapter]: ...
    def stream(self) -> Optional[StreamAdapter]: ...
    def reconciliation(self) -> Optional[ReconciliationAdapter]: ...
    def normalizer(self) -> EventNormalizer: ...
```

### CapabilitySet

`CapabilitySet` is the frozen, derived truth of which capabilities a plugin
actually exposes. It is produced by `capability_set(plugin)` from the adapter
accessors (non-`None` ⇒ `True`) and must agree with what the manifest claims.
A mismatch is a certification failure, never silently reconciled.

### Identity rules

- The canonical string form is `family.product.capability` — lowercase
  segments matching `^[a-z][a-z0-9_]*$`, dots reserved as the separator.
- `plugin_identity_key(plugin)` returns `manifest().identity_key` **and**
  asserts it equals `identity().key`; disagreement raises
  `PluginValidationError`. The manifest and the identity object must describe
  the same `family.product.capability`.
- Identity is **per-capability**. `shopify.admin.orders_read` and
  `shopify.admin.orders_write` are distinct, never-equal identities; enabling
  one never enables the other.

## 2. Adapter results

Every adapter operation returns `AdapterResult` (`shared/integration_contracts/results.py`):

| Field | Meaning |
|---|---|
| `success` | `True` for a completed operation |
| `status` | `ok` / `not_supported` / `retryable_error` / `permanent_error` / `rate_limited` / `unauthorized` |
| `error_code` | machine-readable code (e.g. `not_supported:pull`) |
| `retryable` | whether the orchestrator may retry |
| `latency_ms` | observed latency |
| `rate_limit` | `RateLimitInfo` (limit / remaining / reset_epoch_ms / retry_after_ms) |
| `provider_request_id` | upstream request id for tracing |
| `correlation_id` | runtime correlation id |
| `data` | typed payload (e.g. `ReadBatch`) |

**`not_supported` never raises.** An adapter that does not implement an
operation returns `AdapterResult.not_supported(op)` — a typed, non-retryable
failure, not an exception. A missing adapter (accessor returns `None`) is
handled the same way by the runtime. Only genuinely unexpected failures should
raise.

## 3. Pull pagination contract

A `PullAdapter` returns pages via `AdapterResult[ReadBatch]`
(`shared/integration_contracts/events.py`):

```python
class ReadBatch(BaseModel):
    records: list[RawProviderRecord]   # one page
    next_cursor: Optional[str]         # cursor for the NEXT page
    has_more: bool                     # False ⇒ this page is the last
```

- `fetch(context, cursor)` — advance from `cursor` (or the manifest's
  `sync.cursor` default on first call).
- `initial_backfill(context)` — the full-history path for `sync.initial_backfill`.
- **`has_more=True` requires a non-empty `next_cursor`.** The orchestrator
  loops `fetch` until `has_more=False`, so a batch that claims more pages must
  say where the next page starts.
- Idempotency is guaranteed by `RawProviderRecord.idempotency_key`
  (`sha256(tenant|provider_identity|provider_record_id|version)`), so a
  replayed page never double-ingests.

## 4. Webhook verify / parse contract

A `WebhookAdapter` has two methods:

- `verify(request) -> bool` — authenticates an inbound delivery (HMAC,
  signature, token). **This is mandatory whenever the manifest claims
  `webhooks.supported`; the verification_scheme declared in the manifest must
  match the actual verification performed.**
- `parse(request) -> RawProviderRecord | list[RawProviderRecord]` — converts a
  verified delivery into raw records that flow through the normalizer.

The `/v1/provider-webhooks/` route is in `PUBLIC_PATH_PREFIXES` — it is
unauthenticated by API key by design, so **the plugin's `verify()` is the only
barrier** and the gateway is **fail-closed** (`services/provider_runtime/webhook.py`):

- A signature scheme (e.g. `shopify_hmac`) requires a configured webhook
  secret to verify the delivery. A missing secret is a misconfiguration: the
  delivery is **DENIED** with a closed 4xx and an auditable metadata-only
  denial record — never silently trusted.
- The `endpoint_secret` scheme requires a caller-presented per-connection
  token (header `X-Aether-Webhook-Endpoint-Token`) that constant-time-matches
  the connection's configured webhook secret; a missing/mismatched token is
  likewise **DENIED**.

There is **no "no secret ⇒ trust" path**: this endpoint is public, so trust
must come from cryptographic proof the caller holds the connection's secret.
Never process an unverified delivery.

Even after a delivery is verified and parsed, its normalized events are not
immediately durable. The provider-runtime event bridge
(`services/provider_runtime/bridge.py`) runs each event through the platform's
**unconditional sensitive-value scrub** on `data`/`context` (server-authoritative
minimization; redaction never rejects) plus a per-event **ingress
consent/data-policy gate** (WS-B3) before the Bronze write and publish. A
consent-denied event is skipped — no Bronze row, no publish, a metric and a
warning — so individual events inside a verified delivery can be dropped by
tenant data-policy or consent independently of `verify()`; the delivery itself
is never silently failed wholesale.

## 5. Normalization contract

`normalizer().normalize(raw: RawProviderRecord) -> NormalizationResult`
(`shared/integration_contracts/normalization.py`):

- **Deterministic.** No wall-clock time, randomness, or provider I/O. The same
  raw record always yields the same events (idempotent re-normalization for
  replay/debug).
- **Network-free.** The normalizer never calls the provider or any service.
- **`dropped` is never silent.** Anything the normalizer cannot translate must
  appear in `result.dropped` with enough detail to audit — convention
  `f"{record_id}:{provider_record_type}"` — and counts in `result.skipped`.
- `NormalizationResult` carries `events`, `skipped`, `dropped`, and
  `normalizer_version`.

See [COMMERCE-EVENT-CONTRACT](COMMERCE-EVENT-CONTRACT.md) for the canonical
`AetherEvent` shape produced here.

## 6. Registration path

Registration is additive and does not touch central type unions:

- `register_provider(plugin)` (module-level in `provider_runtime/plugin.py`) /
  `ProviderRegistry.register(plugin)` — runs the §32 honesty validation
  (`assert_plugin_honest` in `provider_runtime/validation.py`), then inserts
  into the registry. A duplicate identity key is a hard error.
- `provider_registry.load_all()` — the startup batch path; discovers plugins
  from:
  - the **`aether.providers`** entry-points group (`PLUGIN_ENTRY_POINT_GROUP`,
    enabled by configuration), and
  - **`LOCAL_PLUGIN_MODULES`** (explicit in-repo module list for local
    development; import failures are logged and skipped), then
  - installs legacy connector compatibility plugins (`install_legacy_plugins`).
- A dishonest plugin is rejected **at registration** with every violation
  collected, not a partial install.

## 7. Worked example — the Shopify plugin

`services/providers/shopify/` is the reference native plugin. Walk its files:

- `auth.py` — `AuthAdapter`: credential validation + live connectivity test;
  no secret material ever appears in an error message or result `detail`.
- `account.py` — `AccountAdapter`: one account per shop, discovered as
  `shop:{shop_domain}`; structural discovery is deterministic and
  network-free when no credential is present.
- `pull.py` — `PullAdapter`: orders with `page_info` (opaque next-page token)
  or `since_id` (legacy incremental id) cursors; batches honor `has_more ⇒
  next_cursor`.
- `webhook.py` — `WebhookAdapter`: constant-time `base64(HMAC-SHA256(secret,
  raw_body)) == X-Shopify-Hmac-SHA256` verification computed over the RAW
  body; on a missing secret it returns `False` (never auto-verifies), and the
  gateway then DENIES the delivery fail-closed.
- `plugin.py` — declares a **`webhook_secret`** credential field so the
  declared `shopify_hmac` scheme is actually verifiable; without it the
  gateway would deny every delivery (no secret ⇒ cannot prove ownership).
- `normalizer.py` — `EventNormalizer`: deterministic, network-free mapping of
  a Shopify order record to one canonical `commerce.order.*` `AetherEvent`;
  `dropped` is populated for records it cannot translate — never silent.
- `payloads.py` — strict (`extra="forbid"`) Shopify REST payload models, with
  `ShopifyOrder.from_api_dict` as the tolerance seam that selects known
  fields and ignores unknown keys.

Every adapter operation returns `AdapterResult`; unsupported ops use
`not_supported(op)`.

## 8. Minimal skeleton plugin

```python
"""Minimal honest plugin: one capability, one adapter."""
from typing import Optional

from shared.integration_contracts.identity import ProviderIdentity
from shared.integration_contracts.manifest import (
    Authentication, ManifestReadiness, ProviderManifest, Sync, Webhooks,
)
from shared.integration_contracts.plugin import BaseProviderPlugin
from shared.integration_contracts.capabilities import PullAdapter
from shared.integration_contracts.normalization import EventNormalizer
from shared.integration_contracts.results import AdapterResult
from shared.integration_contracts.events import ReadBatch, RawProviderRecord


class AcmePullAdapter(PullAdapter):
    async def fetch(self, context, cursor=None, limit=100):
        # ... provider API call ...
        return AdapterResult.ok(ReadBatch(records=[...], has_more=False))


class AcmeNormalizer(EventNormalizer):
    def normalize(self, raw: RawProviderRecord):
        # deterministic, network-free; never silently drop
        from shared.integration_contracts.normalization import NormalizationResult
        return NormalizationResult(events=[...], dropped=[], skipped=0)


class AcmePlugin(BaseProviderPlugin):
    """family=acme, product=catalog, capability=products_read."""
    def identity(self) -> ProviderIdentity:
        return ProviderIdentity(family="acme", product="catalog", capability="products_read")

    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_family="acme",
            product_id="catalog",
            capability_id="products_read",
            display_name="Acme Catalog Products",
            category="commerce",
            readiness=ManifestReadiness(state="replay_validated", level=3),
            availability=...,          # honest environments
            authentication=Authentication(type="api_key", credential_schema=[...]),
            sync=Sync(initial_backfill=True, incremental=True, cursor="updated_at"),
            webhooks=Webhooks(supported=False),
            data_outputs=["bronze.connector_events"],
            product_destinations=[],
        )

    def pull(self) -> Optional[PullAdapter]:
        return AcmePullAdapter()

    def normalizer(self) -> EventNormalizer:
        return AcmeNormalizer()
```

## 9. Provider checklist

- [ ] Identity is per-capability `family.product.capability`; `identity().key`
      equals `manifest().identity_key`.
- [ ] Every adapter accessor the manifest claims returns a real adapter;
      unclaimed ones return `None` (honest defaults).
- [ ] Every adapter operation returns `AdapterResult`; unsupported ops return
      `not_supported(op)`, never raise.
- [ ] Pull batches honor `has_more ⇒ next_cursor`; pages dedup via raw
      idempotency keys.
- [ ] Webhook `verify()` matches the manifest's `verification_scheme`.
- [ ] Normalizer is deterministic, network-free, and surfaces `dropped`.
- [ ] Manifest is §32-honest (`validate_manifest` passes) and ready for
      certification (`certify_provider`).
- [ ] No secrets anywhere — credentials only as `credential_service` refs.
- [ ] Replay fixtures exist so certification can reach at least level 3.

## Related docs

- [UNIVERSAL-PROVIDER-RUNTIME](UNIVERSAL-PROVIDER-RUNTIME.md)
- [PROVIDER-MANIFEST-SPEC](PROVIDER-MANIFEST-SPEC.md)
- [PROVIDER-CERTIFICATION](PROVIDER-CERTIFICATION.md)
- [COMMERCE-EVENT-CONTRACT](COMMERCE-EVENT-CONTRACT.md)
- [PROVIDER-MIGRATION](PROVIDER-MIGRATION.md)
