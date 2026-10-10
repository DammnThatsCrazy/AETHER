---
title: Universal Provider Runtime
slug: architecture/universal-provider-runtime
section: architecture
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "0.1.0"
source_files:
  - services/backend/main.py
  - services/backend/config/settings.py
  - services/backend/shared/rate_limit/feature_gate.py
  - services/backend/shared/integration_contracts/
  - services/backend/shared/commerce_contracts/
  - services/backend/services/provider_runtime/
  - services/backend/services/providers/
  - services/backend/services/providers/shopify/
canonical_owner: platform@aether
estimated_read_minutes: 14
toc_depth: 3
source_hashes:
  "services/backend/config/settings.py": "sha256:f0b62e61d60a115bf5794b2d91fdb6115e3500d41f4f99eeccd726a34b28944c"
  "services/backend/main.py": "sha256:00ec069cbc1e995319deadc933182a3d768757b7425da348502d57d70e61d64c"
  "services/backend/services/provider_runtime/": "sha256:76161c67972ddd7ab2b014beb85b6f1c3488fd9136be799f18f2debc0fc2313d"
  "services/backend/services/providers/": "sha256:faa27d5485906802e22cc8c2289b047ff9094f3cf4f0eaed6e84d7ef0c3e5a3c"
  "services/backend/services/providers/shopify/": "sha256:bd8171dabd1af895c65cfd432611241b436a1255bd0e08f57b2fd8bd1bbbab7c"
  "services/backend/shared/commerce_contracts/": "sha256:b2bce635d1c6472fdf0bdccd842098fb601a8a72362521d82fe582f1d536b013"
  "services/backend/shared/integration_contracts/": "sha256:e7cbea51644fe93fb204a21cf8e2ece11833a6aa7803b6fdf2dfc076988e5929"
  "services/backend/shared/rate_limit/feature_gate.py": "sha256:a93ea91270a1d0ca3d8664ddea29b75cbfca8c2180a239cb78a3a61d8facda96"
---

# Universal Provider Runtime

## Overview

The **Universal Provider Runtime (UPR)** is a provider-neutral integration
runtime that executes **self-contained provider plugins**. It is an
**additive** layer over the existing Aether authority — the legacy
`BaseConnector` system stays untouched and working (see
[ADR-009](decisions/ADR-009-universal-provider-runtime.md)). The UPR becomes
the **authoritative** surface for new providers: a provider is a plugin
package declaring identity, a manifest, capability adapters, and a normalizer,
registered and certified as a unit.

The layer map:

| Layer | Location | Role |
|---|---|---|
| Plugin contract | `services/backend/shared/integration_contracts/` | `ProviderPlugin` protocol, manifest + honesty invariants, capability adapters, canonical results, normalization, events, certification contracts |
| Commerce vocabulary | `services/backend/shared/commerce_contracts/` | Provider-neutral Money / Order shapes and the canonical `commerce.*` event-type set |
| Runtime service | `services/backend/services/provider_runtime/` | Registry → orchestrator → pipeline → engines → API; registers, certifies, and executes plugins |
| Plugin modules | `services/backend/services/providers/*/` | One package per provider capability (reference: `services/backend/services/providers/shopify/`) |
| Legacy compat | `services/backend/services/provider_runtime/legacy.py` (`LegacyConnectorPlugin`) | Exposes every existing `BaseConnector` as a plugin with zero code changes |

## Components

### System map

```
                        ┌─────────────────────────────────────────────┐
                        │                 main.py                      │
                        │  feature-gated wiring (flag default OFF)    │
                        └──────────────┬──────────────────────────────┘
                                       │ AETHER_PROVIDER_RUNTIME_ENABLED
                                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     services/backend/services/provider_runtime                             │
│                                                                          │
│   ┌──────────────┐   discover   ┌───────────────┐   invoke    ┌───────┐  │
│   │   Registry   │ ───────────▶ │  Orchestrator │ ───────────▶ │Pipeline│ │
│   │ (register /  │              │ (sync, webhook│              │(raw → │  │
│   │  load_all)   │              │  routes, certify)             │normalize│ │
│   └──────┬───────┘              └───────────────┘              │→ bridge)│ │
│          │ register_provider                                   └───┬───┘  │
│          ▼                                                        │     │
│   ┌──────────────┐        ┌─────────────┐                         ▼     │
│   │   Engines    │        │   API       │   ┌──────────────────────────┐ │
│   │ health/read- │        │ /v1/provider│   │   Engines (persistence)  │ │
│   │ iness · cert │        │ -webhooks/  │   │ BronzeRepository · bus   │ │
│   └──────────────┘        └─────────────┘   └──────────────────────────┘ │
└───────────────────────────┬──────────────────────────────────────────────┘
                            │ plugin discovery
                            ▼
   ┌────────────────────────────────────────────────────────────────┐
   │ Plugin modules (services/backend/services/providers/*/)                          │
   │   services/backend/services/providers/shopify/   (native plugin)                 │
   │   ...future native plugins...                                    │
   │   LegacyConnectorPlugin          (wraps BaseConnector, identity │
   │                                    (connector_type,"ingestion", │
   │                                    "connector") — byte-identical │
   │                                    to catalog-derived manifest)  │
   └────────────────────────────────────────────────────────────────┘
```

### Package layout

```
services/backend/
├── shared/
│   ├── integration_contracts/          # plugin contract layer (additive)
│   │   ├── plugin.py                   #   ProviderPlugin, BaseProviderPlugin,
│   │   │                               #   CapabilitySet, plugin_identity_key
│   │   ├── manifest.py                 #   ProviderManifest + validate_manifest (§32)
│   │   ├── identity.py                 #   ProviderIdentity (family.product.capability)
│   │   ├── capabilities.py             #   Auth/Account/Pull/Webhook/Report/Stream/
│   │   │                               #   Reconciliation adapter protocols
│   │   ├── results.py                  #   AdapterResult + bridge mappers
│   │   ├── normalization.py            #   EventNormalizer, NormalizationResult
│   │   ├── events.py                   #   RawProviderRecord, ReadBatch, AetherEvent
│   │   ├── streams.py                  #   stream mode/cursor declarations
│   │   ├── source_objects.py           #   non-identity object refs, logical event key
│   │   ├── certification.py            #   CertificationReport, readiness tokens
│   │   ├── catalog.py                  #   derived catalog — 4 groups (connectors, ad-platforms, payment-rails, credit bureaus)
│   │   ├── experience.py               #   ExperienceCategory + experience_category_for (customer-facing projection)
│   │   ├── aliases.py                  #   boundary-family aliases (twitter_ads→x_ads, …) + canonical_family_id
│   │   └── ...                         #   lifecycle, deployment, health
│   ├── commerce_contracts/             # commerce vocabulary (additive)
│   │   ├── money.py                    #   Money, Currency, sum_money, money_from_cents
│   │   ├── order.py                    #   CommerceOrder, OrderSnapshot, order_to_snapshot
│   │   └── events.py                   #   COMMERCE_EVENT_FAMILIES (9 canonical types)
│   └── rate_limit/feature_gate.py      # one sanctioned change: /v1/provider-webhooks/
├── services/
│   ├── provider_runtime/               # NEW — the runtime service
│   │   ├── acquisition.py              #   account discovery/selection coordinator
│   │   ├── bridge.py                   #   canonical event → typed Bronze + outbox
│   │   ├── certification.py            #   certification harness (certify_provider)
│   │   ├── connection.py               #   connection lifecycle
│   │   ├── credential_broker.py        #   credential resolution via credential_service
│   │   ├── errors.py                   #   typed runtime errors
│   │   ├── health.py                   #   health engine (ProviderHealthReport)
│   │   ├── legacy.py                   #   LegacyConnectorPlugin (wraps every BaseConnector)
│   │   ├── manifest_service.py         #   merged manifest view (catalog + installed plugins)
│   │   ├── metering.py                 #   usage metering
│   │   ├── normalization.py            #   normalization engine (applies plugin normalizer)
│   │   ├── plugin.py                   #   BaseProviderPlugin + register_provider
│   │   ├── rate_limit.py               #   per-provider rate limiting
│   │   ├── raw_store.py                #   raw-before-canonical Bronze persistence
│   │   ├── object_refs.py              #   verified source-object IDs and aliases
│   │   ├── tenant_route_repository.py  #   audited route ledger and writer fence
│   │   ├── tenant_route_service.py     #   governed route transitions
│   │   ├── connector_graph_writer.py  #   opt-in guarded graph mutation seam
│   │   ├── registry.py                 #   ProviderRegistry — register/load_all, entry points
│   │   ├── retry.py                    #   retry policy
│   │   ├── routes.py                   #   /v1/provider-connections, /v1/admin/kyber/
│   │   │                               #   provider-connections (incl. /certify),
│   │   │                               #   /v1/provider-webhooks
│   │   ├── scheduler.py                #   pull scheduler (manual triggers; sync-run ledger)
│   │   ├── validation.py               #   §32 honesty validation (capability_violations)
│   │   └── webhook.py                  #   inbound webhook gateway — fail-closed verify
│   ├── providers/
│   │   ├── shopify/                    # NEW — reference native plugin
│   │   │   ├── plugin.py               #   plugin class + manifest (shopify.admin.orders_read)
│   │   │   ├── auth.py                 #   AuthAdapter (credential validation + connectivity)
│   │   │   ├── account.py              #   AccountAdapter (shop discovery/selection)
│   │   │   ├── pull.py                 #   PullAdapter (page_info / since_id cursors)
│   │   │   ├── graphql_pull.py         #   opt-in version-pinned GraphQL orders
│   │   │   ├── webhook.py              #   WebhookAdapter (HMAC-SHA256 verify + parse)
│   │   │   ├── normalizer.py           #   Shopify order → commerce.order.*
│   │   │   └── payloads.py             #   strict Shopify REST payload models
│   │   └── ...                         #   future native plugins
│   └── integrations/connectors/        # LEGACY — untouched, still working
└── config/settings.py                  # AETHER_PROVIDER_RUNTIME_ENABLED=False
```

## Data flow

### Raw-before-canonical pipeline

```
Provider adapter
  (pull/webhook/report/stream)
        │  RawProviderRecord (provider's own payload, untouched)
        ▼
BronzeRepository("provider_records")      ← idempotent (raw idempotency key)
        │  raw rights are resolved before insert; a denied record is never written
        │  (staging/production require the migrated durable grant schema)
        │  normalize only if the persisted row is valid / not_quarantined
        ▼
Tenant rights admission (ProviderRawRightsAdmission — the single admission gate)
  ├─ missing / denied / non-durable grant store → ProviderRawRightsDenied:
  │    nothing retained, run fails, cursor and last-success unchanged
  └─ allowed RightsDecision + active tenant_byod_data grant + valid persisted evidence
        ▼
Normalization engine (EventNormalizer.normalize)
        │  deterministic, network-free; NormalizationResult
        ▼
Event bridge
  1. consent-admitted canonical AetherEvent → typed bronze_sdk_events
  2. SDK_EVENTS_VALIDATED outbox row in the same database transaction
  3. supervised event-outbox relay → event bus when enabled
        ▼
Downstream consumers (analytics, outbox, intelligence)
```

The pipeline honors three invariants:

- **Idempotency.** Legacy raw keys remain readable. Schema v2 raw keys include
  the verified source account, object, and source revision, so a changed
  source object is retained while a duplicate revision returns the original
  Bronze lineage ID. The typed canonical Bronze/outbox transaction deduplicates
  the event ID. Provider-specific semantic duplication still needs source
  authority and reconciliation.
- **Bronze-before-publish.** Pull and webhook ingress persist a raw record,
  then admit it to normalization only if the persisted Bronze provenance and
  quarantine statuses pass the fail-closed check below. For an admitted record,
  the bridge commits a typed canonical Bronze row
  and an outbox row atomically. A persistence failure leaves the pull cursor or
  webhook inbox receipt unadvanced. Bus delivery requires the existing
  supervised relay, and downstream projection is a separate authority.
- **Deterministic normalization.** A normalizer must not depend on wall-clock,
  randomness, or provider I/O. Dropped or invalid records remain a visible
  normalization outcome; provider-specific quarantine and repair are still
  required before a stream is promoted.
- **Ingress consent gate (WS-B3).** The event bridge scrubs sensitive values
  from each `AetherEvent`'s `data`/`context` in place before the durable dump
  (mandatory and unconditional — Bronze and the publish carry only scrubbed
  payloads) and runs the shared ingress decision
  (`services/backend/services/ingestion/validation.evaluate_ingress_decision`) per event. A
  denied event is rejected — no canonical Bronze/outbox row or publish,
  `provider_runtime_consent_blocked_total` incremented. Any already-admitted
  provider raw record remains available only while its rights/retention basis
  permits; it is not preserved indefinitely as an audit exception. The internal
  raw replay service has no public/operator authorization surface today. The
  per-subject (S) server-receipt rejection applies only when
  `PROVIDER_RUNTIME_CONSENT_ENFORCEMENT_ENABLED` is set (default True) AND the
  authoritative consent flag is on AND the event resolves a purpose + subject.
  Provider raw retention and deletion remain governed separately by rights and
  data-use policy.

**Current raw-rights admission gate:** UPR resolves the provider account at
`source_id="provider-account:{connection_id}:{account_id}"`. The required
`DataRightsGrant` is tenant-scoped to the verified connection, sets
`connector_id` to the provider identity and `connector_class` to
`tenant_byod_data`, and grants tenant-lake permission. Raw payload is retained
only after an allowed, immutable `RightsDecision` is recorded; the persisted
Bronze row must also have `provenance_status=valid` and
`quarantine_status=not_quarantined` before normalization. Replay requires the
tenant-scoped decision reference and a fresh rights check. `DataRightsService`
persists canonical grants and create/revoke events through its migration-owned
tenant-scoped repository. Staging/production raw admission also checks that the
database and required schema are available, and fails closed when they are not.
Omitted use permissions default to false. This persistence change does not
enable the provider runtime or alter environment flags.

**Revocation fence.** Admission decides at one instant and Bronze is written
later. `RawProviderRecordStore` therefore holds the admitting grant
(`ProviderRawRightsAdmission.hold_grant`) across the final grant re-read, the
Bronze insert and `verify_persisted`. `DataRightsGrantRepository.revoke` takes the
same per-grant lock exclusively inside its transaction. A revocation either
committed first, so the write is refused with `grant_revoked_before_write` and
nothing is retained, or it waits until the in-flight write has committed and then
sees the row. On PostgreSQL writers take a session-level shared advisory lock and
revocation takes `pg_advisory_xact_lock`; local mode uses a per-grant asyncio
lock. A writer pins one pooled connection while it holds the lock, so concurrent
holders are capped below half of the pool size. Replay does not write new raw
rows and still requires a fresh admission.
Rows created under the earlier path remain quarantined because they have no
persisted admission evidence or referenced allowed `RightsDecision`. Replay
rejects their quarantine state and requires the original tenant-scoped decision
reference plus a fresh current-grant check. No historical-row re-admission
path exists, so operators cannot unquarantine or replay these rows manually. A
future governed path must resolve immutable decision evidence for each
unchanged Bronze row and perform a fresh rights check; it must not rewrite the
raw row to bypass replay admission. `BronzeRepository.update` rejects
post-insert changes to provider raw, source, provenance, and quarantine fields.
Its only exception appends IDs to `payload.metadata.confirmed_signal_ids`.
Quarantine does not grant an audit-retention exception: current rights and
retention rules govern preservation, deletion, and suppression. The runtime
flag remains default-off; an adapter payload or manifest cannot grant
admission.

Provider credentials use a separate secret reference. New credential writes use
opaque refs scoped to tenant, provider identity, and connection. Persisted
legacy tenant/provider refs remain resolvable for existing connections, but
new writes do not reuse or rewrite them. This credential boundary does not
grant raw-data retention rights.

## Feature flag & wiring

- `main.py` wires the UPR **conditionally**: when
  `AETHER_PROVIDER_RUNTIME_ENABLED=True`
  (`config/settings.py` `ProviderRuntimeConfig`, default **False**), the
  runtime calls `provider_registry.load_all()`, mounts the connections router
  (`/v1/provider-connections`) and the public webhook router
  (`/v1/provider-webhooks`).
- The **admin** router (`/v1/admin/kyber/provider-connections`, including the
  `/certify` route) mounts only when a second flag
  `KYBER_PROVIDER_RUNTIME_HEALTH_ENABLED` is also `True` (default **False**).
- With the flag off, no UPR route is mounted and no plugin is registered —
  the legacy system is byte-for-byte unaffected.
- **One sanctioned feature-gate change**: `/v1/provider-webhooks/` is added to
  `PUBLIC_PATH_PREFIXES` in `shared/rate_limit/feature_gate.py`. Like the
  existing `/v1/integrations/webhooks/` entry, the route is unauthenticated by
  API key and MUST self-verify inbound calls **fail-closed** inside the handler:
  a signature scheme without a configured secret, or an `endpoint_secret`
  scheme without a matching per-connection token, is DENIED with a closed 4xx
  and no "no secret ⇒ trust" path. Before verification proves connection
  ownership, the public response is a generic closed denial. Internal
  telemetry may record a bounded reason label with no tenant label; it does
  not write tenant-scoped Bronze denial rows or inbox bodies. A webhook body
  is retained only after successful verification, binding, and raw-rights
  admission. Later tenant-scoped metadata-only failure evidence is retained
  only after successful verification and binding and only if its own raw-rights
  admission succeeds; a rights denial creates no such evidence.

## How a new provider lands

1. **Build the plugin package** (`services/backend/services/providers/<family>/`): plugin class,
   manifest (honest, §32-valid), one adapter per claimed capability, a
   deterministic normalizer, and replay fixtures.
2. **Register** it: `register_provider(plugin)` / `ProviderRegistry.register`
   runs the §32 honesty validation (`assert_plugin_honest`); startup calls
   `provider_registry.load_all()`, which discovers entry-point plugins (group
   `aether.providers`), imports `LOCAL_PLUGIN_MODULES` for local development,
   and installs legacy connectors. Registration rejects a plugin whose
   manifest overclaims or underclaims its adapters, or whose `identity().key`
   disagrees with `manifest().identity_key`.
3. **Certify** it: `certify_provider(plugin, environment=...)` returns a
   `CertificationReport`; a failed check blocks the provider (see
   [PROVIDER-CERTIFICATION](PROVIDER-CERTIFICATION.md)).
4. **Enable** it: turn on the environment / readiness it honestly earned
   (certification never upgrades readiness — the operator does).
5. **Ship**: the provider is reachable only where its manifest says it is.

## Observability

- **Health engine** produces `ProviderHealthReport` per plugin
  (`shared/integration_contracts/health.py`): reachability, last-success
  timestamps, staleness per adapter, rate-limit and retry state.
- Every `AdapterResult` carries `latency_ms`, `provider_request_id`,
  `correlation_id`, and `rate_limit` — observability without extra probes.
- Certification runs are recorded; a provider's earned readiness is auditable.

## Limits & follow-on

**Universal connector foundation in this branch:** manifests can declare
independently addressable streams, raw v2 records preserve account/realm/object
revisions, non-identity source objects have scoped opaque IDs and aliases,
and a pure length-prefixed helper encodes the proposed 160-bit logical event
ID. The helper does not verify account evidence or publish facts; the object
repository verifies account ownership. `provider_object_refs` remains
repository-only: Shopify normalizers do not call it, emitted Shopify events do
not carry its IDs, and graph projection does not consume it. Tenant routes have
audited transitions plus an opt-in graph writer fence. The graph writer holds
a PostgreSQL route row lock through a bounded enforced gateway call and
rejects absent PostgreSQL outside local mode.
Shopify's GraphQL orders adapter is opt-in and remains credential-waiting.
These primitives do not make cutover or commerce graph projection live: both
legacy and native writers must use the route fence, provider facts need
authority/reconciliation and projection consumers, and provider replay and
external sandbox evidence must pass their own gates. The
[implementation blueprint](blueprints/universal-connector-runtime/README.md)
tracks the complete target and remaining acceptance evidence.

The tenant sync route accepts an optional `stream_ids` list (maximum 32 unique,
nonblank IDs, each at most 128 characters) in addition to `since`. It rejects
the complete selection before provider work unless every requested stream is
declared, pullable, and active; empty or omitted selection runs every active
pull stream. The API does not yet provide a durable long-backfill job request.

**Update (follow-on program, shipped):** the UPR follow-on program landed as
PR-A (shared seams + legacy SSRF hardening) → PR-B (six native provider
plugins, scheduled-worker cron, config/secret migration projections) → PR-C
(web SDK detection engine + commerce bridges) → PR-D (Kyber manifest-driven UI
+ convergence tracker + final docs). The SDK event-registry convergence merge
remains a dedicated program (tracker-only in the follow-on).

**Build status (shipped):** the six native provider plugins (WS1), the
scheduled-worker cron (WS5), config/secret migration projections (WS6), the
web SDK detection engine + commerce bridges (WS2), and the Kyber
manifest-driven UI (WS3) are all shipped in this follow-on program. SDK
event-registry convergence (WS4) remains tracker-only — its merge stays
deferred to a dedicated convergence program.

**WS8 hardening scope:** the six host-bearing legacy connectors (Shopify, Salesforce, PostHog, Jira, Zendesk, Dune) and the Braze connector now validate tenant-supplied base URLs against provider allowlists (fail-closed). Intentional consequences: self-hosted PostHog on custom domains, Salesforce instances outside `*.salesforce.com` / `*.force.com`, and explicit `:443` in URLs are now denied; Salesforce `*.lightning.force.com` and `*.my.salesforce.com` remain covered. Empty-label and resolver-IP spellings are rejected by the shared seam.

- **Not built in this program**: SDK event-registry convergence only — the
  dotted `commerce.*` types stay runtime-domain (mirroring the `comms`
  precedent) until a dedicated convergence program. Every other follow-on item
  (six native plugins, scheduled-worker cron, config/secret migration
  projections, web SDK detection engine + commerce bridges
  ([SDK-COMMERCE-BRIDGES](SDK-COMMERCE-BRIDGES.md)), Kyber manifest-driven UI)
  is built.
- **Migration**: legacy connectors are exposed via `LegacyConnectorPlugin`
  today and migrate per-provider to native plugins tomorrow — never
  core-first (see [PROVIDER-MIGRATION](PROVIDER-MIGRATION.md)).

## Related docs

- [ADR-009: Universal Provider Runtime](decisions/ADR-009-universal-provider-runtime.md) — the decision record
- [PROVIDER-PLUGIN-SPEC](PROVIDER-PLUGIN-SPEC.md) — how to write a plugin
- [PROVIDER-MANIFEST-SPEC](PROVIDER-MANIFEST-SPEC.md) — the manifest + honesty invariants
- [PROVIDER-CERTIFICATION](PROVIDER-CERTIFICATION.md) — the certification harness
- [COMMERCE-EVENT-CONTRACT](COMMERCE-EVENT-CONTRACT.md) — the canonical commerce vocabulary
- [SDK-COMMERCE-BRIDGES](SDK-COMMERCE-BRIDGES.md) — the web SDK detection engine + commerce bridges (shipped)
- [PROVIDER-MIGRATION](PROVIDER-MIGRATION.md) — migrating a legacy connector
