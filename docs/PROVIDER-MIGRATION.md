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
  "services/backend/services/integrations/connectors/base.py": "sha256:c30c8cf70873be7e5974db3d4199779c4d0baa5ca5facef32157245111c5073e"
  "services/backend/services/integrations/connectors/registry.py": "sha256:cbd62d89ef255fbe7097d9778d1adc2f728f7ff98bfade29a98d0620d86238f8"
  "services/backend/services/providers/amazon/": "sha256:775e061ac0c1344aa5ab76585467a510afc063ae6bec1d9fe2f58a32043c75dc"
  "services/backend/services/providers/ebay/": "sha256:36a36b484077e6e4d833ce553a7f80a1f3dab7fefa0b0fc79b143bf19405ec1f"
  "services/backend/services/providers/etsy/": "sha256:3f62869a8e5f1fbdc0e9e3f5d2037a1a2be6539f4b30584176e50f5c8fb7d2d1"
  "services/backend/services/providers/shopify/": "sha256:bd8171dabd1af895c65cfd432611241b436a1255bd0e08f57b2fd8bd1bbbab7c"
  "services/backend/services/providers/tiktok/": "sha256:081c927e0d3bd7ad9dc4610a79005b01949fca195fced6fa8ad7a933f1fb04b3"
  "services/backend/services/providers/walmart/": "sha256:aa3ea9aa3af1b60f59a3e789398e53a89a92c3719e8d32d8b52fc1b6dcb0c186"
  "services/backend/services/providers/woocommerce/": "sha256:2fa57e2e7e797edffe9083feb1462cefb2307de233feed57e60352719805fe4f"
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
| When | With UPR enabled; no per-connector porting | Per-provider as native capabilities are built |
| What | Existing `BaseConnector` entries are exposed through the compatibility wrapper | A provider is implemented as a native plugin package |
| Identity | `(connector_type, "ingestion", "connector")` — **byte-identical** to the catalog-derived manifest | `family.product.capability`, e.g. `shopify.admin.orders_read` |
| Event types | Legacy namespaced types preserved | Canonical `commerce.*` events |
| Lifecycle | Delegated straight to the legacy `BaseConnector` | Native adapters + normalizer |
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
- Lifecycle operations delegate directly to the legacy `BaseConnector`
  (`test_connection`, `pull`, `parse_webhook`), resolve secrets through the
  credential platform, and map legacy results onto `AdapterResult`
  (`provider_runtime/legacy.py`). There is no separate adapter facade; the
  earlier `IntegrationAdapter` / `ConnectorIntegrationAdapter` layer was never
  wired in and was removed.
- Legacy namespaced event types are preserved — downstream consumers see no
  change.

### Path (b) — native plugin, per provider

For a provider that needs canonical `commerce.*` events, native capability
adapters, or UPR-native operation, implement and certify its native plugin.
Six native provider packages already exist in this build; the Shopify package
is the reference for continuing this path:

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
2. **Build** — the native Shopify package already exists at
   `services/backend/services/providers/shopify/` (plugin, adapters, normalizer,
   fixtures); use it as the reference while keeping it alongside the legacy
   connector until cutover gates pass.
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
| Shopify | legacy `shopify.ingestion.connector` | Native UPR stream foundation and opt-in GraphQL reader exist alongside the legacy path; no tenant cutover or environment enablement is claimed. |

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
decommission. In this branch the native plugin declares REST, REST-plus-webhook,
and opt-in GraphQL modes. REST remains the default compatibility path;
GraphQL uses API version `2026-07` and remains credential-waiting with every
environment disabled. Shopify REST/webhook revision parity, sandbox evidence,
source authority, graph projection, durable tenant writer routing, and rollback
are not complete, so no tenant has cut over. The decommission procedure uses the retire helper in
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
maps, a compatibility projection ref (`provider:{tenant}:{identity}`), and a
confidence verdict. That projection field is not the ref stored on a newly
created connection: the migration executor stores credentials under a
tenant/provider/connection-scoped ref (including a SHA-256 digest of the new
connection ID). Existing legacy `provider:{tenant}:{identity}` refs remain
resolvable for persisted connections and are not rewritten by this change.
`ProjectionCandidate` is the lighter pre-projection snapshot with
`native_identity=None` until a native counterpart exists and
`requires_manual_mapping` flagging fields that need a human decision. Both
models are strict (`extra="forbid"`).

## 6. Universal connector migration foundation in this branch

The [universal connector blueprint](blueprints/universal-connector-runtime/README.md)
extends this per-provider sequence with stream-scoped raw revisions,
non-identity source-object mappings, and a durable tenant route ledger. The
route key includes tenant, environment, managed integration, provider,
account, stream, and fact family. A compare-and-swap transition increments
its writer generation and writes an audit receipt in the same transaction.
Route proposals require a governance admission callback and fail closed
without one.

The route ledger is not a cutover switch by itself. No tenant route API is
mounted, and the existing legacy and native graph writers are not yet both
fenced through it. A connector graph writer wrapper can hold a route lock
through one governed graph mutation, but promotion remains disabled until
every affected writer uses that seam, shadow output is isolated, projection
diffs pass, and rollback is rehearsed. Do not retire a legacy connector from
the registry merely because its native plugin registered or its route record
exists.

The event bridge now commits consent-admitted provider events to typed Bronze
and the transactional event outbox. In staging and production, enabling UPR
ingress without the existing event-outbox relay fails startup. Historical raw
rows and legacy canonical outputs need a scoped replay/diff migration; the
bridge does not backfill them automatically. See the
[provider outbox rollout](blueprints/universal-connector-runtime/provider-outbox-rollout.md)
for the delivery gate and operational checks.

## Related docs

- [UNIVERSAL-PROVIDER-RUNTIME](UNIVERSAL-PROVIDER-RUNTIME.md)
- [PROVIDER-PLUGIN-SPEC](PROVIDER-PLUGIN-SPEC.md)
- [PROVIDER-MANIFEST-SPEC](PROVIDER-MANIFEST-SPEC.md)
- [PROVIDER-CERTIFICATION](PROVIDER-CERTIFICATION.md)
- [COMMERCE-EVENT-CONTRACT](COMMERCE-EVENT-CONTRACT.md)
- [ADR-009: Universal Provider Runtime](decisions/ADR-009-universal-provider-runtime.md)
