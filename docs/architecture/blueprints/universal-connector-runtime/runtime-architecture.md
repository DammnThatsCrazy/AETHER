---
title: Universal Connector Runtime — Runtime Architecture
slug: blueprints/universal-connector-runtime/runtime-architecture
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: experimental
since_version: "0.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 30
toc_depth: 3
---

# Universal Connector Runtime — runtime architecture

**Status:** implementation blueprint, not a statement that the target behavior is shipped.

**Repository baseline:** `origin/main` at `7b1fb6f58f0281c7e0929d241b3dbf1a2ed87aed` (2026-10-02 worktree snapshot).

**Scope:** all Aether-managed inbound provider connectors and their relationship to SDK, import, outbound, payment, derivatives, and other specialized integration planes.

**Companion specifications:** [canonical IDs and events](canonical-contracts.md), [migration and delivery](migration-and-delivery.md), and the [commerce reference slice](commerce-reference-slice.md).

## 1. Binding decision

Extend the **existing Universal Provider Runtime (UPR)** under `services/backend/services/provider_runtime/` into the common inbound connector execution seam. Keep its capability-level `ProviderIdentity` (`family.product.capability`), plugin honesty gate, credential broker, connection lifecycle, Bronze storage, sync ledger, webhook gateway, and certification harness. Add stream declarations, raw revision handling, domain-pack validation, source authority, governed graph handoff, per-stream readiness, and replay as extensions of those authorities. Do not create a second `packages/connector-runtime` or `apps/api` implementation: those paths in the referenced ChatGPT draft do not match this repository.

The shared *product* concept is a connector, but that does not make every provider-shaped subsystem a UPR `ProviderPlugin`. First-party SDK events remain observations through the existing ingestion adapters. Imports remain governed import jobs. Outbound delivery keeps its action authorization, receipts, and retry authority. Payment rails, trading/derivatives, BYOK model gateways, and interop each have specialized security and financial state machines; they may reuse manifests, credential references, Bronze provenance, and readiness projections without being moved blindly into an inbound polling runtime.

This decision refines [ADR-009](../../decisions/ADR-009-universal-provider-runtime.md) rather than superseding its additive migration or security rules. The transition is per capability and per tenant, under the gates in [migration and delivery](migration-and-delivery.md).

## 2. Repository truth and document reconciliation

| Surface | Verified current behavior | Target disposition |
|---|---|---|
| `shared/integration_contracts/{plugin,manifest,capabilities,identity,events,normalization}.py` | Typed `ProviderPlugin`, `ProviderManifest`, adapter protocols, `RawProviderRecord`, `AetherEvent`, deterministic normalizer contract. The feature branch adds stream descriptors and manifest activation honesty checks, a repository-only source-object reference store, raw source-revision fields, and additive event schema-v2 revision fields. The object-reference store is not wired into Shopify normalization, emitted events, or graph projection. | Extend with source/subject/governance provenance, authority and reconciliation decisions, generated contract twins, and migration adapters for ABI changes. |
| `services/provider_runtime/{registry,plugin,validation,certification}.py` | Native plugins and `LegacyConnectorPlugin` register through one honesty gate. Local plugins include Shopify, WooCommerce, Etsy, Amazon, eBay, Walmart, TikTok. Certification is structural/replay evidence, not proof of live provider operation. | Register streams and certify each claimed stream, auth scope, webhook topic, normalizer, and destination. Keep provider identity collisions fail closed. |
| `services/provider_runtime/{connection,credential_broker,scheduler,sync_worker,webhook,raw_store,normalization,bridge,health}.py` | Connection state, credential refs, pull schedule, webhook verification, Bronze raw storage, event bridge, health. The feature branch adds account/stream-scoped cursor keys, activation/default resolution, selected-account stream execution, raw scope checks, declared webhook-stream enforcement, post-verification and post-rights-admission inbox persistence, bounded raw replay, tenant-route/writer primitives, and a typed outbox bridge. Raw acquisition requires an allowed, tenant-scoped `RightsDecision` for the verified provider account before body retention or normalization; replay requires the referenced immutable decision and a fresh rights check. Canonical grants and create/revoke events now use the migration-owned DataRights repository; staging/production admission checks persistent database and schema availability and fails closed when unavailable. | Prove durable rights/provenance admission in the target environment; then add all-writer generation fencing, durable authority/reconciliation, authenticated operator controls, comparative shadow evidence, and an evidence-backed per-stream readiness projection. |
| `services/providers/shopify/` | Native `shopify.admin.orders_read` plugin has mode-specific REST polling, REST polling plus signed webhooks, and opt-in GraphQL order pulling pinned to `2026-07`. Manifest remains credential-waiting and unavailable for staging/production; no tenant self-service claim or provider sandbox certification exists. | Add GraphQL bulk historical export, close v1 REST/webhook raw revision/convergence limitations, and certify further streams only with real adapters and fixtures. |
| `services/integrations/connectors/{base,registry,service,routes}.py` | Legacy `BaseConnector` integration path, tenant configuration, sync and webhooks. `LegacyConnectorPlugin` wraps it without renaming legacy events. | Keep it operational during migration; route each migrated capability to native UPR only after cutover evidence. |
| `shared/commerce_contracts/{money,order,events}.py` | Provider-neutral money, order snapshot, and a curated `commerce.*` event classification. | Expand here for commerce-specific invariants; keep payment/accounting source authority explicit. Do not use `services/commerce/` as this domain pack: that service currently owns agentic/x402 commerce control behavior. |
| `services/ingestion/{adapters,validation,spine}.py`, `/v1/batch` | SDK observation ingress and shared validation. For provider records admitted by the tenant raw-rights gate (`ProviderRawRightsAdmission`), the UPR bridge writes canonical Bronze/outbox for `SDK_EVENTS_VALIDATED`; a record without an allowed tenant grant is never retained. | Define one downstream canonical governance handoff for SDK, import, webhook, and provider events while preserving their distinct acquisition paths and trust classes. |
| `services/identity/{source_identity_registry,integration,source_precedence}.py`, `shared/graph/mutation_gateway.py`, `shared/intelligence_projections/` | Existing source-identity, source-precedence, graph mutation, and intelligence projection authorities. | Extend source precedence with field-level domain policy; feed accepted facts through a governed domain service. Provider adapters never choose profile truth, write graph nodes/edges, or write lens projections directly. |
| `shared/integration_contracts/catalog.py`, `services/readiness_graph/tenant_integration_readiness*.py`, `shared/certification/readiness.py` | Derived catalog and evidence-based readiness vocabulary; connected is distinct from ready. | Compose native UPR stream/connection evidence into the existing catalog and tenant readiness projection, without a new catalog store or readiness enum. |

The repository rows above describe the pinned `origin/main` inventory baseline; the feature-branch additions are called out explicitly in the rows. The [target connector runtime page](../../target/connector-runtime-productization.md) is updated in this blueprint branch to distinguish the current UPR foundation from the proposed extensions. [ADR-009](../../decisions/ADR-009-universal-provider-runtime.md) governs additive migration and no-secret policy. [Shopify operations](../../../reference/SHOPIFY-CONNECTOR.md) describes the legacy `shopify.order` path; the native plugin now documents REST, REST-webhook, and GraphQL modes. Preserve a legacy/native capability table until cutover is complete.

**Current raw-admission limitation:** the admission decision is tied to the verified provider account using `source_id="provider-account:{connection_id}:{account_id}"`. It requires a tenant-scoped `DataRightsGrant` whose `tenant_id` matches the connection, `connector_id` equals the provider identity, `connector_class` is `tenant_byod_data`, and tenant-lake permission is granted. The `RightsDecision` record is immutable and tenant-scoped; replay must reference that original decision and perform a fresh rights check before normalizing. However, `DataRightsService` still stores grants in process memory. Therefore provider raw admission in staging/production remains fail-closed until the grant store is durable; a recorded decision alone cannot replace the current grant lookup. Existing Bronze rows created before this rights gate remain quarantined because they lack persisted raw-rights admission evidence and an original allowed `RightsDecision` reference. Replay rejects quarantined rows and requires that reference plus a fresh grant check. There is no historical-row re-admission path, so operators cannot manually unquarantine or replay them. A future governed path must resolve immutable decision evidence for each unchanged row and perform a fresh rights check; it cannot rewrite raw/provenance/quarantine fields. `BronzeRepository.update` otherwise permits only appending IDs to `payload.metadata.confirmed_signal_ids`. This guard does not authorize indefinite retention: raw data may be retained only while its rights and retention basis remain valid, and deletion/suppression follows the lifecycle authority. A provider adapter or manifest cannot grant admission.

## 3. Repository-wide integration posture

The table is a routing inventory, not an assertion that each named provider has been certified live. A detailed per-provider capability/evidence matrix is an implementation deliverable. `WRAP` means reuse through an adapter and migrate only if the shared runtime adds value; `SHARE` means share contracts, credential and readiness projections while retaining the current execution authority.

| Subsystem and current owner | Examples / existing path | Posture | Boundary and first action |
|---|---|---|---|
| Native UPR inbound plugins | Shopify, WooCommerce, Etsy, Amazon, eBay, Walmart, TikTok in `services/providers/*/` | **EXTEND** | Keep UPR as execution authority; inventory the actually implemented `orders_read` and other claimed capabilities. Add stream contracts and certification before expanding outputs. |
| Legacy tenant connector catalog, with inbound and dual-role entries | Stripe webhook, Shopify, HubSpot, Salesforce, Segment, PostHog, GA4, Slack, Jira, Linear, Zendesk, Intercom, generic webhook in `services/integrations/connectors/` | **WRAP → MIGRATE selectively** | Existing `LegacyConnectorPlugin` remains compatibility. Migrate each inbound capability after parity and cutover; preserve outbound action authority for dual-role providers. Do not globally retire the legacy registry. |
| Lifecycle and communications connectors | Klaviyo, Mailchimp, SendGrid, Postmark, Iterable, Braze, Customer.io in `services/integrations/connectors/` and `services/comms/` | **WRAP / SHARE** | Preserve delivery, suppression, consent, and campaign authority; normalise inbound messages/events through a communications pack when proven. Outbound sending remains with delivery/comms. |
| Measurement and paid media | Google Ads, Meta Ads, TikTok Ads, LinkedIn Ads, X Ads, Reddit Ads, Microsoft Ads, file import, generic webhook in `services/measurement/connectors/` | **SHARE then WRAP** | Measurement connector currently owns spend/conversion/touchpoint writes and durable cursor. Adapt raw acquisition and manifests first; preserve measurement repositories and attribution versions until comparative parity. |
| Derivatives market/account sources | Hyperliquid and generic import in `services/derivatives/connectors/`; venue adapters under `services/derivatives/adapters/` | **SHARE** | Read-only scopes, venue checkpoints, normalized fill facts, and derivatives controls remain domain-owned. UPR can expose discoverability/health and raw lineage once those controls are mirrored. No trade execution methods are introduced. |
| Payment rails and billing | Payment-rail adapters in `services/integrations/providers/payment_rails/`; billing providers in `services/billing/providers/` | **SHARE** | Preserve payment signatures, settlement/reconciliation, entitlements, financial ledgers, and billing authority. Connector runtime may provide acquisition metadata and health; payment truth comes from the payment domain. Stripe billing and Stripe transaction ingestion are separate capabilities. |
| Outbound actions and notifications | `services/delivery/adapters/`, `services/delivery/worker.py`, `services/managed_integrations/` | **STAY / SHARE** | Keep approval, authorization, idempotent dispatch, external receipt, audit, and rollback semantics. A provider may have both inbound and outbound capabilities, but their grants and jobs are separate. |
| BYOK, model providers, corpus, interop and chain data | `services/model_runtime/credentials/`, `services/providers/credentials/`, `services/interop/providers/`, `services/stablecoins/` | **SHARE only when applicable** | These are credential/execution or specialized data planes, not all tenant connectors. Reuse canonical provider identity, manifest honesty, secrets policy, and tenant-safe health where semantics fit; domain owners retain execution. |
| SDK, API feeds, imports, replay | `services/ingestion/adapters/`, `services/imports/`, SDK packages under `packages/` | **OBSERVATION INGRESS** | Converge at the validated canonical event/authority seam. SDK is not a UPR plugin and does not acquire provider credentials. Import review, mapping, and commit remain in the import authority. |

Before changing any subsystem, record its owner, direction (inbound/outbound/bidirectional), tenant/source trust class, credential authority, cursor/receipt, canonical outputs, graph policy, readiness evidence, tests, and current flag. `docs/reference/connectors/subsystem-registry.md` captures three connector subsystems and UPR, but the table above intentionally includes additional provider-shaped planes found in source.

## 4. Target execution graph

```text
Provider capability manifest + stream descriptors
    → server-authoritative tenant connection and scoped credential reference
    → adapter (pull / signed webhook / report / stream)
    → verified, revision-addressable RawProviderRecord in Bronze
    → domain-pack normalizer and schema/rights/consent validation
    → canonical event + provenance, or durable quarantine reason
    → source-authority and canonical-ID resolution
    → domain reconciliation and one eligible graph mutation intent
    → GraphMutationGateway → projection providers → lenses / 360s / readiness

SDK observations / reviewed imports / internal events
    → their existing ingress authority → same canonical governance stage

Outbound action request
    → existing policy + delivery worker + receipt authority
    → optional verified outcome observation into the canonical governance stage
```

This is a target flow. For a raw record admitted by the raw-rights and persisted provenance gates, the current UPR `EventBridge` ends at typed Bronze plus `SDK_EVENTS_VALIDATED` outbox publication; the downstream domain, source-authority, and graph path must be wired and proven as an explicit implementation slice. Provider admission stays disabled by default; staging/production denies raw retention unless the durable grant schema is installed and available. Existing rows from the earlier path remain quarantined and require their immutable referenced `RightsDecision` plus a fresh rights check before replay. The diagram does not authorize a provider adapter to write graph truth.

### 4.1 Responsibility split

| Owner | Owns | Must not own |
|---|---|---|
| Provider module (`services/providers/<family>/`) | Provider API, auth/scopes, account discovery, pagination, signature verification, provider-specific parsing, deterministic mapping to domain candidate events, provider fixtures | Tenant authorization, durable credential values, global scheduler, canonical profile merge, domain authority policy, graph mutations, lens projections |
| UPR (`services/provider_runtime/`) | Plugin registry, connection lifecycle, credential resolution, rate/retry coordination, stream job scheduling/checkpoints, raw storage, quarantine/replay, canonical bridge, sync/run/health evidence | Provider-specific objects in core unions, financial semantics, identity truth, direct product projections |
| Domain pack (`shared/<domain>_contracts/` plus domain service) | Provider-neutral event/entity schema, lifecycle/money/attribution rules, source-authority defaults, reconciliation requests, graph mutation mapping | OAuth/token storage, provider pagination, direct external API calls |
| Existing authorities | Identity resolution, consent/data rights, ingestion validation, graph mutation gateway, projection registry, delivery and payment ledgers, readiness graph | Unvalidated provider assumptions or duplicate runtime registries |

### 4.2 Target repo shape, deliberately incremental

```text
services/backend/shared/integration_contracts/
  streams.py                 # NEW typed StreamDescriptor + policy/reference fields
  events.py                  # EXTEND raw revision/provenance; keep compatibility
  manifest.py                # EXTEND stream declarations and honesty validation
  capabilities.py            # EXTEND only if stream-aware adapter ABI is needed
services/backend/shared/commerce_contracts/
  ...                        # EXTEND commerce money/lifecycle/source rules
services/backend/shared/<domain>_contracts/
  ...                        # ADD only for a real second domain slice
services/backend/services/provider_runtime/
  registry.py                # EXTEND registered stream inventory
  scheduler.py               # EXTEND stream-specific jobs/checkpoints
  raw_store.py               # EXTEND revision-aware durable record receipt
  normalization.py           # EXTEND typed quarantine and domain validation
  bridge.py                  # EXTEND durable outbox/authority handoff
  health.py                  # EXTEND per-stream evidence
  replay.py                  # NEW controlled replay service (not a second runtime)
services/backend/services/providers/<family>/
  plugin.py, auth.py, account.py, pull.py, webhook.py,
  streams.py, normalizers/    # ADD only for capabilities claimed by manifest
services/backend/services/ingestion/
  ...                        # REUSE observation ingress and consent validation
services/backend/services/identity/
  ...                        # REUSE source identity and resolution authority
services/backend/shared/graph/
  mutation_gateway.py        # REUSE governed graph writes
services/backend/shared/intelligence_projections/
  ...                        # REUSE projection registration and evidence contracts
```

The concrete file split is proposed. Before creating a file, inspect the existing module and extend it if it already owns that behavior. No TypeScript package duplicate of Python runtime logic is required; frontend types should be generated or validated against the backend API contract.

## 5. Module contract and stream semantics

### 5.1 Backward-compatible plugin extension

Retain `ProviderPlugin.identity()`, `manifest()`, `auth()`, `account()`, `pull()`, `webhook()`, `report()`, `stream()`, `reconciliation()`, and `normalizer()`. Add a versioned, optional stream declaration to the plugin/manifest, and certify that declarations agree with implemented adapters. An ABI v1 plugin with no stream declarations projects to **one legacy capability stream** and keeps its existing behavior until migrated. A new ABI must be explicitly versioned and validated by `ProviderRegistry`; do not silently reinterpret v1 data.

Proposed shape (field names are a design contract; final wire schema belongs in [canonical contracts](canonical-contracts.md)):

```python
class StreamDescriptor(BaseModel):
    stream_id: str                 # stable within ProviderIdentity
    object_kind: str              # e.g. order, refund, product, campaign
    domain_pack: str              # commerce, payments, communications, ads, ...
    acquisition_modes: frozenset[str]  # pull/webhook/report/stream/import
    required_scopes: frozenset[str]
    cursor_scheme: str | None
    webhook_topics: frozenset[str]
    source_authority_class: str   # domain policy key, never provider code
    output_contract: str          # schema/version reference
    pii_classification: str
    enabled_by_default: bool = False
```

`stream_id` is never a provider display label; it is a stable key in a capability. A stream is independently enabled, backfilled, paused, replayed, certified, and reported unhealthy. A provider package may share an HTTP client/auth adapter across streams. The feature branch adds a hashed cursor key for **tenant + connection + provider identity + selected account + stream** while retaining the old three-part key for streamless v1 plugins. It does not migrate legacy cursor values into newly declared streams; those streams start with their own checkpoint and need a reviewed overlap/backfill plan. One sync run records requested and completed stream IDs, page counts, raw/accepted/quarantined counts, high-water mark, rate-limit/retry evidence, and terminal outcome. A failed page never advances a cursor; an empty successful page may advance only per provider cursor semantics. No unbounded page or full-history sweep.

For webhooks, the gateway resolves a candidate connection, verifies the raw bytes or endpoint token, rechecks the tenant/connection/account binding, parses the delivery, and requires successful raw-rights admission before retaining the full request body in the webhook inbox. If rights admission fails, neither the request body nor a tenant-scoped raw denial record is retained. Before a request proves connection ownership, the public response is a generic closed denial; internal telemetry records only a bounded tenantless reason metric, with no tenant-scoped Bronze denial row or inbox entry. After successful verification and binding, a later parse, scope, persistence, or normalization failure may retain only tenant-scoped metadata evidence if raw-rights admission for that evidence succeeds. Unknown topic, replay outside the provider window, or an unsupported stream is denied or quarantined with a safe reason. The runtime validates the declared stream; provider-specific topic extraction and mapping stay in the module. Webhook and pull observations for the same object revision must converge on one canonical fact before any tenant cutover. No generic "no secret means trusted" path.

### 5.2 Raw, canonical, and graph boundaries

The existing `RawProviderRecord.idempotency_key` derives from tenant, provider identity, provider record ID, and schema version. That is insufficient as a *revision* identity when an order or campaign changes under the same provider object ID. Define separately:

1. **Source object key:** tenant, provider family, verified source account/realm, object type, provider object ID. Stable across updates and verified reconnects; the mutable connection ID is lineage, not part of object identity.
2. **Acquisition/delivery key:** connection, stream, webhook delivery ID, page record location, or a deterministic poll observation key. Dedupes retry of the same delivery.
3. **Source revision key:** trusted provider version or update timestamp plus canonical payload checksum, with an explicit no-version fallback. Multiple revisions of one object remain replayable.
4. **Canonical logical event key:** source revision + documented semantic slot, independent of event type, mapping version, and normalizer version. A separate interpretation revision key includes those versions and canonical payload digest, so a revised mapping can restate truth without creating a second purchase.

Store these with a uniqueness policy and append-only lineage; do not overwrite the only raw copy when a provider object changes. The branch's raw schema-v2 key enforces source account/realm, object type/ID, and source revision identity and preserves legacy v1 keys. The REST v1 Shopify normalizer retains its historical raw payload in event context only for records admitted under the applicable rights decision; the GraphQL v2 normalizer keeps permitted provider payload in protected raw Bronze and emits a narrower event. The remaining raw-to-logical-fact crosswalk, conflict quarantine, and consistent revision-safe behavior for REST/webhook modes are required before cutover. Preserve raw payload only under an allowed tenant data-rights/retention basis; downstream canonical Bronze is scrubbed by the existing ingress decision. A raw payload that cannot legally persist must be rejected before raw write under the applicable rights decision. Unknown fields, unsupported lifecycle transitions, invalid money/currency precision, mismatched tenant/account, or missing parent references need typed quarantine and readiness effects before any stream is called healthy.

Canonical domain events are facts with evidence, trust class, source authority, occurred/observed time, schema/normalizer version, correlation IDs, and deterministic identity. The schema and alias rules are owned by [canonical contracts](canonical-contracts.md). The domain pack selects source precedence: for example, provider order/payment/refund events can establish commerce and payment truth, while SDK purchase clicks remain observations that may correlate with that truth. Identity resolution happens before a mutation intent; ambiguous identity is deferred or quarantined rather than guessed. A domain reconciliation decision may supersede or retract a previous fact, preserving its lineage and making replay stable.

Only a domain projector builds a `MutationIntent` and calls `shared.graph.mutation_gateway.GraphMutationGateway.apply`. It must supply tenant, provenance/evidence, rights decision reference where applicable, deterministic idempotency, and event/knowledge time. The gateway's current `off/shadow/enforce` mode ladder must be honored; the connector project must not call its `off` mode "governed" merely because the class is invoked. Gateway `shadow` still projects the graph write; a **connector migration shadow** must stop before gateway apply or use an isolated graph. Product views consume registered projection providers and report unavailable/degraded dependencies honestly.

### 5.3 Domain packs and provider expansion

Domain packs are **contract/policy modules**, not new provider runtimes. The first commerce pack extends `shared/commerce_contracts`; other packs are added only when a real vertical slice needs shared rules. One provider module can emit multiple domain events but each stream declares its domain output and source authority. Payment and commerce may share an order/payment correlation key without collapsing billing subscription, checkout, payment capture, refund, chargeback, and observed revenue into one number.

| Pack | Initial entities/events | Authority rule and consumers |
|---|---|---|
| Commerce | Store, product/variant, cart, checkout, order, line item, refund, fulfillment, inventory | Order/store system controls order lifecycle; payment system controls settled funds; SDK behavior provides correlation. Feed Value, Profile, Journey, Snapshot only through projections. |
| Payments | Payment intent/transaction, capture, refund, dispute, payout, fee | Financial provider and existing rail/ledger reconciliation control state; never infer captured revenue from cart/order creation alone. |
| Communications | Message/send/delivery/open/click/bounce/unsubscribe, campaign touch | Provider events and consent/suppression decisions govern status; campaign attribution remains versioned and evidence-based. |
| Advertising/measurement | Campaign/ad, spend, click, conversion, account | Reuse measurement connector stores and attribution authority; platform API is source for spend, SDK is observation for on-site behavior. |
| CRM/support/operations | Customer/account/contact, ticket/case, task/issue, interaction | Provider object IDs are provenance; cross-provider profile identity is resolved by the existing identity service. |
| Analytics/import | Source observation and reviewed mapped records | Retain import mapping/review and SDK trust policy; do not grant an arbitrary CSV row provider authority by default. |

The first certified end-to-end slice should prove one Shopify orders stream with one tenant, one selected account, raw revision retention, canonical event, identity/correlation, authority decision, graph projection, readiness evidence, replay, and a rollback path. The exact Shopify, payment, SDK, graph, and product acceptance sequence belongs to the [commerce reference slice](commerce-reference-slice.md). Subsequent provider ordering depends on actual credentials and fixture coverage, not catalog presence. The cutover modes are in [migration and delivery](migration-and-delivery.md).

### 5.4 Shopify GraphQL migration work package

This branch adds an opt-in `2026-07` GraphQL Admin orders reader, account/GID/realm validation, scope checks, and schema-v2 event revisions while retaining the REST pull compatibility modes. Shopify documents the [REST Admin API as legacy](https://shopify.dev/docs/api/admin-rest/latest) and the [GraphQL Admin API](https://shopify.dev/docs/api/admin-graphql/latest) as the app integration API; its [bulk query mechanism](https://shopify.dev/docs/apps/build/apis/graphql-admin/bulk-operations/queries) is the asynchronous path for large historical exports. The manifest remains unavailable for staging/production, and no development-store run is recorded.

Extend the existing Shopify adapter with GraphQL bulk operations for bounded initial or historical backfill, including durable operation ID, status polling, streamed JSONL ingestion, resume/retry, cancellation, export expiry handling, and reconciliation against incremental/webhook traffic. The runtime scheduler owns generic job/checkpoint behavior; Shopify owns only the provider protocol. Before a tenant switches from REST to GraphQL, compare records, money, lifecycle state, and revisions over an overlapping window; preserve REST rollback while Shopify's current app credentials and permissions are being migrated. Certification must include a real development-store or sandbox round-trip, authorized historical-order access, rate-limit behavior, webhook parity, and version-upgrade fixtures; no fixture-only result is labeled live.

## 6. API and product surfaces

### 6.1 API evolution

Retain existing tenant routes under `/v1/provider-connections` and the public signed webhook route `/v1/provider-webhooks/{identity_key}`; retain legacy `/v1/integrations/connectors` throughout migration. Extend responses additively while clients migrate. Avoid a parallel `/v2/connectors` control plane.

| Surface | Target request/response contract | Authorization and behavior |
|---|---|---|
| `GET /v1/provider-connections/providers` and `/{identity_key}` | Derived manifest with stream IDs, domains, scopes, capability state, availability, certification evidence refs | Tenant can see only connectable capabilities for its environment/plan. Manifest contains field shape, never secret values. |
| `POST /v1/provider-connections`, `/{id}/credentials`, `/{id}/test`, `/{id}/accounts/select` | Existing lifecycle; future capability/stream selection and account-bound scope display | Server tenant from request context; explicit connect permission; credential ref only in records; OAuth state/redirect bound to tenant and connection. |
| `POST /v1/provider-connections/{id}/sync` | Current route accepts optional `stream_ids` (up to 32 unique IDs) and `since`; selection is validated before provider work. Target adds a durable job ID, idempotency key, and bounded time range. | Current endpoint remains synchronous for its bounded pull path. Reject unsupported, inactive, or non-pullable streams; do not mutate an unrelated account. Long backfills move to durable jobs. |
| `GET /v1/provider-connections/{id}/sync-runs`, `/{id}/health` | Per-stream cursor lag, last success, raw/accepted/quarantined counts, error class, remediation, readiness dimensions | Read permission and tenant filter; connection state and readiness are separate fields. |
| New `POST /v1/provider-connections/{id}/replay` + `GET .../replay/{job_id}` | Mode (`raw_normalize`, `provider_backfill`, `projection`, `readiness`), stream IDs, bounded time, dry-run flag, expected output version | Privileged tenant/operator action; audit, quota, concurrency limit, reversible checkpoint, no production graph mutation in comparison mode. |
| New `GET /v1/provider-connections/{id}/quarantine` and safe detail/actions | Counts, reason codes, field names with redacted values, raw reference, retry eligibility | Tenant-safe read; no raw secret/PII leak; retries require role and audit. |
| `GET /v1/integration-catalog`, `/v1/tenant-integrations`, `/v1/tenant/integration-readiness` | Add derived native capability/stream rows and connection evidence to existing read models | Catalog stays a projection of authorities. Legacy rows and native rows must resolve by provider identity/alias without duplicate user cards. |
| `/v1/admin/kyber/provider-connections/*` | Certification, shadow diffs, run/quarantine/replay telemetry, cutover controls | Operator-gated, audited, cross-tenant view only where role allows. No tenant connect/credential submission through Kyber monitoring UI. |

Every added route needs API/schema ownership-map updates, generated docs, frontend shared client types, permission tests, and source-linked doc review. Existing feature flags (`AETHER_PROVIDER_RUNTIME_ENABLED`, `KYBER_PROVIDER_RUNTIME_HEALTH_ENABLED`, `KYBER_PROVIDER_RUNTIME_UI_ENABLED`, migration/decommission flags) remain default-off until evidence supports enablement; any new replay/cutover flag is narrower than the runtime flag.

### 6.2 Aether and Kyber experience

**Aether:** `/settings/integrations` is the connection-management destination. Reuse `apps/aether/src/pages/settings/integrations-section.tsx`, the connectors page/modal, and `@aether-app/features/integrations` rather than build a second integration UI. The provider card explains available streams, scopes, selected account, initial sync progress, last verified data, connected versus ready, and a concrete next action. It must not show "Ready" from credential receipt or raw-row count alone. Account selection, safe bounded backfill, status, and retry are tenant controls behind the correct permission. Existing `/integrations` stays a compatibility route until migration.

**Kyber:** extend the manifest-driven provider-connections feature under `apps/kyber/src/features/provider-connections/` and existing connectors diagnostics. Show installed/certified capability, environment, per-stream lag, quarantine reason distribution, replay/diff/cutover state, and tenant-safe drilldown. Kyber is an internal operator console; it does not become the tenant's connection wizard or a backdoor around tenant consent and authorization.

**Graph and mobile:** existing Aether Lenses/360s, Snapshot, Signals, Journeys, Value, Profiles, Communications, and Risk consume projections and expose provenance/confidence where supported. Mobile is a continuation/inspection surface with explicit desktop handoff for graph exploration or complex connector setup; it does not get a second connection control plane.

## 7. Security, tenancy, rights, and reliability invariants

1. **Tenant and account scope:** derive tenant from authenticated server context; resolve connection ownership before credential, sync, raw, quarantine, replay, or graph access. Include tenant/account/stream in every durable cursor, job, raw, canonical, authority, and graph key. Cross-tenant source IDs are never global dedupe keys.
2. **Credential custody:** use `shared/credentials/service.py` and UPR credential broker refs; no token values in manifest, connection JSONB, event, raw metadata, logs, frontend bundle, or error response. New connections use a tenant/provider reference scoped to the connection ID (the stored reference includes a SHA-256 digest of that ID), so two connections for the same tenant/provider cannot overwrite one another. Existing legacy `provider:{tenant}:{identity}` references remain resolvable and are not rewritten by this change. Rotation revokes stale versions and revalidates scopes; absent/empty credentials fail closed.
3. **Inbound authenticity:** UPR webhook gateway and provider adapter verify signatures over raw bytes with a configured secret. The gateway stores a webhook body only after proof, connection/account binding, and successful raw-rights admission; pre-verification public responses are generic, with internal denials counted by bounded tenantless reason metrics. Post-verification metadata evidence is tenant-scoped only when its own raw-rights admission succeeds; a raw-rights denial creates no retained request body or tenant-scoped raw denial row. Enforce provider replay windows, bounded payload size, rate limit, and known topic/connection binding. Tenant-supplied hosts pass shared SSRF protections, including DNS resolution checks where required for live use.
4. **Purpose, consent, and data rights:** use existing ingress decision and scrubber plus consent registry, rights authority, retention/deletion, and lake/graph policy taxonomy. Provider raw admission resolves `source_id="provider-account:{connection_id}:{account_id}"` and requires a matching tenant-scoped grant (`connector_id` = provider identity, `connector_class="tenant_byod_data"`, explicitly allowed tenant-lake use). Decisions are immutable references, and replay performs a fresh check. `DataRightsService` persists canonical grants and lifecycle events; staging/production also require the migrated schema and available database. Missing permissions, ambiguous active grants, or unavailable storage deny admission. A quarantine label is not an independent retention basis; delete or suppress raw evidence when the governing retention/lifecycle decision requires it. Keep field trust (observed versus inferred versus confirmed) in canonical output.
5. **Graph and outbound controls:** all material graph writes go through `GraphMutationGateway` in an evidence-appropriate mode. Provider data cannot directly authorize an external send, payment, trade, or account mutation. Outbound effects continue through delivery/payment authority, approvals, receipts, and audit.
6. **Failure semantics:** preserve raw input and explicit terminal outcome; use durable outbox for canonical publish/graph request before acknowledging success where the route promises durability. Retrying a delivery, page, normalizer, or projector is idempotent. Poison payloads quarantine; provider 429/5xx use bounded retry and backoff; 401/403 pause the stream for credential remediation. Reconciliation finds missed webhooks and stuck cursors.
7. **Observability:** metric labels must not include raw tenant IDs, provider object IDs, PII, or secrets in high-cardinality telemetry. Logs carry correlation/job IDs, safe provider identity, stream, outcome code; audit retains actor, tenant, action, evidence and before/after state for cutover/replay.

## 8. Build slices and functional acceptance

These are required implementation outcomes, not checks this document claims to have run.

### Slice A — manifest/stream ABI and catalog

- A native plugin can register multiple real streams under capability identities; the registry rejects duplicate stream IDs, manifest/adapter mismatch, undeclared scope, unsupported webhook topic, or unavailable environment claim.
- ABI v1 plugins and `LegacyConnectorPlugin` still register and behave as before. Derived catalog/UI shows one provider family card with accurate capability rows and no duplicate Shopify legacy/native claim.
- A capability with only fixture evidence remains `replay_validated` or `credential_waiting`, never `partner_live` by construction.

### Slice B — acquisition, raw lineage, and quarantine

- Two updates of the same source order produce two durable raw revisions; a repeated webhook delivery produces one delivery receipt and no duplicate canonical fact. Pull and webhook representations of the same revision converge under a tested source-version rule.
- A failed page preserves its old stream cursor. A successful bounded page advances the matching tenant/account/stream cursor only after raw durability and accepted processing state are recorded. Resume after worker restart yields the same result.
- Invalid money, missing required field, unknown topic, or schema drift after ownership is verified yields a typed quarantine/denial outcome and accurate readiness degradation. Retained raw or tenant-scoped metadata evidence still requires successful raw-rights admission; a rights denial stores no provider body or tenant-scoped raw denial record. Bad signatures and other attempts that have not proved tenant/connection ownership yield only tenantless bounded-reason metrics; they do not create tenant-scoped records. No silent `dropped` count is treated as success.

### Slice C — canonical authority and projections

- Fixture matrix proves Shopify order create/update/cancel/refund and payment capture/refund lifecycle, SDK observation correlation, source authority, profile identity, and deterministic graph intents. A created order does not become paid revenue; an SDK click cannot establish payment truth.
- Replaying the same raw range with the same contract/normalizer version yields byte-identical canonical events and graph digest; changing a version records a restatement, alias, and diff rather than double-counting.
- Projections for the selected lighthouse surfaces are sourced from authoritative graph/facts and include tenant-safe provenance. Missing projection binding is reported as unavailable, not silently shown as implemented.

### Slice D — operations and cutover

- Tenant connect, scoped account selection, test, sync, health, bounded replay, quarantine inspection, and disconnect work through authenticated Aether APIs/UI. Tenant A cannot read tenant B's jobs, raw records, aliases, or graph outputs.
- Kyber operator view can inspect certification and shadow comparison and request audited cutover/replay only with operator authorization. Every mode transition has a rollback record and no competing production graph writer.
- Existing legacy connector users keep their events and configuration until their per-capability migration has passed canonical diff, projection diff, readiness truth, and rollback rehearsal. The full migration gates are in [migration and delivery](migration-and-delivery.md).

### Required validation evidence for implementation PRs

Provider contract fixtures cover pagination, cursor durability, webhook signatures/replay, auth errors, scope mismatch, normalizer determinism, duplicate revisions, and schema drift. Integration tests use real PostgreSQL/Redis and the canonical Bronze/outbox/graph paths where relevant; cross-tenant, consent/rights, and RBAC tests are mandatory. A staging provider sandbox and live certification are separate evidence levels. During buildout run focused checks; at finalization use the repository's normal PR `verification / disposition` authority as prescribed by `AGENTS.md`. Neither this blueprint nor a partial test is merge or production readiness proof.

## 9. Decisions that must be explicit before coding each provider

For every new capability/stream, record: identity key; source account namespace; exact source objects and lifecycle events; pull/webhook overlap and revision policy; provider API version/scopes/rate limits; webhook registration and signature method; retention/PII/rights policy; domain pack and canonical schema version; source authority and reconciliation rule; ID/alias rule; graph/projection destination; readiness thresholds; fixtures and sandbox/live certification evidence; cutover and rollback owner. Missing values are blockers to enabling that stream, not invitations to create provider-specific defaults hidden in code.
