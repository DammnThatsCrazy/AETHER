---
title: Provider Migration
slug: operations/provider-migration
section: operations
visibility: I
audience: [dev-senior, ops]
status: stable
since_version: "0.1.0"
source_files:
  - services/api/connectors/integrations/connectors/base.py
  - services/api/connectors/integrations/connectors/registry.py
  - services/api/shared/integration_contracts/catalog.py
  - services/api/shared/integration_contracts/migration.py
  - services/api/connectors/providers/shopify/
  - services/api/connectors/providers/woocommerce/
  - services/api/connectors/providers/etsy/
  - services/api/connectors/providers/amazon/
  - services/api/connectors/providers/ebay/
  - services/api/connectors/providers/walmart/
  - services/api/connectors/providers/tiktok/
canonical_owner: platform@aether
estimated_read_minutes: 10
toc_depth: 3
source_hashes:
  "services/api/connectors/integrations/connectors/base.py": "sha256:c30c8cf70873be7e5974db3d4199779c4d0baa5ca5facef32157245111c5073e"
  "services/api/connectors/integrations/connectors/registry.py": "sha256:6930e4008db461965dc9c6e0888b7ce204095872d3a7f038cf65eb75fa89fa17"
  "services/api/connectors/providers/amazon/": "sha256:96d3a75625cab54ea0f8e395c3bfc9c72a15b6b98a8a8fd0cc9880e4413ee185"
  "services/api/connectors/providers/ebay/": "sha256:7596f8b9c516ae389f508bc8bad7404839dc1297249bdf7da9280734dea0f5b2"
  "services/api/connectors/providers/etsy/": "sha256:f4bc4633c778787060215a46a10a5333c9cd8a998d7028243f75f8ec22add3dc"
  "services/api/connectors/providers/shopify/": "sha256:3105e681b0fb0ed9f3417abbc72624377a63a97489cca007ce79ab99b7d857e0"
  "services/api/connectors/providers/tiktok/": "sha256:97db9e114887181397ef7e9e1cf1059fee2ed4f686108d12ee0a16db1cbece83"
  "services/api/connectors/providers/walmart/": "sha256:09426499055d250d2ceea2a5ed8053dac7d8b68b5445bcfae1b8b2837d3879ed"
  "services/api/connectors/providers/woocommerce/": "sha256:4f5785952f1ac662b61075d6da093985705be8aba7fce0f948c6e677c2294926"
  "services/api/shared/integration_contracts/catalog.py": "sha256:76a954865823c7b8d0b9aac98787ed4ea1b0dbcbde1e99f6c58a07025971b63c"
  "services/api/shared/integration_contracts/migration.py": "sha256:1254c727afc3841b7803a4cecaa9a528049ff6df29086e10246c50844c293df7"
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
(`services/api/connectors/provider_runtime/legacy.py`, installed by `install_legacy_plugins`
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

1. Write a plugin package under `services/api/connectors/providers/<family>/` following
   [PROVIDER-PLUGIN-SPEC](../architecture/PROVIDER-PLUGIN-SPEC.md).
2. Honor the manifest + §32 honesty invariants
   ([PROVIDER-MANIFEST-SPEC](../architecture/PROVIDER-MANIFEST-SPEC.md)).
3. Map to canonical `commerce.*` events
   ([COMMERCE-EVENT-CONTRACT](../reference/COMMERCE-EVENT-CONTRACT.md)).
4. Certify it ([PROVIDER-CERTIFICATION](../reference/PROVIDER-CERTIFICATION.md)).
5. Enable it in the environments its manifest declares.

## 2. Step-by-step — the Shopify reference

Shopify is the reference migration. The path for any future connector is the
same shape:

1. **Expose** — Shopify is already exposed via `LegacyConnectorPlugin` today
   (`shopify.ingestion.connector`); legacy `shopify.*` namespaced events keep
   flowing.
2. **Build** — the native Shopify package already exists at
   `services/api/connectors/providers/shopify/` (plugin, adapters, normalizer,
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
`services/api/connectors/providers/<family>/` with an `install_<family>_providers(registry)`
entry in its `__init__.py`, self-registers through the runtime's
`LOCAL_PLUGIN_MODULES` discovery list
(`services/api/connectors/provider_runtime/plugin.py`), and is covered by
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
`services/api/connectors/integrations/connectors/registry.py`:
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

The [universal connector blueprint](../architecture/blueprints/universal-connector-runtime/README.md)
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
[provider outbox rollout](../architecture/blueprints/universal-connector-runtime/provider-outbox-rollout.md)
for the delivery gate and operational checks.

## Related docs

- [UNIVERSAL-PROVIDER-RUNTIME](../architecture/UNIVERSAL-PROVIDER-RUNTIME.md)
- [PROVIDER-PLUGIN-SPEC](../architecture/PROVIDER-PLUGIN-SPEC.md)
- [PROVIDER-MANIFEST-SPEC](../architecture/PROVIDER-MANIFEST-SPEC.md)
- [PROVIDER-CERTIFICATION](../reference/PROVIDER-CERTIFICATION.md)
- [COMMERCE-EVENT-CONTRACT](../reference/COMMERCE-EVENT-CONTRACT.md)
- [ADR-009: Universal Provider Runtime](../architecture/decisions/ADR-009-universal-provider-runtime.md)
