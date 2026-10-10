---
title: Shopify Connector
slug: shopify-connector
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: "0.1.0"
---

# Shopify connector

## Current paths

Shopify has a legacy `BaseConnector` under
`services/backend/services/integrations/connectors/` and a native Universal
Provider Runtime capability, `shopify.admin.orders_read`, under
`services/backend/services/providers/shopify/`. The legacy route remains
available behind its existing connector flag. A native plugin registration is
not a tenant migration or a whole-commerce certification.

The native capability declares order pull and signed order webhook adapters,
account discovery, authentication, and an order normalizer. REST is the
compatibility/default pull path. This branch adds an opt-in, pinned GraphQL
Admin order reader with explicit live/test realm, verified Shop ID, updated-at
cursor, complete line items, and raw revision retention. Its manifest remains
credential-waiting and unavailable for live tenant enablement pending provider
evidence. The GraphQL path is an orders stream; it does not claim customer,
catalog, cart, payment settlement, or full historical bulk export coverage.

### Acquisition modes

The `orders_api` setting selects both the order transport and webhook posture:

| `orders_api` | Behavior | Credential profile |
|---|---|---|
| `rest` (default) | REST order polling only | API key and password; no webhook secret required |
| `rest_webhook` | REST order polling plus signed order webhooks | API key, password, and webhook HMAC secret |
| `graphql` | Pinned GraphQL order polling only | Admin access token and explicit `source_account_realm` (`live` or `test`) |

The manifest declares one pull stream per mode: `orders_rest` for `rest`,
`orders_rest_webhook` for `rest_webhook`, and `orders` for `graphql`. The
`orders_api` config default selects `rest` when omitted. Each connection runs
exactly one of these pull streams with its own scoped cursor. All three are
disabled by default as scheduler entries and activate for their matching mode.
The separate `orders_webhook` stream is enabled only for `rest_webhook` and
accepts the declared `orders/create`, `orders/update`, and `orders/cancelled`
topics. The GraphQL pull stream remains poll-only.

The public webhook gateway admits Shopify deliveries only for `rest_webhook`.
That mode still requires a configured secret and valid HMAC proof; missing or
invalid proof is denied. Poll-only REST and GraphQL requests are denied before
inbox persistence. For all handled routing, mode, and verification denials
before a request proves connection ownership, the public response is generic.
The gateway records only a bounded-reason tenantless metric internally; it
does not write a tenant-scoped denial row or inbox body. For `rest_webhook`,
successful HMAC verification and a second tenant/connection/account binding
check precede raw-rights admission. The request body is written to its
best-effort webhook inbox only after that admission succeeds. If raw-rights
admission fails, no request body or tenant-scoped raw denial record is retained.
A later failure after proof may retain tenant-scoped metadata-only evidence
only if its own raw-rights admission succeeds; failed verification remains
tenantless telemetry only and reveals no routing detail.
GraphQL mode remains poll-only until order webhooks can be
hydrated into the same complete, realm-bound snapshot contract. Provider
certification validates each declared credential profile; the Shopify manifest
still reports `credential_waiting` and does not imply that any tenant has
configured or verified a webhook secret.

### GraphQL order scopes

The GraphQL connection test and every GraphQL order pull require `read_orders`. Shopify
allows that scope to read recent orders from the rolling 60-day window. A full
historical backfill, or an incremental cursor older than that window, also
requires `read_all_orders`; without it the pull returns the permanent
`read_all_orders_required` failure before writing records or advancing its
cursor. Recent incremental sync remains available with `read_orders` alone.

The current shared manifest only accepts `StreamDescriptor.required_scopes`
for OAuth2 providers. Shopify's API-key and Admin-token profiles do not use
that OAuth2 declaration, so the mode-dependent base and historical scope rules
are enforced by Shopify's connection probe, account discovery, and pull
adapter. The connection probe reports whether `read_orders` is present and
whether historical access is available; the static manifest does not claim
that every credential has historical access.

## Native order data flow

```text
verified Shopify account and credential
  → bounded REST or opt-in GraphQL order pull
  → tenant/account-scoped protected raw Bronze revision
  → deterministic commerce.order.* event
  → consent-gated typed Bronze and transactional event outbox
  → supervised relay when enabled
  → provider-aware authority and projection gates (not yet live)
```

Native provider events do not enter through the SDK `/v1/batch` endpoint.
SDK commerce signals remain observations and cannot establish a Shopify order
or a settled payment. The current SDK-only Silver and identity consumers defer
provider events; no graph or revenue projection should be inferred from an
outbox receipt. GraphQL-mode order webhooks require a reviewed full-state
hydration and equivalence path before they can converge with GraphQL snapshots.

## Migration and evidence

Keep legacy tenant traffic on its current route while comparing verified raw
records, canonical facts, money, source authority, projections, and rollback
behavior with the native path. The
[universal connector blueprint](../../architecture/blueprints/universal-connector-runtime/README.md)
defines canonical IDs/events and the tenant cutover gates. The
[provider outbox rollout](../../architecture/blueprints/universal-connector-runtime/provider-outbox-rollout.md)
describes relay prerequisites and historical replay limits. No live Shopify
sandbox round-trip or tenant cutover is claimed by this page.
