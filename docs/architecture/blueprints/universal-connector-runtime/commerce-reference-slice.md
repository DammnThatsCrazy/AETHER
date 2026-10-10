---
title: Commerce Reference Slice for the Universal Connector Runtime
slug: blueprints/universal-connector-runtime/commerce-reference-slice
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: experimental
since_version: "0.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 20
toc_depth: 3
---

# Commerce reference slice

This is the first target vertical slice of the [Universal Connector Runtime blueprint](README.md). It describes the customer loop and repository work needed to prove it. The branch implements an opt-in Shopify GraphQL orders reader, raw revision fields, and canonical transport foundations; it has not completed payment/SDK reconciliation, graph projection, tenant cutover, or live certification. `provider_object_refs` is repository-only and is not wired into Shopify events or graph projection. All remaining targets below require their stated evidence.

## What exists and what must change

| Surface | Current repository evidence | Required extension |
|---|---|---|
| Shopify plugin | `services/backend/services/providers/shopify/plugin.py` declares `shopify.admin.orders_read`, mode-specific auth/account/pull/webhook behavior, and no reconciliation adapter. Environment availability is empty and readiness is `credential_waiting`. | Keep capability-level plugin identity; certify each stream and add reconciliation through shared runtime/domain authority. Do not label the current plugin tenant self-service or production ready. |
| Shopify pull | `services/backend/services/providers/shopify/pull.py` retains REST `orders.json` as the default compatibility path. `orders_api=graphql` opts into a paginated Admin GraphQL adapter pinned to `2026-07`; GraphQL bulk export is not implemented. | Prove the GraphQL path in Shopify sandbox, including scope, rolling history window, rate limits, and replay; then decide whether to change the default. Build bulk export for large historical backfills. Keep REST compatibility bounded and do not cut over until its raw-revision limitations are resolved. |
| Shopify normalization | `services/backend/services/providers/shopify/normalizer.py` preserves the REST v1 event shape; GraphQL v2 emits a versioned snapshot revision with a stable logical ID and an immutable interpretation ID. Order lifecycle remains separate from processor settlement; paid, fulfilled, and partial refunds are not yet distinct domain facts. | Version lifecycle mapping before expanding event types. Preserve legacy results for existing consumers until they accept the new contract. Emit explicit payment/refund/fulfillment facts only from corresponding source evidence. |
| Commerce contract | `services/backend/shared/commerce_contracts/` owns `Money`, `CommerceOrder`, `OrderSnapshot`, and dotted `commerce.*` vocabulary. | Extend these exact contracts for revisions, exact adjustments, authority, and evidence links. Generate shared twins only through the repository's contract generator where that contract has a generated owner. |
| SDK bridge | `packages/web/src/modules/commerce-detection.ts`, `packages/web/src/bridges/`, and `services/backend/shared/integration_contracts/commerce_bridge.py` distinguish observed SDK signals from canonical commerce events. | Correlate SDK checkout/session observation to a provider order only with valid server lineage; an observation cannot confirm a paid order by itself. Preserve the existing bare SDK event versus dotted runtime event boundary until versioned convergence is reviewed. |
| Legacy connector | `services/backend/services/integrations/connectors/adapters.py` still contains a Shopify connector; UPR wraps legacy connectors. | Shadow and compare the native stream, migrate each tenant connection through durable routing, then retire the legacy path only after rollback and decommission gates. |

Shopify states that the REST Admin API is legacy and directs new integrations to GraphQL. Its [versioning guidance](https://shopify.dev/docs/api/usage/versioning) requires a supported pinned version and provides an API version response header; [GraphQL bulk operations](https://shopify.dev/docs/apps/build/apis/graphql-admin/bulk-operations/queries) support large backfills. The opt-in implementation pins `2026-07`; maintainers must verify Shopify's supported-version window before upgrades and confirm scopes, query shapes, cost limits, and response version headers. The pinned version is an implementation fact, not a permanent target.

**Current raw-admission gate:** provider raw admission resolves `source_id="provider-account:{connection_id}:{account_id}"` and requires a tenant-scoped `DataRightsGrant` matching the verified connection tenant, provider identity as `connector_id`, `connector_class="tenant_byod_data"`, and explicit tenant-lake permission. The canonical `DataRightsService` persists grants and lifecycle events through the migration-owned repository. Staging/production admission checks database and schema availability and remains fail-closed if either is unavailable; omitted use permissions default to false. The decision is immutable and replay verifies its reference and performs a fresh rights check. Existing quarantined rows from the earlier path lack persisted admission evidence and an original allowed decision reference, so current replay rejects them and no historical-row re-admission path exists. A future path must resolve immutable decision evidence for each unchanged raw row and perform a fresh current-rights check. New raw payloads are retained only after rights admission, and all raw retention remains subject to deletion/suppression policy. The runtime is default-off. The customer loop below is the target after the admission/replay gates are proven, not a currently runnable end-to-end path.

## Target customer value loop

1. In AETHER, a tenant chooses Shopify, sees the specific scopes and data uses, authorizes the store, selects the store/account, and sees a truthful connection state. The credential broker retains secrets; the UI receives references and status only.
2. The runtime records a durable initial backfill job, fetches the selected streams, verifies provider responses, stores permitted source evidence, normalizes with a pinned mapping version, and advances each stream checkpoint only after required persistence succeeds.
3. Signed webhooks bring later changes into the same source-object and revision lineage. Duplicate deliveries are idempotent; changed objects are new revisions; an unknown schema goes to quarantine with a visible repair path. Shopify requires HMAC verification over the [raw request body and duplicate-delivery handling](https://shopify.dev/docs/apps/build/webhooks/verify-deliveries).
4. Source authority decides whether each order, payment, refund, fulfillment, and customer record establishes truth, adds evidence, corrects a prior fact, or requires review. SDK product/cart/checkout observations remain first-party behavior evidence.
5. Approved intents pass through the existing graph mutation gateway. Projections expose source-backed order and net-value context in AETHER Snapshot, Value, Profiles, Journeys, and relevant lenses, with explicit freshness and limitation states. Kyber holds internal sync, replay, quarantine, certification, and cutover controls.

The minimal commercially useful first slice is one connected store, one complete order lifecycle including a refund or cancellation, safe SDK correlation, and a trusted net-value read model. The full Shopify pack then expands the streams below without changing the generic runtime.

## Stream and capability backlog

Each row is a proposed stream descriptor under the Shopify provider family, with its own cursor/watermark, schema version, account scope, checkpoint, retries, and certification fixtures. A stream may be withheld if approved API scopes or customer data rights are absent.

| Priority | Stream | Canonical output and authority | Required proof |
|---|---|---|---|
| P0 | Orders and line items | Order state, exact order totals, line-item identity; Shopify order is primary for order existence and order-side totals. | Initial/incremental pull, changed revision, cancellation, late update, duplicate webhook. |
| P0 | Refunds and order adjustments | Distinct refund IDs and signed value adjustments; never infer a full refund from an order update alone. | Partial, multiple, full, reversal, out-of-order, cross-currency rejection or explicit conversion policy. |
| P0 | Transactions/payment references | Provider transaction evidence and stable references to independent processors. | Paid/unpaid transition; do not count both order total and processor charge as separate sales. |
| P1 | Customers | Source customer identity evidence, scoped PII handling, consent and deletion effects. | Reconnect alias, ambiguous identity, cross-tenant block, redaction/erasure. |
| P1 | Products, variants, collections | Product catalog facts with stable source object IDs and tombstones. | Variant moves, deleted product, missing versus zero inventory/price. |
| P1 | Fulfillments and shipments | Fulfillment state and shipment references, not payment truth. | Partial fulfillment, cancellation, webhook/pull parity. |
| P2 | Inventory and locations | Time-stamped inventory observations per location; never overwrite order history. | Late stock update, multiple locations, unavailable source. |
| Conditional | Checkout/cart or marketing objects | Provider facts only where supported and authorized; SDK remains an observation source. | Scope/capability proof and explicit source-authority rules before enabling. |

Provider-specific schedules and API contracts belong in `services/backend/services/providers/shopify/`; generic stream execution belongs in `provider_runtime`. Webhook topic names, scope grants, and retention rules must be enumerated in the actual manifest and reviewed against current Shopify documentation during implementation.

## Cross-source authority and value rules

| Evidence | May establish | May not establish by itself |
|---|---|---|
| Shopify order | Order existence, items, store-facing order state and totals. | Independent processor settlement or campaign causality. |
| Shopify refund record | A specific order-side refund or adjustment. | A processor payout reversal absent processor evidence. |
| Connected merchant processor event | Payment attempt, capture, refund, fee, payout or settlement for that processor account. | A second sale when it matches an existing order; another tenant's payment. |
| SDK web/mobile event | Product, cart, checkout, session and user-observed interaction. | Order creation, payment success, refund, or revenue. |
| Ads/analytics/communications | Campaign spend, click, exposure, message and attribution evidence under each source's rights. | An order or a deterministic attribution claim without a governed join. |

Reconciliation needs a durable candidate ledger with links, evidence, confidence, reason, policy version, and decision. Join an SDK checkout to an order only by stable approved lineage such as a server-issued correlation token or a verified provider checkout/order reference. Join a processor payment to an order only through explicit processor/transaction references or a reviewed evidence rule; amount, timestamp, email, or phone alone is insufficient. A pending candidate must not alter revenue. Corrections produce auditable supersession, not silent overwrite. Exact decimal strings and currency-aware arithmetic remain mandatory.

Stripe's [webhook guidance](https://docs.stripe.com/webhooks) says events can arrive out of order and may be delivered more than once; it recommends event IDs and object IDs with event type for duplicate handling. A processor adapter therefore retains both delivery and source-object identities, fetches missing objects when necessary, and applies a source-version policy. Stripe billing for AETHER subscriptions and Stripe on-ramp/payment-rail capabilities remain separate from a tenant's merchant payment connector, even though they share a provider name.

## Source-to-graph proof case

The fixture sequence is an executable acceptance contract for Shopify and a template for WooCommerce or another commerce provider:

1. SDK records `checkout_started` for tenant T, session S, correlation C. This is an observation with no order or revenue.
2. Shopify order O arrives by verified webhook, with a durable source revision and a reference to C. The same O arrives again through pull; one canonical order fact remains, with both delivery receipts linked.
3. Shopify updates O to paid and partially fulfilled. The versioned mapping emits the corresponding lifecycle facts with evidence; no new order is created.
4. A connected merchant processor sends payment P for O after a delay. The authority layer links P to O, records processor state, and leaves order revenue counted once. An unmatched P remains pending evidence.
5. Shopify emits partial refund R1, then R2. Net value is recomputed from exact, distinct refund facts. A replay of R1 changes nothing. A later provider correction supersedes the affected fact with lineage.
6. The identity service resolves the customer evidence, possibly late. Graph mutation intents use the canonical identity redirect and do not rewrite source history or cross a tenant boundary.
7. AETHER displays the current value with evidence timestamps and any payment/attribution limitations. Kyber can explain the raw-to-canonical-to-graph lineage and replay a bounded slice without a second production graph writer.

The graph relationships and projection fields should be defined in the existing graph and 360 contracts during the implementation wave; this blueprint does not authorize provider adapters to write graph nodes or edges directly.

## Acceptance fixtures and failure tests

The Shopify slice is not done until tests cover all of these cases against the current service seams:

- Signature invalid, wrong store/tenant, wrong credential, revoked scope, stale API version, and webhook replay all fail closed before source truth is accepted.
- A valid webhook is acknowledged only after permitted raw evidence is durable. A downstream normalization failure is visible and replayable. A failed page or partial batch leaves its checkpoint unchanged.
- Duplicate delivery, pull/webhook overlap, one object with multiple revisions, out-of-order correction, delete/tombstone, and repeated backfill preserve canonical and graph idempotency.
- A paid order plus processor charge counts once; partial refunds adjust value exactly; chargeback/reversal is not silently treated as a new sale or a zero.
- SDK checkout without order remains an observation; `commerce.order.created` does not become SDK `order_confirmed`; ambiguous SDK/order and payment/order joins stay pending.
- Source identity merge, split, reconnect, and erasure preserve permitted aliases and audit without resurrecting deleted identities.
- Tenant A cannot read, dedupe against, link to, replay, or project tenant B's raw, canonical, identity, or graph evidence.
- Unknown payload versions quarantine with original provenance; unsupported capability is `not_applicable`; missing access or stale data is `unavailable` or `degraded`, not empty or healthy.
- Shadow output is compared in an isolated store, including object count, order totals, refunds, projection fields, identity joins, and missing/degraded states. Live graph mutation occurs only through the fenced writer.
- A sandbox store and a seeded staging tenant prove connect, initial sync, webhook, replay, UI state, rollback, and data isolation. Fixture success alone remains replay-level evidence.

Add these fixtures beside the existing provider, commerce-contract, ingestion, graph-gateway, and frontend integration tests; certify each stream and provider environment separately. Exact file ownership and cutover gates are in [migration and delivery](migration-and-delivery.md). Canonical identity, revision, and event fields are in [canonical contracts](canonical-contracts.md).
