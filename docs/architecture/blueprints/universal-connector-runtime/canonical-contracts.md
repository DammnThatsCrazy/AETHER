---
title: Universal Connector Runtime Canonical Contracts
slug: blueprints/universal-connector-runtime/canonical-contracts
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: 0.1.0
canonical_owner: platform@aether
---

# Canonical ID and event contracts

**Status:** Target contract with an in-branch foundation. This branch adds non-identity source-object and alias storage, a pure logical event-key helper, additive raw v2 revision fields, and a Shopify GraphQL v2 mapping. Raw admission resolves the verified account at `source_id="provider-account:{connection_id}:{account_id}"` and requires a tenant-scoped `DataRightsGrant` matching the connection tenant, provider identity as `connector_id`, `connector_class="tenant_byod_data"`, and tenant-lake permission. The `RightsDecision` is an immutable reference; replay verifies that original reference and performs a fresh check against current grant state. The canonical `DataRightsService` now persists grants and create/revoke events through the migration-owned repository. Staging/production admission checks database and schema availability and remains fail-closed if either is unavailable; omitted use permissions default to false. Existing rows from the earlier path remain quarantined because they have no persisted admission evidence or original allowed decision reference; current replay rejects them, and no historical-row re-admission path exists. A future governed path must resolve immutable decision evidence for the unchanged Bronze row and perform a fresh rights check, without manually clearing quarantine or rewriting raw/provenance fields. `BronzeRepository.update` otherwise permits only appending IDs to `payload.metadata.confirmed_signal_ids`. Quarantine is not an audit-retention exception: current rights and retention rules govern whether raw payload is stored, kept, or deleted. The complete authority, reconciliation, graph, and replay contracts below remain target behavior. No tenant cutover or live certification follows from the implemented primitives. Existing identity, rights, event, and graph authorities remain the owners of those decisions.

## 1. Existing authorities and required convergence

| Concern | Current authority | Contract decision |
|---|---|---|
| Provider acquisition and raw lineage | `services/api/shared/integration_contracts/events.py` (`RawProviderRecord`), `services/api/connectors/provider_runtime/raw_store.py` and Bronze `provider_records` | Extend these existing seams for source revisions and replay. Keep raw persistence before normalization. |
| Provider-neutral event | `shared/integration_contracts/events.py` (`AetherEvent`) and deterministic `EventNormalizer` protocol | Extend `AetherEvent` additively. Do not create a competing `CanonicalDomainEvent` transport. |
| Commerce vocabulary and money | `services/api/shared/commerce_contracts/{events,order,money}.py`; [Commerce Event Contract](../../../reference/COMMERCE-EVENT-CONTRACT.md) | Preserve dotted `commerce.*`, `OrderSnapshot`, and exact `Decimal`/JSON decimal-string money. Add lifecycle facts through versioned mapping. |
| SDK capture | `packages/shared/contracts/event-registry.json`, generated `packages/shared/events.ts`, `/v1/batch`, [Ingestion Contract](../../../reference/source-of-truth/INGESTION_CONTRACT.md) | SDK `BaseEvent` and bare SDK commerce signals remain source observations. They cannot emit server-confirmed order, payment, identity, or graph truth. |
| Ingress convergence | `packages/shared/contracts/observation-envelope-registry.json`, `shared/observation/envelope.py`, `packages/shared/observation-envelope.ts`, ingestion gateway | Map verified connector data to Envelope B without treating it as a new SDK event type. Preserve source trust, time, privacy, and raw lineage. |
| Identity | `packages/shared/contracts/identity/*.json`; `services/api/identity/identity/{source_identity_registry,resolver,merge_ledger,redirects}.py` | These owners alone create/resolve canonical person/account/agent identities and their merge/split history. |
| Graph mutation | `services/api/shared/graph/mutation_gateway.py`, graph mutation registry/ledger and rights/consent authorities | Normalizers emit facts; only governed graph writers submit `MutationIntent` to `GraphMutationGateway.apply`. |
| SDK/provider confirmation | `services/api/shared/integration_contracts/commerce_bridge.py`, `services/api/connectors/provider_runtime/confirmation.py`, [SDK Commerce Bridges](../../../reference/SDK-COMMERCE-BRIDGES.md) | Correlate an SDK signal to a Bronze-backed canonical event with a typed verdict. A source hint alone never establishes an order. |

The ChatGPT source blueprint proposed `{type}_v1_{sha256(...).slice(0,12)}` and `apps/api/src/identity/canonical-id-registry.ts`. **This blueprint supersedes both proposals.** A 12-hex-character digest has only 48 bits and is too short for an expanding cross-provider object space. This repository's backend is Python, and its identity registry, merge ledger, and redirect logic already own canonical identity. The connector program must extend them, and must not install a second TypeScript identity authority.

The same source text described an all-new runtime and `apps/api` tree. The current repo already has the Universal Provider Runtime (UPR), raw store, Shopify and other provider plugins, universal observation envelope, and graph gateway. Implementation should extend those paths and use the existing ownership map; paths in that conversation are ideas, not observed repository facts.

## 2. Identifier domains and ownership

`canonical_entity_id` means an **identity resolution result**. `canonical_object_id` below means an opaque, tenant-scoped ID for a provider-owned non-identity object, such as an order or product. They must not be conflated. A Shopify customer is registered as a source identity; its resolved person/account ID comes from the identity service, never from a hash of an email, phone, Shopify customer ID, cookie, or SDK `userId`. A source customer ID may still be retained as a source reference on the order.

| Identifier | Meaning | Issuer and stability |
|---|---|---|
| `tenant_id` | Server-resolved isolation boundary | Existing auth/tenant context; never accepted from an untrusted payload as authority. |
| `provider_identity` | UPR `family.product.capability` identity | Existing provider catalog/manifest. |
| `source_account_key` | Provider's immutable store/account/merchant identity plus live/test realm | Verified server-side at connection; survives OAuth reconnect. A domain/display name is insufficient. |
| `source_object_ref` | `(tenant, provider family, source-account realm/key, object type, native object id)` | Provider source claim; scoped before lookup. |
| `canonical_object_id` | Opaque ID for one source-owned object | UPR object-reference repository prototype; intended to be reused on pull, webhook, replay, and reconnect, but not yet wired to Shopify normalizers, emitted events, or graph projection. |
| `source_identity_id` | One source-scoped person/agent/account/device claim | Existing `SourceIdentityRegistry`. |
| `canonical_entity_id` | Resolved person/agent/account/etc. graph identity | Existing identity resolver and merge/split ledger. |
| `logical_event_id` | Stable ID of one provider fact from a source revision and semantic slot | `LogicalEventKey`; independent of mapping and normalizer versions. |
| `event_id` / `event_revision_id` | Immutable interpretation ID for schema v2; those fields are equal in the v2 `AetherEvent` envelope | `event_revision_id_for_parts`; schema v1 retains its historical event ID and idempotency behavior. |
| `raw.record_id` | Existing UPR raw envelope lineage ID | `RawProviderRecord`; not a provider object ID and not a canonical event ID. |
| `observation_id` | Envelope B observation identity | Existing observation envelope; may refer to an SDK BaseEvent or a connector raw fact. |

### 2.1 Object mapping and collision rule — foundation implemented

The branch adds a tenant-scoped `provider_object_refs` repository inside UPR, backed by a relational table and a unique constraint on the tenant, provider family, live/test realm, verified source-account HMAC, non-identity object type, and native object-ID HMAC. It issues a **server-generated UUIDv4 (122 random bits)** as `canonical_object_id` and reuses the persisted value on retry. It verifies a selected, live-discovered `ProviderAccountRecord` and connection before lookup or write; a mutable domain, display name, or unverified account is insufficient. The raw source tuple is not stored in these mapping tables. PostgreSQL and the identity hash key are required outside local mode. HMAC-key rotation and live database concurrency evidence remain rollout gates. The repository is not called by Shopify REST/GraphQL normalizers, its IDs are not attached to Shopify events, and graph projection does not consume it; it is a repository-only foundation, not current graph identity.

The connection's mutable `integration_id` is lineage, **not part of object identity**. If the same verified provider account reconnects under another integration, reuse the object mapping. A matching display name, URL, email, or unverified account claim is not sufficient to reuse it. Separate live and sandbox provider realms even when native IDs match. Cross-provider references (for example Shopify order to Stripe payment) are evidence-bearing relationships; do not assign the same object ID to both and do not infer equality from coincident numeric IDs.

For identities, call `SourceIdentityRegistry` and the resolver. Its merge survivor redirects continue to resolve old entity links. A split is one-to-many history: it requires an identity decision, versioned graph relationship, and projection restatement; it **must not** become an unconditional old-ID-to-new-ID alias. For non-identity objects, UPR may keep a versioned source/legacy alias table whose unique key includes tenant, namespace, alias type, and alias value. An alias resolves only after account ownership and evidence checks; ambiguity is quarantined, never resolved by picking the first row. Tombstoned IDs are never recycled.

### 2.2 Alias and redirect record — source-object foundation implemented

```text
tenant_id, alias_namespace, alias_kind, alias_value,
canonical_object_id, source_account_key,
valid_from, valid_to?, reason, evidence_ref, decided_by, created_at
```

Allowed reasons: `legacy_migration`, `verified_reconnect`, `source_id_change`, `schema_upgrade`, `operator_correction`. The branch's source-object alias table stores an HMAC of the alias and an evidence ref under the verified tenant/account scope; its unique constraint rejects a conflicting target. There is no global alias lookup. For identity merge/split, use the existing identity records and redirects instead of this table. `canonical_object_id` is a source-object key, not an identity graph key. A migration crosswalk for existing legacy object IDs has not yet been populated.

## 3. Raw revision and logical event identity

Historical schema-v1 `RawProviderRecord.idempotency_key` and Bronze dedup use tenant, `provider_identity`, `provider_record_id`, and envelope `schema_version`; the v1 `AetherEvent.idempotency_key` uses tenant, event type, `source_record_id`, and schema version. This is safe when `provider_record_id` identifies an immutable delivery. It can collapse valid updates if a poll adapter uses a mutable object ID as `provider_record_id`. The branch adds raw schema-v2 source-revision fields and a revision-aware raw key, and adds an `AetherEvent` schema-v2 interpretation ID. These additions preserve v1 key behavior; they do not rehash historical Bronze rows or yet provide a durable logical-event uniqueness/crosswalk table.

### 3.1 Raw acquisition and logical fact revisions

An adapter must report the source-object reference separately from its raw acquisition revision. A normalizer must derive a separate **logical fact revision** from fields that affect the canonical fact. Both classify the unit as a state snapshot or atomic transition:

1. For a current-state snapshot, use a raw `source_revision_key` such as `snapshot:<provider-modified-at-or-none>:<raw-material-digest>`. The raw digest covers the complete provider-shaped payload after removing transport-only noise such as request ID, pagination cursor, webhook delivery ID, and JSON key order. Only raw payload admitted under the applicable rights decision may be stored in protected Bronze; its retention remains subject to that decision and lifecycle policy. A contact-only edit therefore makes a new raw revision when retention is allowed. An identical verified webhook and poll snapshot may reuse the same raw revision only when their complete source state and account scope match. A sparse webhook must be hydrated to a complete state or held pending.
2. Independently derive a logical fact revision from a versioned normalization of **decision-relevant fields**: lifecycle, totals, currency, lines, refund/payment/fulfillment references, deletion state, and stable source links. Contact details, free text, polling time, and the provider's general `updatedAt` do not change an order economic fact by themselves. Two raw revisions may thus map to one logical event ID. A changed total, line, or lifecycle reference produces a different logical fact revision and an explicit correction candidate. Preserve the raw-to-fact mapping and the extractor version; do not discard the second raw receipt merely because its canonical event deduplicates.
3. For a genuinely atomic transition such as a provider refund transaction with its own immutable event/transaction ID, use `event:<provider-logical-event-id>`. Retry deliveries of that event use the same value. The atomic transition uses its own semantic slot and may be linked to the resulting object snapshot; it is **not** published again as the snapshot's lifecycle fact. A webhook delivery ID remains transport evidence and is not necessarily the logical event ID.
4. Persist a tenant/account/object-scoped equivalence crosswalk from a verified provider logical event ID to the resulting snapshot revision when the provider supplies both. The crosswalk requires source version or material-state evidence and is immutable/audited. If equivalence cannot be proven, quarantine the candidate duplicate and suppress its economic/graph effect until reconciliation.
5. When the source supplies neither a logical transition ID nor enough material for a complete snapshot, retain and quarantine the raw delivery only if the provider-account rights decision permits raw retention. If rights are missing or denied, do not persist the request body; record the typed rights outcome and fail closed. Never fabricate a revision from ingestion time.

The branch's additive raw v2 fields carry verified source account and live/test realm, object type and ID, raw `source_revision_key`, and stream. The Bronze key hashes that tuple; the native `provider_record_id` remains separate. The raw store deduplicates retries of one revision while retaining later revisions of the same object, and returns the **already persisted** `record_id` on duplicate ingestion. Historical v1 Bronze keys remain readable; no existing row is rehashed. The graph-safe raw-to-logical-event crosswalk and conflict handling remain to be implemented before cutover.

Raw retention begins only after the provider-account rights check allows it. The `source_id` is `provider-account:{connection_id}:{account_id}`; the matching tenant-scoped grant must identify the provider identity as `connector_id`, use `connector_class="tenant_byod_data"`, and explicitly grant tenant-lake permission. The decision reference is immutable and tenant-scoped. Replay must verify the original reference, then perform a fresh check against current rights before normalization. The canonical `DataRightsService` persists grants and create/revoke lifecycle events through the migration-owned repository; staging/production admission checks database and schema availability and remains fail-closed if either is unavailable. Omitted use permissions default to false. Historical rows created before this admission gate lack persisted rights-admission evidence and an original decision reference, so replay rejects them; there is no historical-row re-admission path. A future governed path must resolve immutable decision evidence for the unchanged row and perform a fresh rights check. `BronzeRepository.update` rejects changes to raw/source/provenance/quarantine fields after insert and only permits appending IDs to `payload.metadata.confirmed_signal_ids`. Quarantine is not an audit-retention exception: preserve raw data only while its rights and retention basis remain valid, and apply deletion/suppression through the lifecycle authority. Provider metadata alone never grants admission or retention.

### 3.2 Exact proposed event uniqueness rule

After raw validation and normalization, define the logical event key as a length-prefixed tuple:

```text
(
  tenant_id,
  provider_family,
  source_account_realm + ":" + source_account_key,
  source_object_type,
  source_object_id,
  logical_fact_revision_key,
  semantic_slot
)
```

`semantic_slot` is a provider-neutral stable slot such as `order.lifecycle`, `order.snapshot`, `payment.settlement`, or `refund.created`. The `LogicalEventKey` helper calls the logical fact revision input `source_revision_key`; it must receive the fact revision, not the raw acquisition key when those differ. The slot is **not** the emitted `event_type`, normalizer version, schema version, integration ID, or acquisition mode. Compute `logical_event_id = "cevt_v1_" + base32lower(SHA-256(encoded_tuple))[0:32]` (160 digest bits); the helper now implements this encoding. Durable full-tuple uniqueness and collision detection are still required before it becomes an issuing authority. The encoded tuple uses NFC-normalized Unicode/UTF-8 and 32-bit length prefixes, never delimiter concatenation. Keep the full 256-bit digest internally for collision diagnosis. The `event_type` can change under a reviewed mapping upgrade while logical event identity stays stable. A new version of interpretation becomes a new **event revision**, not a second purchase or graph fact.

The `source_revision_key` identity extractor is separately versioned and pinned at the first accepted receipt. It must not change just because a normalizer or event mapping changes. If the extractor itself must change, migration supplies a reviewed old-to-new revision-key crosswalk and preserves the old `logical_event_id`; unpaired revisions are quarantined. This protects event identity across schema evolution.

When a normalizer emits two distinct facts for the same raw source revision, it assigns different documented semantic slots. A provider-local event/delta with no stable object ID uses its immutable event ID as the source object ID in a provider-specific `event` object type. Multiple acquisition channels yielding the same source revision and semantic slot resolve to the same logical event. If provider ordering or content is insufficient to decide equivalence, quarantine rather than deduping or double-counting.

The implemented `event_revision_id_for_parts` computes `event_revision_id = "erev_v1_" + lowercase_hex(SHA-256(length_prefixed_NFC_UTF8(logical_event_id, event_schema_version, mapping_version, normalizer_version, canonical_payload_digest)))`; the digest is the full 256 bits. `AetherEvent` schema v2 requires `event_id == event_revision_id` and derives its idempotency key from tenant, event ID, and schema version. Version metadata does not enter `logical_event_id`. A later interpretation keeps the logical ID and creates a new revision ID. The runtime stores each revision as a separate v2 event/outbox identity; a durable logical-fact ledger, supersession decision, v1-to-v2 crosswalk, and governed correction/reprojection remain future work. On replay, unchanged raw bytes plus pinned mapping and normalizer versions must produce the same IDs, JSON-safe payload, and authority outcome. Consumers must not subscribe to multiple interpretations as independent economic facts.

## 4. Canonical event envelope — implemented revision core and target provenance extension

Keep `AetherEvent` as the runtime envelope. Its existing event, provider, lineage, tenant, time, payload, and context fields remain readable. Schema v1 preserves its historical serialized shape. Schema v2 currently requires `logical_event_id`, `event_revision_id`, `mapping_version`, `normalizer_version`, `source_revision_key`, and `canonical_payload_digest`, and requires `event_id == event_revision_id`. The runtime does not yet carry the wider source/subject/governance/lineage block below as typed top-level fields. The implemented core is:

```ts
type AetherEventV2RevisionCore = {
  event_id: string;                 // same immutable value as event_revision_id
  logical_event_id: string;         // stable provider fact identity
  event_revision_id: string;        // erev_v1_ plus full SHA-256 hex digest
  mapping_version: string;
  normalizer_version: string;
  source_revision_key: string;
  canonical_payload_digest: string;
};
```

The wider provenance contract below is the target extension. Do not treat it as the current `AetherEvent` schema or a generated SDK type:

```ts
type AetherEventV2Extension = {
  event_id: string;                 // equals event_revision_id for schema v2
  logical_event_id: string;         // stable logical fact ID, section 3.2
  event_revision_id: string;        // one immutable interpretation
  canonical_payload_digest: string;
  semantic_slot: string;
  mapping_version: string;
  normalizer_version: string;
  source_revision_key: string;
  source: {
    provider_family: string;
    provider_identity: string;
    source_account_key: string;
    source_object_type: string;
    source_object_id: string;
    raw_record_id: string;
    raw_checksum: string;
    acquisition_mode: "poll" | "webhook" | "report" | "stream" | "import" | "reconciliation";
    provider_event_id?: string;
    webhook_delivery_id?: string;
  };
  subject: {
    source_identity_id?: string;
    canonical_entity_id?: string;   // backend resolver output only
    identity_decision_ref?: string;
    resolution_state: "unresolved" | "provisional" | "resolved" | "conflicted" | "suppressed";
  };
  object: { canonical_object_id: string; object_type: string };
  related_objects: Array<{ canonical_object_id: string; relation: string }>;
  time: {
    provider_occurred_at?: string;
    provider_modified_at?: string;
    observed_at: string;
    received_at: string;
    ingested_at: string;
    temporal_quality: "verified" | "source_claim" | "inferred" | "unknown";
  };
  governance: {
    credential_class: string;
    signature_status?: string;
    consent_decision_ref?: string;
    rights_decision_ref?: string;
    authority_decision_ref?: string;
    pii_classification: string;
  };
  correlation?: { correlation_id?: string; causation_id?: string; trace_id?: string };
  lineage: { raw_artifact_ref: string; source_event_ids: string[]; supersedes_event_revision_id?: string };
};
```

The wider TypeScript shape is target-only, **not** a current generated SDK type. When implemented, the server will stamp tenant, credential class, receipt/ingestion time, validation, consent and rights references. The adapter supplies provider-native facts and correlation hints. The resolver alone fills `canonical_entity_id` and identity decision refs. A normalizer cannot mark an SDK checkout as a paid order or attach an unverified identity. Field trust must follow the existing Contract Spine classes: source IDs are `SOURCE_REFERENCE`, SDK identity/correlation inputs are at most `CLIENT_HINT`, server receipt is `SERVER_STAMPED`, identity is `RESOLVED`, and attribution/value projection is `DERIVED`. A verified provider credential establishes origin, not an unlimited data-use grant.

All source times are ISO-8601 with explicit offset when present. Preserve the original source-time claim and recorded receipt separately; do not rewrite a questionable source clock as server truth. `occurred_at` is the interpreted business time; `observed_at`/`received_at`/`ingested_at` support audit and latency. An invalid/ambiguous time degrades or quarantines according to the event's temporal contract. Unknown event type, currency precision, impossible lifecycle transition, mixed-currency order, malformed amount, missing parent reference, or signature failure must produce a typed rejection/quarantine result and readiness effect, never a silently zeroed fact.

Provider-specific payloads admitted by the account's rights decision may be stored in protected raw Bronze, subject to that decision's retention basis and lifecycle policy. `OrderSnapshot` stays small and closed; do not copy the full Shopify payload or customer PII into canonical `data` or a public projection. The REST v1 Shopify normalizer retains its historical `context["raw_provider_payload"]` for compatibility only when the raw payload was admitted for retention. Opt-in GraphQL v2 emits an opaque raw reference and checksum instead. Moving existing REST consumers to that shape requires inventory and compatibility tests before v1 removal. Public responses must expose only safe canonical fields and opaque lineage refs.

## 5. Source authority and reconciliation

`services/api/identity/identity/source_precedence.py` already contains a fail-closed precedence matrix and `resolve_conflict` for identity and broad `revenue`/`conversion` classes. It does **not** yet express all provider-specific commerce facts and lifecycle rules below. Extend the existing source-resolution decision pattern with versioned, field-level policies; do not treat one scalar trust rank or `provider=shopify` as blanket authority. Identity decisions remain in the identity resolver; outcome/attribution decisions remain with their existing measurement owners. A connector cannot grant itself graph or data-use authority.

| Fact | Eligible primary source | Ineligible inference / fallback rule |
|---|---|
| Store, catalog, cart, order creation/cancellation, fulfillment | Verified store provider for that provider account (Shopify, WooCommerce, Amazon Seller, Square commerce, etc.) | SDK and ad click events are observations only. CSV may fill missing facts with explicit `tenant_import` provenance, not overwrite verified store truth. |
| Payment authorization, capture, settlement, payout, fee, dispute | Verified payment/processor provider for its own transaction/account | Store `financial_status` can describe store-reported status but cannot assert processor settlement, payout, or fee. An SDK payment-intent observation has no settlement authority. |
| Refund | Provider responsible for the refund event and its payment/order linkage; reconcile store and processor views | A cancelled order is not automatically a refund. An order snapshot's refunded status is not enough to invent a refund ID or amount. |
| Campaign delivery/spend | Verified ad or messaging provider for its campaign/account | UTM and SDK touchpoints are source references or observations, never spend authority. |
| Behavior/session/journey hint | SDK or permitted first-party server observation | May correlate to order via verified server-side references; does not establish a purchase or canonical identity. |
| Attribution credit, net value, graph relationship | Aether measurement/graph authority from accepted underlying facts | Provider and SDK fields cannot write derived truth directly. |

Decision inputs must include `tenant_id`, object ID, field path, candidate value and currency if monetary, provider/account, credential/signature status, source revision, effective time, raw/event evidence refs, consent/rights refs, and policy version. The decision output is an append-only `AuthorityDecision` with `accepted`, `rejected`, `deferred`, or `conflicted`; winning event revision, losing candidate refs, reason code, decision time, policy version, and reviewer override ref where applicable. A verified connection is necessary, but availability of a more authoritative source does not imply its data is correct: two same-authority disagreeing revisions with no valid ordering cause a conflict. Unknown field or missing evidence fails closed, following existing precedence behavior.

`CommerceReconciliationRecord` is proposed as a **decision/evidence record**, not a second order or payment store. It keys on tenant, canonical object, fact family, and source revision set; records comparison of store/processor facts, completeness, mismatch type, money delta, currency, effective times, authority decision refs, and disposition. Accepted monetary corrections supersede the previous fact version and reproject Value/attribution. Gross order total, captured payment, refunded amount, processor fee, payout, and net value remain distinct fields/objects. Never sum a Shopify order and Stripe charge as two sales. Never subtract the same refund twice when store and processor both report it. A partial refund requires an explicit refund ID/amount, linked to the original payment/order, with an accepted authority decision.

Use existing `Money` (`Decimal`, currency string) and `OrderSnapshot` as the v1 commerce payload. JSON amounts must be decimal **strings**; floats are rejected at canonical boundaries. Validate a currency code and its minor-unit/precision rules through a versioned currency authority, with explicit behavior for zero- and three-decimal currencies. The current `money_from_cents`/`to_cents` helpers assume two decimal places; they cannot be applied to every currency without a reviewed contract change. Mixed-currency totals are rejected by existing commerce models. A refund/credit may legitimately be negative in `Money`, but the event kind and sign convention must be fixed per canonical payload version so a consumer never guesses whether to subtract it.

## 6. Lifecycle versioning, ordering, and tombstones

The current Shopify normalizer maps `cancelled_at` first, then `created_at == updated_at`, then `financial_status == refunded`, and otherwise `updated`. Its `OrderStatus` can express `paid`, `fulfilled`, and `partially_refunded`, while that normalizer currently folds these states into `commerce.order.updated`. The v2 contract must **not** relabel old v1 events in place. Add a versioned Shopify mapping table and golden fixtures before switching any producer:

| Source fact / condition | Current v1 emission | Proposed v2 emission and guard |
|---|---|---|
| Order first observed | `commerce.order.created` when timestamps match | `commerce.order.created` for verified new order; repeated snapshots become revisions, not new orders. |
| Nonterminal order change | `commerce.order.updated` | `commerce.order.updated`, with versioned field diff. |
| Store reports paid | Usually `commerce.order.updated` | `commerce.order.paid` **only as store-reported payment state** with source evidence. Processor `payment.captured`/`payment.settled` remains separate. |
| Fulfillment advances | Usually `commerce.order.updated` | Add a reviewed `commerce.order.fulfilled` type or retain `updated` plus a typed fulfillment fact until taxonomy is expanded. Do not emit a type absent from the curated registry. |
| Partial refund | Usually `commerce.order.updated` | Add `commerce.order.partially_refunded` only after a refund contract and taxonomy migration; emit linked refund fact with exact amount. |
| Full refund | `commerce.order.refunded`, subject to current rule ordering | `commerce.order.refunded` only with explicit refunded-state evidence and linked refund facts where available. Cancellation and refund are separate transitions. |
| Cancellation | `commerce.order.cancelled`, currently wins when `cancelled_at` is set | `commerce.order.cancelled` remains a store state; do not erase subsequent refund evidence. |

Version the **mapping**, event taxonomy, normalizer, and payload independently. During migration, persist both v1 and v2 interpretations with a stable logical ID and distinct v2 interpretation ID; today the bridge can persist v2 rows by revision-aware `event_id`, but does not record a durable active-revision pointer or cross-version migration map. Historical v1 output remains readable. A v2 switch requires consumer compatibility for the new types and a backfill diff, then an atomic primary-version flip. Event name is never inferred from an SDK signal. The currently curated commerce type set in `shared/commerce_contracts/events.py` must be updated together with any new emitted types; `packages/shared/contracts/event-registry.json` remains the SDK registry until a separate, reviewed convergence change.

For mutable object state, order accepted revisions by provider sequence/version when available, then provider-modified time **only if the provider documents it as monotonic for that object**. Receipt time is a tie breaker for observability, not authority for business state. Keep a per-object high-water mark and complete revision history. A late older revision is stored but cannot roll the active state backward. Same revision key with different material content is `revision_conflict` and quarantined. Equal-time, different-content revisions without a provider sequence require reconciliation rather than last-write-wins. Missing intermediate revisions or parent objects are pending/repairable; no graph mutation until required lineage is complete.

Only explicit provider deletion/cancellation/revocation facts can tombstone an object. Absence from a partial page or interrupted sync is not deletion. A completed, scoped full inventory may propose a tombstone only after provider-specific deletion semantics and a reconciliation grace window are certified. A tombstone retains source ID, canonical ID, evidence, effective/recorded time, and rights/retention policy; it does not recycle an ID. A later verified restoration is a new version linked to the tombstone, not a fresh canonical object. Identity erasure and consent revocation follow their own existing authorities and may suppress projections even while an audit-safe source tombstone remains.

## 7. Governed graph mutation and projection

The normalizer returns provider-neutral `AetherEvent` facts and a visible dropped/quarantine result. It never writes graph state. The graph projector resolves source-object IDs and identity separately, requests current consent and rights decisions, obtains a source-authority decision, and constructs a `MutationIntent` with `tenant_id`, `source_event_id`, `idempotency_key`, `actor_kind=provider` or `service`, `evidence_refs`, reason/policy/consent refs, `rights_decision_ref`, valid time, and change-set linkage. `GraphMutationGateway.apply` remains the choke point and append-only mutation ledger vocabulary remains canonical. A correction must version or expire the prior fact/edge, not add a second purchase/value edge. Derived attribution and Value computations have their own model/policy refs and do not inherit provider authority by proximity.

The proposed mutation idempotency key is a length-prefixed hash of `(tenant_id, logical_event_id, event_revision_id, operation, target_aggregate_id)`. A replay of the same interpretation is deduplicated; a reviewed new interpretation creates a distinct correction mutation and supersedes the prior active version. Projectors must use a stable aggregate ID and compare desired state before writing. If the graph gateway is in `off` or `shadow`, that mode's actual code behavior must be considered: **gateway `shadow` still calls the graph projector** and only shadows validation/ledger enforcement. Connector migration `shadow` must stop before `GraphMutationGateway.apply` or use a physically isolated comparison graph/store. Production cutover requires the intended governed enforcement behavior to be evidenced, never inferred from the word “shadow.”

Projection consumers (Profile, Campaign, Communications, Value, Signals, Journeys, Snapshot, Risk) read authorized graph/measurement projections, not provider adapter tables. A raw provider event can enter Bronze only after raw rights admission; after that, identity resolution may remain pending, event-level consent may deny canonical output, or graph projection may be pending. These are distinct states. Readiness must report them separately. Replay/reprojection carries a run ID, pinned contract/mapping/policy versions, tenant and source scope, actor/RBAC/audit record, referenced immutable `RightsDecision`, fresh rights-check result, dry-run diff, checkpoint, and rollback/suppression plan. Replay does not re-call the provider unless it is a separately authorized backfill.

## 8. SDK correlation and privacy contract

The four shipped bridge pairs remain the scoped mapping in [SDK Commerce Bridges](../../../reference/SDK-COMMERCE-BRIDGES.md). In particular, `commerce.order.created` is **not** `order_confirmed`. Client `product_view`, `cart_updated`, `checkout_started`, and `order_confirmed` are bare SDK signal names, while dotted `commerce.*` is the server runtime vocabulary. A bridge projection alone returns `confirmed=false`; only server confirmation against a Bronze-backed canonical event can return `matched`. A missing/mismatched lineage returns `not_found` or `unconfirmed`, and a repeat signal is `replay`.

Proposed correlation fields are source-observable `checkout_ref`, `cart_ref`, `session_ref`, `correlation_id`, and provider order reference when the source actually knows it. The client may submit a hint, but the server must verify tenant, provider account, canonical source object, raw lineage, consent, and uniqueness before making a graph relationship. A single session can contain multiple carts/orders, and shared devices/users do not imply a merge. Explicit nested correlation fields take precedence over legacy flat fields by **presence**, including explicit null/empty values; a fallback based on truthiness would resurrect a value the caller cleared. Identity confidence and signals from the client remain non-authoritative.

SDK `/v1/batch` continues to accept `BaseEvent` and dedupe by tenant, client event ID, and SDK schema version. The ingress gateway builds Envelope B server-side and applies credential, tenant, signature where relevant, consent, privacy, sensitive-field scrubbing, and source-trust gates before Bronze. Connector events also map to Envelope B; they do not pass through SDK `/v1/batch` or claim `sdkEmitable` status. Server consent receipts and data-rights grants are authoritative; client consent snapshots are evidence. PII such as email/phone remains in protected identity claims or raw stores under the existing classification/retention rules, never in a canonical ID, dedup key, public event, log line, or analytics URL. For provider raw ingress, an evaluated denial produces a typed `RightsDecision` where the rights authority is available, and no denied provider body is retained; an unavailable or non-durable grant authority also fails closed before raw persistence. Later consent or projection denials produce the existing typed decision/quarantine outcome and no graph write.

## 9. Illustrative contract payloads

The first example combines the implemented `AetherEvent` v2 revision core with target-only wider provenance fields; it is not the current wire shape emitted by the Shopify plugin. GraphQL Shopify emits the v2 revision core, while REST v1 retains its legacy shape. IDs and checksums are illustrative; conformance fixtures must derive and assert their exact values from the canonical encoders.

### 9.1 Shopify order state from a verified provider account

```json
{
  "event_id": "erev_v1_0000000000000000000000000000000000000000000000000000000000000000",
  "logical_event_id": "cevt_v1_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "event_revision_id": "erev_v1_0000000000000000000000000000000000000000000000000000000000000000",
  "canonical_payload_digest": "0000000000000000000000000000000000000000000000000000000000000000",
  "event_type": "commerce.order.paid",
  "event_family": "commerce",
  "semantic_slot": "order.lifecycle",
  "mapping_version": "shopify-order-v2",
  "normalizer_version": "2",
  "schema_version": "2",
  "tenant_id": "tenant-a",
  "provider": "shopify",
  "provider_identity": "shopify.admin.orders_read",
  "source_record_id": "raw-record-uuid",
  "occurred_at": "2026-10-02T14:02:03Z",
  "observed_at": "2026-10-02T14:02:06Z",
  "account_id": "store-account-1",
  "data": {
    "order_id": "4839201",
    "status": "paid",
    "currency": "USD",
    "total": { "amount": "119.95", "currency": "USD" },
    "created_at": "2026-10-01T21:00:00Z",
    "updated_at": "2026-10-02T14:02:03Z",
    "account_id": "store-account-1"
  },
  "context": { "legacy_event_type": "shopify.orders.updated" },
  "source_revision_key": "snapshot:2026-10-02T14:02:03Z:sha256-of-material-state",
  "source": {
    "provider_family": "shopify",
    "provider_identity": "shopify.admin.orders_read",
    "source_account_key": "shopify:live:verified-store-id",
    "source_object_type": "order",
    "source_object_id": "4839201",
    "raw_record_id": "raw-record-uuid",
    "raw_checksum": "sha256-of-raw-payload",
    "acquisition_mode": "webhook",
    "webhook_delivery_id": "delivery-701"
  },
  "subject": { "resolution_state": "unresolved" },
  "object": { "canonical_object_id": "36da9b5e-6860-4e9f-9688-82e26c6d8fe1", "object_type": "order" },
  "related_objects": [],
  "time": {
    "provider_occurred_at": "2026-10-02T14:02:03Z",
    "provider_modified_at": "2026-10-02T14:02:03Z",
    "observed_at": "2026-10-02T14:02:06Z",
    "received_at": "2026-10-02T14:02:07Z",
    "ingested_at": "2026-10-02T14:02:08Z",
    "temporal_quality": "source_claim"
  },
  "governance": {
    "credential_class": "VERIFIED_WEBHOOK",
    "signature_status": "verified",
    "rights_decision_ref": "rdec_example",
    "authority_decision_ref": "authz_example",
    "pii_classification": "none"
  },
  "lineage": { "raw_artifact_ref": "provider_records/raw-record-uuid", "source_event_ids": [] }
}
```

`commerce.order.paid` here means the store **reported** a paid state. It does not establish capture, settlement, payout, net value, or identity. Those require their own eligible sources and decisions. In a real fixture, the digest-shaped fields above must have correct computed encodings and the `rights_decision_ref` must point to an actual allowed decision for the requested use.

### 9.2 SDK checkout observation and correlation verdict

```json
{
  "sdk_signal": {
    "signal_id": "sdk-event-809",
    "signal_type": "checkout_started",
    "occurred_at": "2026-10-02T13:55:00Z",
    "source_url": "https://shop.example/checkout",
    "lineage": { "source_record_id": null },
    "payload": { "checkout_ref": "checkout-42", "session_ref": "session-9" }
  },
  "server_result": {
    "confirmed": false,
    "confirmation_state": "not_found",
    "canonical_event_type": "",
    "provider": ""
  }
}
```

An accepted SDK signal has behavioral meaning even with `not_found`; it cannot add an order or payment edge. If a later server-verified provider fact supplies matching lineage, a reviewed correlation pass may record `matched` and link the observation to that order. Replaying the signal produces `replay`, not another conversion. The example's `checkout_ref` is only a client hint until the server verifies it against the provider account.

### 9.3 Authority disagreement

```json
{
  "tenant_id": "tenant-a",
  "canonical_object_id": "36da9b5e-6860-4e9f-9688-82e26c6d8fe1",
  "field_path": "payment.settled_amount",
  "policy_version": "commerce-authority-v1",
  "candidates": [
    { "provider": "shopify", "amount": "119.95", "currency": "USD", "claim": "store_financial_status", "event_revision_ref": "shop-rev" },
    { "provider": "stripe", "amount": "109.95", "currency": "USD", "claim": "processor_settlement", "event_revision_ref": "stripe-rev" }
  ],
  "decision": {
    "status": "conflicted",
    "reason_code": "settlement_mismatch",
    "winning_event_revision_ref": null,
    "graph_write_allowed": false
  }
}
```

The policy may later accept the processor settlement with explicit evidence and represent the store status separately, but it must not manufacture a reconciled net amount from the mismatch or present the order as twice paid.

## 10. Versioned artifacts and implementation ownership

The implementation should add contract artifacts at the **existing** owner seams, not a new `apps/api` runtime:

| Artifact to implement | Owner / relationship |
|---|---|
| `packages/shared/contracts/provider-runtime-event-registry.json` | Proposed single source for runtime dotted event taxonomy, semantic slots, required evidence, and event/mapping versions. It is separate from the current SDK-only `event-registry.json`. During adoption, generate a Python taxonomy imported/re-exported by `shared/commerce_contracts/events.py`; remove its independent hand-written list so there is one runtime type authority. Generate a passive TypeScript reader only for server/admin use, not a public SDK emitter. |
| `services/api/shared/integration_contracts/events.py` | Implemented additive raw revision fields and `AetherEvent` schema-v2 interpretation fields with v1 serialization compatibility. The wider source/subject/governance envelope, durable logical-fact ledger, and supersession/cross-version mapping remain target work. |
| `services/api/shared/integration_contracts/normalization.py` | Require pinned `normalizer_version`, source revision, semantic slot, deterministic IDs, and explicit drop/quarantine reasons. |
| `services/api/shared/commerce_contracts/{order,money,events}.py` | Preserve existing payloads and exact money; add payment/refund/fulfillment payloads under the same commerce package only when authoritative provider fixtures define them. |
| `services/api/connectors/provider_runtime/{raw_store,object_refs}.py` | Preserve raw revisions and persist non-identity object mapping/aliases inside UPR. The source-object foundation is implemented, while the raw-to-fact crosswalk and graph integration remain target work; no new identity registry. |
| `services/api/identity/identity/*` | Reuse source identities, decisions, merge/split ledger, redirects, and projection restatement. Add only integration tests or the minimum typed link needed by UPR. |
| `services/api/shared/graph/mutation_gateway.py` and graph projectors | Continue to own graph mutation. Add source/authority/rights evidence and correction semantics through `MutationIntent`, not direct adapter writes. |
| `services/api/connectors/providers/shopify/normalizer.py` | Versioned v1/v2 lifecycle mapping and golden fixtures; source revision extraction distinct from event interpretation. |
| `packages/contracts/provider-runtime/*.schema.json` | Proposed **generated** machine-readable JSON Schemas for v2 `AetherEvent`, source-object ref, authority decision, and reconciliation record. Generate from the enforcing Python models or the chosen canonical registry; do not hand-maintain a conflicting definition. |

Add generator and parity work to `scripts/generate_platform_contracts.py` or the existing `scripts/generate_contracts.py` ownership path, and register the new source/output surfaces in `docs/reference/source-of-truth/repo_consistency_ownership.json`. Generated TypeScript/Python/docs remain generated. Source-linked docs, especially [Commerce Event Contract](../../../reference/COMMERCE-EVENT-CONTRACT.md), [SDK Commerce Bridges](../../../reference/SDK-COMMERCE-BRIDGES.md), [Ingestion Contract](../../../reference/source-of-truth/INGESTION_CONTRACT.md), and the UPR/Provider Migration pages, must be reviewed against their declared `source_files` before scoped source-hash refresh. The present blueprint edit changes none of those runtime or generated artifacts.

## 11. Migration and backward compatibility sequence

1. **Inventory and freeze v1.** Record current raw keys, `AetherEvent` types/keys, `OrderSnapshot` consumers, identity IDs, graph writes, rights/consent path, and all Shopify lifecycle fixtures. Pin source and mapping versions. Keep legacy event types readable.
2. **Add object/ref and revision indexes.** Create durable tenant-scoped mappings without changing existing public IDs. Backfill verified source tuples and legacy aliases. Reject ambiguous reconnections and collisions. Existing raw rows keep their original dedup keys and receive a crosswalk to logical source revisions.
3. **Additive v2 write in an isolated shadow store.** Emit v1 primary plus v2 comparison output from the same still-authorized raw artifacts. Connector shadow cannot touch the production graph. Compare counts, source revisions, IDs, order lifecycle, exact money, identity links, authority decisions, graph intents, and projections. Record every mismatch and quarantine.
4. **Governed per-tenant/provider cutover.** Require fixture parity, no unexplained missing refunds/payments, no duplicate economic facts or graph mutations, rights/consent parity, acceptable quarantine and freshness, and a reversible tenant/provider/account flag. Flip one primary interpretation; old v1 remains readable as history/fallback for a bounded window.
5. **Reproject and retire.** Rebuild only affected graph/Value/attribution projections from pinned event revisions, compare digests and totals, retain aliases, then retire old writers after evidence. Never delete raw artifacts solely to make counts agree; apply governing rights, retention, deletion, and suppression decisions. Rollback restores the v1 primary flag and prior projection snapshot; v2 facts remain audit history but cannot write active graph state.

These steps are a contract dependency for the sibling cutover plan. The proposed `dual_write` state must not mean two graph authorities: both interpretations may be persisted for comparison, but exactly one can own active economic and graph mutations for a given tenant/source scope.

## 12. Contract test vectors and acceptance gates

| Vector | Input / invariant | Expected result |
|---|---|
| T01 tenant isolation | Same Shopify store/order IDs under two tenants | Distinct object/event IDs; no cross-tenant alias or graph edge. |
| T02 reconnect | Verified same store reinstalled under new `integration_id` | Same canonical object ID and event identity; new connection lineage only. |
| T03 account collision | Same numeric order ID under two stores or live/test realms | Distinct objects/events. |
| T04 mutable snapshot | Same order ID, changed paid/refunded material state | New raw revision and event revision; existing object ID; no lost update. |
| T05 webhook retry | Same logical provider event, new delivery attempt | One raw logical revision, one event, one active mutation; delivery attempts retained as transport evidence. |
| T06 webhook/poll convergence | Full webhook and poll carry the same order state but different delivery IDs | Same `snapshot:*` revision, logical lifecycle fact, and authority outcome; both acquisition refs retained. A distinct refund transition remains linked, not merged into the snapshot event. |
| T07 sparse webhook | Missing fields needed for a complete order state | Pending hydration/quarantine; cannot supersede a complete state. |
| T08 replay | Same raw bytes, pinned mapping and normalizer | Byte-identical canonical payload/IDs and no extra graph/value increment. |
| T09 mapping upgrade | Old `updated` becomes v2 `paid` with same source revision/slot | Same `logical_event_id`, new `event_revision_id` (which becomes v2 `event_id`); explicit correction and no second sale. |
| T10 late/out-of-order | Older provider revision arrives after newer | Both retained, active state unchanged, ordering evidence recorded. |
| T11 equal-time conflict | Same object/time, conflicting money and no sequence | Conflict/quarantine; no last-write-wins. |
| T12 tombstone/restoration | Explicit delete then verified restoration | Same object ID, versioned tombstone and restore; no ID reuse. |
| T13 identity ambiguity | Shared email/device or split profile | No automatic merge or one-to-many alias; identity review/restatement path. |
| T14 SDK false positive | `order_confirmed` hint or `commerce.order.created` alone | No paid/settled order authority; confirmation requires Bronze-backed eligible event. |
| T15 financial collision | Store total, processor capture, partial refund, fee, payout | Distinct typed facts, exact decimal strings, one accepted net-value derivation; no double count. |
| T16 rights/consent | Missing, denied, revoked, or cross-tenant grant | Typed denial and no graph/projected write; raw retention follows policy. |
| T17 schema/PII drift | Unknown currency precision, float money, full customer payload in public event | Typed rejection/quarantine or protected raw-only preservation; no silent default. |
| T18 digest collision | Forced generated-ID or event-digest collision | Transaction rejects/retries or quarantines and alerts; never aliases two source tuples. |

Implement golden provider fixtures with raw input, expected Envelope B, `AetherEvent`, authority decision, graph intent, and projection/readiness effects. Add parity tests for generated runtime vocabulary and Python/TypeScript/JSON Schema shapes, plus migration tests against stored v1 events. Focused tests during development include `tests/contracts/test_observation_envelope_parity.py`, `services/api/tests/integration_contracts/test_events.py`, `services/api/tests/commerce_contracts/`, `services/api/tests/providers/test_shopify_plugin.py`, identity replay/merge/split tests, graph gateway idempotency/consent tests, and SDK bridge/confirmation tests. The chief agent's finalization workflow owns generator/idempotency checks and the single normal PR verification disposition; no focused suite alone proves merge or production readiness.
