---
title: "ADR-009: Universal Provider Runtime"
slug: decisions/adr-009-universal-provider-runtime
section: reference
visibility: I
audience: [architect, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
---

# ADR-009: Universal Provider Runtime

**Status**: Accepted (8.12.0)

## Context

Aether's inbound integration surface is a **closed union of connector types**.
`services/integrations/connectors/base.py` defines
`ConnectorType = Literal[...]` — a single, ever-growing union of 61 connector
ids — plus the `BaseConnector` hierarchy and the `CONNECTORS` registry (21
registered connectors). Adding
a provider touches core code paths: the union, the registry, credential
wiring, sync plumbing, the route surface, and the derived catalog. The
integration control plane has begun layering provider-neutral contracts
(`shared/integration_contracts`), but the runtime that *executes* a provider
is still the connector framework.

Three concrete problems:

- **Closed unions grow everywhere.** A new provider edits `ConnectorType`,
  `ConnectorCategory`, the registry, and any switch over connector types. One
  provider means many coordinated edits across core modules — and each edit
  risks breaking every connector that shares the union.
- **A provider is not a self-contained unit.** There is no "drop the plugin,
  register it, done". A provider's identity, manifest, adapters, and
  normalization are spread across the framework rather than owned by the
  provider module.
- **The catalog and the connector can drift.** The catalog is *derived* from
  connector descriptors (`shared/integration_contracts/catalog.py`) and the
  runtime executes connectors; nothing enforces that what a connector claims
  matches what it actually does.

The goal: a provider should be a **self-contained plugin** — its own package
declaring identity, a manifest, capability adapters, and a normalizer —
registered and certified as a unit, with the legacy system kept intact and
working.

## Decision

Adopt a provider-neutral **Universal Provider Runtime (UPR)** as an
**additive migration — NOT a rewrite**. The legacy `BaseConnector` system
stays untouched and working; the UPR adds a parallel provider-neutral runtime
and becomes the **authoritative** integration surface for new providers.
Concretely:

- New **`shared/integration_contracts`** extension — plugin protocol,
  manifest + honesty invariants, capability adapters, canonical results,
  normalization, certification contracts.
- New **`shared/commerce_contracts`** — provider-neutral commerce vocabulary
  (Money, Order, canonical event-type classification).
- New **`services/provider_runtime`** service — registry → orchestrator →
  pipeline → engines → API.
- New **`services/providers/shopify`** reference plugin.
- **Legacy compatibility** via a `LegacyConnectorPlugin`
  (`services/provider_runtime/legacy.py`) that exposes every existing
  connector with zero code changes, delegating lifecycle to the existing
  `IntegrationAdapter` / `ConnectorIntegrationAdapter`.
- **One sanctioned feature-gate change**: `/v1/provider-webhooks/` is added
  to `PUBLIC_PATH_PREFIXES` in `shared/rate_limit/feature_gate.py` (the route
  is unauthenticated by API key and HMAC-verified inside the handler, matching
  the existing `/v1/integrations/webhooks/` precedent).

The legacy system keeps working. The UPR becomes authoritative: new providers
land as plugins; legacy connectors continue to operate through the compat
plugin until individually migrated (see `PROVIDER-MIGRATION.md`).

## Key design decisions (binding)

### D1 — Plugin identity is `family.product.capability`

Identity is **per-capability**, not per-provider: `family.product.capability`
(e.g. `shopify.admin.orders_read`). The catalog-derived manifest maps every
existing connector onto `(connector_type, "ingestion", "connector")` — the
**byte-identical** identity the `LegacyConnectorPlugin` exposes, so the plugin
and the catalog cannot drift. Native `shopify.admin.orders_read` identities
coexist with legacy `(type, "ingestion", "connector")` identities. **No
provider names appear in central type unions** — the UPR registers identities,
it does not extend a `Literal`.

### D2 — Raw-before-canonical

A `RawProviderRecord` is persisted **before** normalization, idempotently via
`BronzeRepository("provider_records")` (`repositories/lake.py`). The canonical
`AetherEvent` then flows to the existing `bronze_connectors` store and the bus
publish. **Bronze-before-publish** — an event is only published after its raw
record is durably stored, so replay never fabricates data the lake does not
have.

### D3 — Honesty

Every manifest claim is backed by a real adapter, enforced at **registration
AND certification**. `validate_manifest` is unchanged and still the gate for
manifest-level honesty (see `PROVIDER-MANIFEST-SPEC.md`). A plugin cannot
claim a capability it does not implement, an environment it has not
validated, or a webhook scheme it does not verify.

### D4 — Reuse, not rewrite

`IntegrationAdapter` / `ConnectorIntegrationAdapter`
(`services/integrations/adapter.py`) stay **authoritative** for the legacy
lifecycle. The credential service (`shared/credentials/service.py`),
`SyncRunService`, `WebhookInbox`, `BronzeRepository`, and
`ingest_normalized_events` are all reused. The UPR composes these systems; it
never re-implements them.

### D5 — Canonical events are provider-neutral

The canonical event vocabulary is `commerce.order.created` and the other
curated `commerce.*` types (`shared/commerce_contracts/events.py`). Provider
identity lives in `AetherEvent.provider` / `AetherEvent.provider_identity` and
in `context` — never in `event_type`. Legacy connectors keep their namespaced
event types during migration; only migrated plugins emit canonical
`commerce.*` events.

### D6 — Feature-gated

UPR routes are **off by default** (`AETHER_PROVIDER_RUNTIME_ENABLED=False`,
`config/settings.py` `ProviderRuntimeConfig`). Nothing is reachable until an
operator enables it. The connections and public webhook routers mount with the
main flag; the admin router (`/v1/admin/kyber/provider-connections`, incl.
`/certify`) requires a second flag `KYBER_PROVIDER_RUNTIME_HEALTH_ENABLED`.
`main.py` wires the runtime conditionally (see
`UNIVERSAL-PROVIDER-RUNTIME.md`).

### D7 — No secrets anywhere

Credentials exist **only** as `credential_service` refs. Plugins and
manifests describe credential *shape* (`CredentialFieldSpec`), never values.
A manifest must never carry a secret; the certification harness rejects one
that does.

## Security invariants (binding)

- Credentials never stored in source, frontend bundles, logs, prompts, or
  manifests — only as `credential_service` refs resolved at call time.
- `/v1/provider-webhooks/` is unauthenticated by API key and MUST
  self-verify (HMAC/signature) inside the handler before processing,
  **fail-closed**: a signature scheme without a configured secret, or an
  `endpoint_secret` scheme without a matching per-connection token, is DENIED
  (closed 4xx + auditable denial record). There is no "no secret ⇒ trust"
  path.
- Provider adapters never receive direct database authority; the runtime
  executes all persistence.
- Tenant scope is server-authoritative; raw records and events are
  tenant-scoped end to end.
- Staging/production fail closed on missing credentials or unsafe
  configuration.
- Never log API keys, authorization headers, or raw secret values.

## Consequences

### Positive

- **Self-contained providers.** A provider is a plugin package: identity,
  manifest, adapters, normalizer — registered and certified as a unit. No
  more edits to core unions.
- **No more union sprawl.** Provider names leave central `Literal` types; the
  registry is data, not a type.
- **Honesty enforced.** A manifest is only as strong as its adapters and its
  certification; plugin and catalog cannot drift.
- **Additive safety.** The legacy system is untouched; the UPR ships behind a
  flag default OFF and reuses existing authority (credentials, Bronze, bus,
  sync, webhook inbox).
- **Provider-neutral events.** Downstream consumers read canonical
  `commerce.*` events; provider churn stays behind the adapter seam.

### Negative / trade-offs

- **Parallel runtime.** The UPR is a second execution surface that must stay
  consistent with the legacy one during the migration window. The
  `LegacyConnectorPlugin` and the migration ordering (expose → certify → map →
  decommission, per-provider) bound but do not eliminate this.
- **Certification cost.** Honesty at registration + certification adds a
  quality gate every plugin must pass; plugins cannot claim more than they
  ship.
- **Event vocabulary tension.** Canonical `commerce.*` types are runtime-domain
  today and NOT yet in the SDK event registry — downstream SDK consumers must
  be bridged (follow-on), and the split must be documented until convergence.

## Follow-on (explicitly OUT of this program)

The following are deliberately deferred; they are scoped in
`SDK-COMMERCE-BRIDGES.md` where relevant and are NOT built in this program:

**Update (follow-on program — SHIPPED):** the UPR follow-on program delivered
WS1 (six native provider plugins: WooCommerce, Etsy, Amazon, eBay, Walmart,
TikTok), WS2 (web SDK detection engine + commerce bridges), WS3 (Kyber
manifest-driven operator UI), WS5 (scheduled-worker cron for provider sync),
WS6 (config/secret migration projections — engine + Shopify mapping ship;
other families are table rows + framework, explicitly unbuilt), WS7 (legacy
decommission plumbing, Shopify only), and WS8 (legacy SSRF hardening). The
SDK event-registry convergence merge (WS4) remains a dedicated program —
tracker-only in this follow-on. Live credential certification for the new
plugins (real OAuth exchanges, real replay, SigV4 round-trips) is
certification-level follow-on work, not a build claim.

**WS8 hardening scope:** the six host-bearing legacy connectors (Shopify, Salesforce, PostHog, Jira, Zendesk, Dune) and the Braze connector now validate tenant-supplied base URLs against provider allowlists (fail-closed). Intentional consequences: self-hosted PostHog on custom domains, Salesforce instances outside `*.salesforce.com` / `*.force.com`, and explicit `:443` in URLs are now denied; Salesforce `*.lightning.force.com` and `*.my.salesforce.com` remain covered. Empty-label and resolver-IP spellings are rejected by the shared seam.

- **WooCommerce / Etsy / Amazon / eBay / Walmart / TikTok** native plugins.
- **Web SDK detection engine + commerce bridges** — detect commerce frames on
  the web, map canonical `commerce.*` `AetherEvent`s to SDK event shapes,
  bridge `OrderSnapshot` into SDK payloads, server-side confirmation
  (`SDK-COMMERCE-BRIDGES.md`).
- **Kyber manifest-driven UI** — operator UI driven by `ProviderManifest`
  instead of connector-specific code.
- **SDK event-registry convergence** — dotted `commerce.*` event types stay in
  the runtime domain, mirroring the `comms` precedent, until a
  registry-convergence program merges them into the SDK `EventType` union.
- **Scheduled-worker cron** — scheduled provider sync is manual-trigger only in
  this program.
- **Config/secret migration projections** — automatic projections from legacy
  connector config to UPR credential refs.

## References

- `Backend Architecture/aether-backend/shared/integration_contracts/` — plugin
  protocol (`plugin.py`), manifest + honesty invariants (`manifest.py`),
  capability adapters (`capabilities.py`), canonical results (`results.py`),
  normalization (`normalization.py`), events (`events.py`), certification
  contracts (`certification.py`).
- `Backend Architecture/aether-backend/shared/commerce_contracts/` — Money,
  Order vocabulary, and the canonical `commerce.*` event-type set.
- `Backend Architecture/aether-backend/services/provider_runtime/` — the UPR
  service (registry, orchestrator, pipeline, engines, API): `registry.py`,
  `plugin.py` (`register_provider`), `validation.py`, `legacy.py`
  (`LegacyConnectorPlugin`), `certification.py` (`certify_provider`),
  `webhook.py` (fail-closed gateway), `routes.py`.
- `Backend Architecture/aether-backend/services/providers/shopify/` — the
  reference native plugin (`plugin.py`, `auth.py`, `account.py`, `pull.py`,
  `webhook.py`, `normalizer.py`, `payloads.py`).
- `Backend Architecture/aether-backend/services/integrations/connectors/base.py`
  — the legacy `ConnectorType` union and `BaseConnector` hierarchy this ADR
  layers on (untouched).
- `Backend Architecture/aether-backend/services/integrations/adapter.py` — the
  authoritative `IntegrationAdapter` / `ConnectorIntegrationAdapter` lifecycle
  facade reused by the compat plugin (D4).
- `Backend Architecture/aether-backend/shared/rate_limit/feature_gate.py` — the
  one sanctioned change: `/v1/provider-webhooks/` added to
  `PUBLIC_PATH_PREFIXES`.
- `docs/decisions/ADR-007-domain-canonicalization.md` — the one-source-of-truth
  precedent this ADR extends.
- `docs/UNIVERSAL-PROVIDER-RUNTIME.md` — architecture of the runtime service.
