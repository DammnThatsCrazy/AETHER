---
title: "Provider Manifests"
slug: connectors/provider-manifests
section: reference
visibility: P
audience: [dev-senior]
status: stable
since_version: "0.1.0"
---

# Provider Manifests

Every provider plugin under `services/providers/` declares a
`ProviderManifest` — the single, typed source of truth for what a provider
capability *is* and *needs*. The canonical type lives at
`shared/integration_contracts/manifest.py` (`ProviderManifest` and its
sub-models); the honesty rules that gate what a manifest may claim are
enforced by `validate_manifest` in the same module.

## Identity

A manifest is keyed by three required fields:

- `provider_family` — the provider, e.g. `"shopify"`
- `product_id` — the product surface within that provider, e.g. `"admin"`
- `capability_id` — the specific capability, e.g. `"orders_read"`

Together these form the plugin's identity (`ProviderIdentity`), e.g.
`shopify.admin.orders_read`. A plugin's `identity()` accessor and its
manifest's three identity fields must agree.

## Manifest fields

| Section | Purpose |
|---|---|
| `display_name`, `category` | Human-facing name and category (e.g. `commerce`) |
| `readiness` | A `CredentialReadiness` state plus a coarse 1-5 productization `level` |
| `availability` | Tenant self-service / Kyber-managed / Olympus-system flags, and which environments (local/integration/staging/production) the capability is enabled in |
| `authentication` | Auth `type` (`oauth2`, `api_key`, `composite`, `webhook_only`, `none`), credential field shapes (never values), and OAuth scope/PKCE/refresh details |
| `configuration` | Non-secret configuration fields (e.g. `api_version`) |
| `accounts` | Whether account discovery and selection are supported |
| `webhooks` | Whether webhooks are supported, whether registration is automated, and the signature verification scheme |
| `sync` | Initial backfill, incremental sync, reconciliation, and the cursor field an incremental sync advances |
| `data_outputs` | Canonical output streams the plugin writes to (e.g. `bronze.provider_events`) |
| `product_destinations` | Downstream products the capability feeds |
| `deployment` | Required environment variables, secrets, public URLs, and provider-side registration steps |

Manifest construction (`ProviderManifest(...)`) only enforces types and simple
field bounds. `validate_manifest` enforces the §32 honesty invariants
separately — for example: a manifest visible in an environment must claim
`level >= 3`; a supported webhook must declare a verification scheme;
incremental sync must declare its cursor; a secret credential field may never
be marked optional. This split lets tests construct a structurally-valid but
dishonest manifest and assert the honesty gate rejects it.

## Certification

`services/provider_runtime/certification.py` (`certify_provider`) runs a fixed
set of honesty checks against a plugin and returns a `CertificationReport`.
Checks include: identity parses and is non-empty; the manifest passes
`validate_manifest`; the capability set is honest
(`services/provider_runtime/validation.py`); credential schemas never mark a
secret field optional; `webhooks.supported` implies both a verification scheme
and a webhook adapter; the normalizer never raises on an opaque record; auth
and pull adapters return an `AdapterResult` (never raise) for a
no-credential context without leaking secrets; declared outputs/destinations
are non-empty; and the claimed readiness `level` never exceeds what its
`CredentialReadiness` state supports. No live network calls are made during
certification — adapters are exercised with a no-credential
`AcquisitionContext` so a conforming adapter short-circuits.

## Registration through the provider runtime

`services/provider_runtime/manifest_service.py` (`ManifestService`) exposes
one merged manifest surface:

- `catalog()` — the derived catalog: manifests projected from existing
  inbound connectors (`services/integrations/connectors/`,
  `services/measurement/connectors/`, `services/derivatives/connectors/`) via
  `shared/integration_contracts/catalog.py`. This projection is conservative —
  it never claims more readiness, availability, or capability than the
  connector's own descriptor evidences.
- `installed()` — manifests of plugins registered with the
  `ProviderRegistry` (`services/provider_runtime/registry.py`), e.g. via
  `register_provider(...)` at plugin import time (see
  `services/providers/shopify/__init__.py` for the self-registration
  pattern).
- `merged_manifests()` — catalog + installed, collision-asserted. A plugin
  manifest that collides on identity with a catalog manifest is only admitted
  when byte-identical (`model_dump()` equal — the legacy re-derivation case);
  any other collision raises `ValueError` so the surface never ships two
  conflicting claims for the same identity.

## Reference plugin

`services/providers/shopify/plugin.py` (`ShopifyOrdersPlugin`) is the
reference provider plugin for the Universal Provider Runtime. It declares
identity `shopify.admin.orders_read`, a manifest with an honest capability set
(auth/account/pull/webhook true; report/stream/reconciliation false), and
wires `ShopifyAuthAdapter`, `ShopifyAccountAdapter`, `ShopifyPullAdapter`,
`ShopifyWebhookAdapter`, and `ShopifyOrderNormalizer`. New provider plugins
should follow this shape.

## See Also

- [Provider Normalization](./provider-normalization.md)
- [Provider vs Connector](./provider-vs-connector.md)
- [Connector Subsystem Registry](./subsystem-registry.md)
- [Capability Coverage](./capability-coverage.md)
