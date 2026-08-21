---
title: Provider Migration
slug: operations/provider-migration
section: operations
visibility: I
audience: [dev-senior, ops]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/integrations/connectors/base.py
  - Backend Architecture/aether-backend/services/integrations/connectors/registry.py
  - Backend Architecture/aether-backend/services/integrations/adapter.py
  - Backend Architecture/aether-backend/shared/integration_contracts/catalog.py
  - Backend Architecture/aether-backend/services/providers/shopify/
canonical_owner: platform@aether
estimated_read_minutes: 10
toc_depth: 3
last_synced_commit: "c6aa7606"
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
(`services/provider_runtime/legacy.py`, installed by `install_legacy_plugins`
during `provider_registry.load_all()`) wraps the existing connector framework
with **zero provider code**:

- It derives identity from the catalog (`shared/integration_contracts/catalog.py`):
  `provider_family = connector_type`, `product_id = "ingestion"`,
  `capability_id = "connector"`. The manifest is derived from the
  `ConnectorDescriptor`, so **the plugin and the catalog cannot drift**.
- Lifecycle operations delegate to the authoritative
  `IntegrationAdapter` / `ConnectorIntegrationAdapter`
  (`services/integrations/adapter.py`), which in turn delegate to
  `BaseConnector`, resolve secrets through the credential platform, and map
  legacy results onto `AdapterResult`.
- Legacy namespaced event types are preserved — downstream consumers see no
  change.

### Path (b) — tomorrow: a native plugin

For a provider that wants canonical `commerce.*` events, real capability
adapters, and UPR-native operation:

1. Write a plugin package under `services/providers/<family>/` following
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
2. **Build** — create `services/providers/shopify/` (plugin, adapters,
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

## Related docs

- [UNIVERSAL-PROVIDER-RUNTIME](UNIVERSAL-PROVIDER-RUNTIME.md)
- [PROVIDER-PLUGIN-SPEC](PROVIDER-PLUGIN-SPEC.md)
- [PROVIDER-MANIFEST-SPEC](PROVIDER-MANIFEST-SPEC.md)
- [PROVIDER-CERTIFICATION](PROVIDER-CERTIFICATION.md)
- [COMMERCE-EVENT-CONTRACT](COMMERCE-EVENT-CONTRACT.md)
- [ADR-009: Universal Provider Runtime](decisions/ADR-009-universal-provider-runtime.md)
