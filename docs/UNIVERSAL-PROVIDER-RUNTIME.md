---
title: Universal Provider Runtime
slug: architecture/universal-provider-runtime
section: architecture
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/main.py
  - Backend Architecture/aether-backend/config/settings.py
  - Backend Architecture/aether-backend/shared/rate_limit/feature_gate.py
  - Backend Architecture/aether-backend/shared/integration_contracts/
  - Backend Architecture/aether-backend/shared/commerce_contracts/
  - Backend Architecture/aether-backend/services/provider_runtime/
  - Backend Architecture/aether-backend/services/providers/
  - Backend Architecture/aether-backend/services/providers/shopify/
canonical_owner: platform@aether
estimated_read_minutes: 14
toc_depth: 3
last_synced_commit: "83ac3569"
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
| Plugin contract | `Backend Architecture/aether-backend/shared/integration_contracts/` | `ProviderPlugin` protocol, manifest + honesty invariants, capability adapters, canonical results, normalization, events, certification contracts |
| Commerce vocabulary | `Backend Architecture/aether-backend/shared/commerce_contracts/` | Provider-neutral Money / Order shapes and the canonical `commerce.*` event-type set |
| Runtime service | `Backend Architecture/aether-backend/services/provider_runtime/` | Registry → orchestrator → pipeline → engines → API; registers, certifies, and executes plugins |
| Plugin modules | `Backend Architecture/aether-backend/services/providers/*/` | One package per provider capability (reference: `services/providers/shopify/`) |
| Legacy compat | `services/provider_runtime/legacy.py` (`LegacyConnectorPlugin`) | Exposes every existing `BaseConnector` as a plugin with zero code changes |

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
│                     services/provider_runtime                             │
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
   │ Plugin modules (services/providers/*/)                          │
   │   services/providers/shopify/   (native plugin)                 │
   │   ...future native plugins...                                    │
   │   LegacyConnectorPlugin          (wraps BaseConnector, identity │
   │                                    (connector_type,"ingestion", │
   │                                    "connector") — byte-identical │
   │                                    to catalog-derived manifest)  │
   └────────────────────────────────────────────────────────────────┘
```

### Package layout

```
Backend Architecture/aether-backend/
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
│   │   ├── certification.py            #   CertificationReport, readiness tokens
│   │   ├── catalog.py                  #   catalog-derived manifests (legacy)
│   │   └── ...                         #   lifecycle, deployment, health
│   ├── commerce_contracts/             # commerce vocabulary (additive)
│   │   ├── money.py                    #   Money, Currency, sum_money, money_from_cents
│   │   ├── order.py                    #   CommerceOrder, OrderSnapshot, order_to_snapshot
│   │   └── events.py                   #   COMMERCE_EVENT_FAMILIES (9 canonical types)
│   └── rate_limit/feature_gate.py      # one sanctioned change: /v1/provider-webhooks/
├── services/
│   ├── provider_runtime/               # NEW — the runtime service
│   │   ├── acquisition.py              #   account discovery/selection coordinator
│   │   ├── bridge.py                   #   event bridge (canonical event → Bronze + bus)
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
│   │   ├── reconciliation.py           #   reconciliation
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
        │  durable, re-playable
        ▼
Normalization engine (EventNormalizer.normalize)
        │  deterministic, network-free; NormalizationResult
        ▼
Event bridge
  1. canonical AetherEvent → bronze_connectors (existing store)
  2. event bus publish                        ← Bronze-before-publish
        ▼
Downstream consumers (analytics, outbox, intelligence)
```

The pipeline honors three invariants:

- **Idempotency.** `RawProviderRecord.idempotency_key` dedups raw ingestion;
  `AetherEvent.idempotency_key` dedups event publication. Re-running a pull or
  replaying a webhook never double-persists or double-publishes.
- **Bronze-before-publish.** An `AetherEvent` is only published after its raw
  record is durably stored, so replay cannot fabricate events the lake lacks.
- **Deterministic normalization.** A normalizer never depends on wall-clock,
  randomness, or provider I/O; anything it cannot translate is surfaced via
  `dropped`, never silently skipped.

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
  and an auditable denial record — there is no "no secret ⇒ trust" path.

## How a new provider lands

1. **Build the plugin package** (`services/providers/<family>/`): plugin class,
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
