---
title: Provider Plugin Spec
slug: architecture/provider-plugin-spec
section: architecture
visibility: I
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
source_files:
  - services/backend/shared/integration_contracts/plugin.py
  - services/backend/shared/integration_contracts/capabilities.py
  - services/backend/shared/integration_contracts/results.py
  - services/backend/shared/integration_contracts/normalization.py
  - services/backend/shared/integration_contracts/events.py
  - services/backend/shared/integration_contracts/identity.py
  - services/backend/services/provider_runtime/
  - services/backend/services/providers/shopify/
canonical_owner: platform@aether
estimated_read_minutes: 15
toc_depth: 3
source_hashes:
  "services/backend/services/provider_runtime/": "sha256:76161c67972ddd7ab2b014beb85b6f1c3488fd9136be799f18f2debc0fc2313d"
  "services/backend/services/providers/shopify/": "sha256:bd8171dabd1af895c65cfd432611241b436a1255bd0e08f57b2fd8bd1bbbab7c"
  "services/backend/shared/integration_contracts/capabilities.py": "sha256:0549328cc36de3ad566dcc2bbdf2792cab4eafbf3a6785141485d5cdf0058b6f"
  "services/backend/shared/integration_contracts/events.py": "sha256:3db66be3c58959b1ac01cebaee21559d19069abf617ed8086c474f3161f5a80e"
  "services/backend/shared/integration_contracts/identity.py": "sha256:8264880ababfa1eb2c6be6cbc099478d3e140e7caf1afcb52b664921b6b2871b"
  "services/backend/shared/integration_contracts/normalization.py": "sha256:65fe57419a11f1a4c6a14225a024af6d74425261a7b27296798142abca9d3aeb"
  "services/backend/shared/integration_contracts/plugin.py": "sha256:b4cfa2d84da2a47a43f96564d55d4ad63fdad3027feb08e1747cc0788030988c"
  "services/backend/shared/integration_contracts/results.py": "sha256:cf30d4dbed85c68e809a87b0f256f93665d11844b5a983a0b83177d62800e51a"
---

# Provider Plugin Spec

A **provider plugin** is the self-contained unit the Universal Provider
Runtime (UPR) executes. This spec is the contract for writing one. Reference
implementation: `services/backend/services/providers/shopify/`.

## 1. The plugin contract

A plugin satisfies the structural `ProviderPlugin` protocol
(`shared/integration_contracts/plugin.py`). It exposes:

- `identity() -> ProviderIdentity` — the per-capability identity.
- `manifest() -> ProviderManifest` — what the capability is and needs (see
  [PROVIDER-MANIFEST-SPEC](PROVIDER-MANIFEST-SPEC.md)).
- Seven optional capability adapter accessors, one per capability:
  `auth()`, `account()`, `pull()`, `webhook()`, `report()`, `stream()`,
  `reconciliation()` — each returns the adapter or `None` when the capability
  is not implemented.
- `normalizer() -> EventNormalizer` — always present (the plugin may return a
  no-op normalizer, but the accessor must exist).

`BaseProviderPlugin` (in `services/backend/services/provider_runtime/plugin.py`) provides the
**honest defaults**: every capability accessor returns `None`, so a plugin
claims a capability only by overriding the accessor to return an adapter.
`normalizer()` — like `identity()` and `manifest()` — is left abstract: a
subclass must declare its normalizer (a no-op normalizer is a deliberate
choice, never an accidental default).

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

An optional `manifest().streams` inventory declares independently named
source-object streams. Registration validates each descriptor against the
manifest and installed `pull()`, `webhook()`, `report()`, or `stream()` adapters;
`ProviderRegistry.streams_for(identity_key)` exposes the validated declarations.
The plugin ABI remains v1: a declaration does not by itself dispatch a
per-stream worker or prove live provider behavior.

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
| `account` | optional dict identifying the account the operation addressed |
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
- The v1 raw idempotency key includes tenant, provider identity, provider
  record ID, and envelope version. It dedupes retries of one immutable source
  record. Mutable objects need an explicit v2 source revision; otherwise a
  later state with the same native object ID can be collapsed. The raw store
  now accepts a complete source account/live-or-test-realm/object/raw-revision
  tuple for v2 records,
  returns the persisted raw lineage ID on duplicate, and rejects partial v2
  identity. Providers must establish a verified account and complete revision
  before opting into this path. Raw acquisition revisions can differ while a
  PII-free logical fact revision and canonical event ID remain the same; the
  raw-to-fact mapping still needs source-authority review before graph writes.

## 4. Webhook verify / parse contract

A `WebhookAdapter` has two methods:

- `verify(raw_body, headers, secret) -> bool` — authenticates an inbound
  delivery (HMAC, signature, token) from the raw body bytes, the delivery
  headers, and the configured secret. **This is mandatory whenever the
  manifest claims `webhooks.supported`; the verification_scheme declared in
  the manifest must match the actual verification performed.**
- `parse(payload, *, headers) -> list[RawProviderRecord]` — converts a
  verified delivery's JSON payload into raw records that flow through the
  normalizer (never a bare record).

The `/v1/provider-webhooks/` route is in `PUBLIC_PATH_PREFIXES` — it is
unauthenticated by API key by design, so the gateway is **fail-closed**
(`services/backend/services/provider_runtime/webhook.py`). The plugin's
`verify()` proves provider-specific authenticity; the runtime also resolves
and rechecks tenant, connection, and selected-account binding before it
persists tenant-scoped evidence:

- A signature scheme (e.g. `shopify_hmac`) requires a configured webhook
  secret to verify the delivery. A missing secret is a misconfiguration: the
  delivery is **DENIED** with a closed 4xx — never silently trusted. Until
  signature verification proves connection ownership, the public response is
  generic. The gateway records only a bounded-reason tenantless metric
  internally; it creates no tenant-scoped Bronze denial row or inbox entry.
- The `endpoint_secret` scheme requires a caller-presented per-connection
  token (header `X-Aether-Webhook-Endpoint-Token`) that constant-time-matches
  the connection's configured webhook secret; a missing/mismatched token is
  likewise **DENIED** with tenantless bounded-reason telemetry until the
  token verifies. The public response does not reveal the internal reason or
  tenant/account routing result.

There is **no "no secret ⇒ trust" path**: this endpoint is public, so trust
must come from cryptographic proof the caller holds the connection's secret.
Never process an unverified delivery.

After successful verification, the gateway rechecks the candidate binding and
then binds each parsed raw record to the resolved connection's tenant,
connection, and selected account. The full request body is retained in the
webhook inbox only after this binding succeeds and raw rights admission allows
retention. A rights denial therefore creates no retained request body or
tenant-scoped raw denial record. Later binding, parse, persistence, or
normalization failures may retain only tenant-scoped metadata evidence if raw
rights admission for that evidence succeeds; they never include an
unauthenticated body. A conflicting claim is denied; an unscoped record on a
multi-account connection is ambiguous and denied. A raw-persistence failure
occurs before inbox creation and retains no inbox body. Normalization or event
persistence failures leave an already-retained verified inbox unprocessed and
return a retryable server error through the HTTP route. Pre-verification public
responses remain generic even though bounded internal metrics retain a safe
reason label.

The raw-rights decision must resolve exactly one effective tenant/source grant.
All use permissions default to false. The canonical Data Rights service stores
grants and append-only lifecycle events in the migration-owned repository;
staging/production admission also requires the durable schema to be available.
Missing, ambiguous, revoked, expired, or cross-tenant grants deny before raw
payload or webhook-body persistence.
A revocation that commits after admission but before the write also denies: the
store holds the admitting grant (shared lock; revocation takes it exclusively)
across the final grant re-read and the Bronze insert, so a revoked grant never
leaves a retained record.

Even after a delivery is verified and parsed, its normalized events are not
immediately durable. The provider-runtime event bridge
(`services/backend/services/provider_runtime/bridge.py`) runs each event through the platform's
**unconditional sensitive-value scrub** on `data`/`context` (server-authoritative
minimization; redaction never rejects) plus a per-event **ingress
consent/data-policy gate** (WS-B3) before the Bronze write and publish. A
consent-denied event is skipped — no Bronze row, no publish, a metric and a
warning — so individual events inside a verified delivery can be dropped by
tenant data-policy or consent independently of `verify()`; the delivery itself
is never silently failed wholesale.

Pull sync uses the same tenant rights gate as webhooks: before any raw payload is
written, `ProviderRawRightsAdmission` resolves an allowed `RightsDecision` and an
active `tenant_byod_data` grant for `provider-account:{connection_id}:{account_id}`,
and after the Bronze write it re-verifies the persisted evidence. A record that
fails either step raises `ProviderRawRightsDenied`: nothing is retained, no
identity evidence, normalized event, or bridge output is created, the run is
marked failed with `provider_raw_persist_failed`, and the cursor and connection
last-success time do not advance. Technical plugin certification and provider
payload fields cannot supply or infer these rights.

## 5. Normalization contract

`normalizer().normalize(raw: RawProviderRecord) -> NormalizationResult`
(`shared/integration_contracts/normalization.py`):

- **Deterministic.** No wall-clock time, randomness, or provider I/O. The same
  raw record always yields the same events (idempotent re-normalization for
  replay/debug).
- **Network-free.** The normalizer never calls the provider or any service.
- **`dropped` is never silent.** Anything the normalizer cannot translate must
  appear in `result.dropped` with enough detail to audit — convention
  `f"{record_id}:{provider_record_type}"` — never as a silently-skipped record.
- `NormalizationResult` carries `events`, `skipped`, `dropped`, and
  `normalizer_version`.

See [COMMERCE-EVENT-CONTRACT](COMMERCE-EVENT-CONTRACT.md) for the canonical
`AetherEvent` shape produced here.

## 6. Registration path

Registration is additive and does not touch central type unions:

- The module-level `register_provider(plugin)` hook
  (`provider_runtime/plugin.py`) records a plugin into the in-repo store by its
  `plugin_identity_key` — idempotent per identity key, and a *different* object
  under a duplicate key is a hard error. The runtime registry's
  `ProviderRegistry.register(plugin)` (`provider_runtime/registry.py`) is the
  full path: it runs the §32 honesty validation (`assert_plugin_honest` in
  `provider_runtime/validation.py`), an ABI check, and a duplicate-key / catalog
  conflict check before inserting.
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

`services/backend/services/providers/shopify/` is the reference native plugin. Walk its files:

- `auth.py` — `AuthAdapter`: credential validation + live connectivity test;
  no secret material ever appears in an error message or result `detail`.
- `account.py` — `AccountAdapter`: one selected account per shop. The opt-in
  GraphQL path discovers immutable Shop GID and explicit live/test realm with
  brokered credentials; domain-only structural discovery is insufficient for
  v2 source-object mapping.
- `pull.py` — `PullAdapter`: REST orders with `page_info` or `since_id`
  compatibility cursors; batches honor `has_more ⇒ next_cursor`.
- `graphql_pull.py` — opt-in, version-pinned GraphQL Admin order snapshots with
  scoped updated-at cursors, complete line items, explicit realm and scope
  checks, and separate raw acquisition and economic fact revisions. This
  slice does not implement Shopify bulk historical export or live certification.
- `webhook.py` — `WebhookAdapter`: constant-time `base64(HMAC-SHA256(secret,
  raw_body)) == X-Shopify-Hmac-SHA256` verification computed over the RAW
  body; on a missing secret it returns `False` (never auto-verifies), and the
  gateway then DENIES the delivery fail-closed.
- `plugin.py` — declares a **`webhook_secret`** credential field so the
  declared `shopify_hmac` scheme is actually verifiable; without it the
  gateway would deny every delivery (no secret ⇒ cannot prove ownership).
- `normalizer.py` — `EventNormalizer`: deterministic, network-free mapping of
  a Shopify order record to one canonical `commerce.order.*` `AetherEvent`.
  GraphQL v2 keeps the full source payload in protected raw Bronze and emits
  opaque lineage; REST v1 retains its historical context shape. `dropped` is
  populated for records it cannot translate — never silent.
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
from services.provider_runtime.plugin import BaseProviderPlugin
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
