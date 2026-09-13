---
title: Provider Migration
slug: operations/provider-migration
section: operations
visibility: I
audience: [dev-senior, ops]
status: stable
since_version: "0.1.0"
source_files:
  - services/backend/services/integrations/connectors/base.py
  - services/backend/services/integrations/connectors/registry.py
  - services/backend/services/integrations/adapter.py
  - services/backend/shared/integration_contracts/catalog.py
  - services/backend/shared/integration_contracts/migration.py
  - services/backend/services/providers/shopify/
  - services/backend/services/providers/woocommerce/
  - services/backend/services/providers/etsy/
  - services/backend/services/providers/amazon/
  - services/backend/services/providers/ebay/
  - services/backend/services/providers/walmart/
  - services/backend/services/providers/tiktok/
canonical_owner: platform@aether
estimated_read_minutes: 10
toc_depth: 3
source_hashes:
  "services/backend/services/integrations/adapter.py": "sha256:92065c9a6c459302d05241379d1bc92fbc96a25596c767bfcd7d29671ee4eb7e"
  "services/backend/services/integrations/connectors/base.py": "sha256:c30c8cf70873be7e5974db3d4199779c4d0baa5ca5facef32157245111c5073e"
  "services/backend/services/integrations/connectors/registry.py": "sha256:cbd62d89ef255fbe7097d9778d1adc2f728f7ff98bfade29a98d0620d86238f8"
  "services/backend/services/providers/amazon/": "sha256:47421acb9e29d0fd5d8f6414edb2c86b03c35ccfd226b6027abe0ecc31e6c882"
  "services/backend/services/providers/ebay/": "sha256:7b1986d902e2fe6e488798464e95abadc2f6a78838e1bb53798a6b1244c1d318"
  "services/backend/services/providers/etsy/": "sha256:a554214cb6b6058580328f5d94a0ad59d382ed14c27be1a42b2d330c2d170026"
  "services/backend/services/providers/shopify/": "sha256:c0a12ddb85d4fd9590fe6559c1921a494ef73cf74575a876a56445d13dbd61b9"
  "services/backend/services/providers/tiktok/": "sha256:7c3e216b87d697b8c9b977cab6fc97a1fc338a529da59686c68c4836327af306"
  "services/backend/services/providers/walmart/": "sha256:46b1e19cd84c539069b862d86299e45e2af952a0140fa8234e07fad3f3673bc1"
  "services/backend/services/providers/woocommerce/": "sha256:ae6a2fe8ce2c2b1038e4f146db36a8c6c805cb31ddb59a5ff200cd8075f70732"
  "services/backend/shared/integration_contracts/catalog.py": "sha256:895abcded4185c421d1e84cb3e711b5c88abd963daf3260373c0f54a50c4a03c"
  "services/backend/shared/integration_contracts/migration.py": "sha256:1254c727afc3841b7803a4cecaa9a528049ff6df29086e10246c50844c293df7"
---

# Provider Migration

Migrating a legacy `BaseConnector` to the Universal Provider Runtime (UPR)
takes one of two paths. The runtime is **additive** — the legacy system stays
untouched and working throughout; nothing in this migration is core-first.

## 1. The two paths

| | **Path (a) — `LegacyConnectorPlugin`** | **Path (b) — native plugin** |
|---|---|---|
| When | **Today, zero code** | **Tomorrow, per-provider** |
| What | Every existing connector is automatically exposed as a plugin | A provider writes a real plugin package |
| Identity | `(connector_type, "ingestion", "connector")` — **byte-identical** to the catalog-derived manifest | `family.product.capability`, e.g. `shopify.admin.orders_read` |
| Event types | Legacy namespaced types preserved | Canonical `commerce.*` events |
| Lifecycle | Delegated to `IntegrationAdapter` / `ConnectorIntegrationAdapter` | Native adapters + normalizer |
| Certification | Catalog-derived manifest is honest by construction | `certify_provider` required |

### Path (a) — today: every connector is already exposed

The `LegacyConnectorPlugin`
(`services/backend/services/provider_runtime/legacy.py`, installed by `install_legacy_plugins`
during `provider_registry.load_all()`) wraps the existing connector framework
with **zero provider code**:

- It derives identity from the catalog (`shared/integration_contracts/catalog.py`):
  `provider_family = connector_type`, `product_id = "ingestion"`,
  `capability_id = "connector"`. The manifest is derived from the
  `ConnectorDescriptor`, so **the plugin and the catalog cannot drift**.
- Lifecycle operations delegate to the authoritative
  `IntegrationAdapter` / `ConnectorIntegrationAdapter`
  (`services/backend/services/integrations/adapter.py`), which in turn delegate to
  `BaseConnector`, resolve secrets through the credential platform, and map
  legacy results onto `AdapterResult`.
- Legacy namespaced event types are preserved — downstream consumers see no
  change.

### Path (b) — tomorrow: a native plugin

For a provider that wants canonical `commerce.*` events, real capability
adapters, and UPR-native operation:

1. Write a plugin package under `services/backend/services/providers/<family>/` following
   [PROVIDER-PLUGIN-SPEC](PROVIDER-PLUGIN-SPEC.md).
2. Honor the manifest + §32 honesty invariants
   ([PROVIDER-MANIFEST-SPEC](PROVIDER-MANIFEST-SPEC.md)).
3. Map to canonical `commerce.*` events
   ([COMMERCE-EVENT-CONTRACT](COMMERCE-EVENT-CONTRACT.md)).
4. Certify it ([PROVIDER-CERTIFICATION](PROVIDER-CERTIFICATION.md)).
5. Enable it in the environments its manifest declares.

## 2. Step-by-step — the Shopify reference

Shopify is the reference migration. The path for any future connector is the
same shape:

1. **Expose** — Shopify is already exposed via `LegacyConnectorPlugin` today
   (`shopify.ingestion.connector`); legacy `shopify.*` namespaced events keep
   flowing.
2. **Build** — create `services/backend/services/providers/shopify/` (plugin, adapters,
   normalizer, fixtures) per the plugin spec.
3. **Map events** — the normalizer maps Shopify order status → canonical
   `commerce.order.*` types and `CommerceOrder` → `OrderSnapshot`.
4. **Certify** — `certify_provider(ShopifyPlugin(), environment=...)`; fix any
   failing check (e.g. missing `verification_scheme`, silent `dropped`).
5. **Enable** — turn on the environments the manifest declares, at the
   readiness level the evidence earned (level 3 → replay, 4 → sandbox,
   5 → production). Certification never upgrades readiness.
6. **Decommission legacy path** — once the native plugin is certified and
   enabled and tenants have migrated, retire the Shopify `BaseConnector` entry
   from the legacy registry — per-provider, never core-first.

## 3. What does NOT change

None of the following are touched by the UPR migration:

- **Legacy routes** (`/v1/integrations/...`, connector admin) — stay mounted
  and working.
- **Credential service** — `shared/credentials/service.py` remains the only
  way credentials are stored and resolved; both paths reuse it.
- **Bronze** — `BronzeRepository` is the raw-store authority for both paths;
  `bronze_connectors` and `provider_records` coexist.
- **Consent** — consent authority is unchanged; events remain subject to the
  same gates.
- **Sync runs** — `SyncRunService` stays authoritative; UPR sync delegates to
  it.
- **Webhook inbox** — `WebhookInbox` handling is unchanged; `/v1/provider-webhooks/`
  is a new public-prefix route that verifies inside the handler, mirroring the
  existing `/v1/integrations/webhooks/` precedent.

## 4. Migration ordering principle

> **Expose → certify → map events → decommission legacy path, per-provider —
> never core-first.**

- Every existing connector is exposed first (path a) so the UPR has
  full-provider coverage from day one.
- A provider migrates to a native plugin only when it needs canonical events or
  native capabilities; the migration is per-provider and evidence-gated
  (certification).
- The legacy system and core type unions are never rewritten as part of a
  provider migration; decommissioning happens per-provider after the native
  path is live and tenants have moved.

## 5. Per-provider migration status (shipped)

The UPR follow-on program (PR-B) ships six native-only providers and one
per-provider decommission, plus the config/secret projection engine (WS6).

| Provider | Legacy connector | Path (shipped) |
|---|---|---|
| WooCommerce | none | native plugin only — no legacy decommission |
| Etsy | none | native plugin only — no legacy decommission |
| Amazon | none | native plugin only — no legacy decommission |
| eBay | none | native plugin only — no legacy decommission |
| Walmart | none | native plugin only — no legacy decommission |
| TikTok | none | native plugin only — no legacy decommission |

Because these six ship **no legacy `BaseConnector`**, there is no legacy path
to decommission: they land directly as native plugins (path b). Each lives at
`services/backend/services/providers/<family>/` with an `install_<family>_providers(registry)`
entry in its `__init__.py`, self-registers through the runtime's
`LOCAL_PLUGIN_MODULES` discovery list
(`services/backend/services/provider_runtime/plugin.py`), and is covered by
`tests/unit/test_provider_plugins.py` (55 collected tests: registry install,
pull fetch/cursor/error-classification, and the claimed webhook schemes).
The manifests are honest by construction: `certification_state` stays
`uncertified` (best `replay_certified` via the offline `certify_provider`
harness) and availability is local/integration only — the evidence basis is
offline fixture-replay determinism, not live verification; live steps remain
certification-level follow-ons and are not claimed as build facts.

Shopify is the one provider in this build that carries a legacy connector to
decommission. The decommission procedure uses the retire helper in
`services/backend/services/integrations/connectors/registry.py`:
`retire_connector_type(registry_state, connector_type)` returns a typed
`RetireResult` (`retired` / `already_retired` / `unknown` /
`not_eligible`) and is idempotent + audited (first success records
`retired_at`; repeats preserve it). Only `shopify` is in
`DECOMMISSIONABLE_CONNECTOR_TYPES`, so the decommission is enforced as an
explicit per-provider set — never core-first.

**Projection engine (WS6):** the config/secret migration projections live in
`shared/integration_contracts/migration.py`. `MigrationProjection` is one
fully-mapped legacy connector — target native identity, config/secret field
maps, target credential ref (`provider:{tenant}:{identity}`), and a confidence
verdict. `ProjectionCandidate` is the lighter pre-projection snapshot with
`native_identity=None` until a native counterpart exists and
`requires_manual_mapping` flagging fields that need a human decision. Both
models are strict (`extra="forbid"`).

## Related docs

- [UNIVERSAL-PROVIDER-RUNTIME](UNIVERSAL-PROVIDER-RUNTIME.md)
- [PROVIDER-PLUGIN-SPEC](PROVIDER-PLUGIN-SPEC.md)
- [PROVIDER-MANIFEST-SPEC](PROVIDER-MANIFEST-SPEC.md)
- [PROVIDER-CERTIFICATION](PROVIDER-CERTIFICATION.md)
- [COMMERCE-EVENT-CONTRACT](COMMERCE-EVENT-CONTRACT.md)
- [ADR-009: Universal Provider Runtime](decisions/ADR-009-universal-provider-runtime.md)
