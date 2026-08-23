---
title: SDK Commerce Bridges
slug: sdks/sdk-commerce-bridges
section: sdks
visibility: I
audience: [dev-senior, architect]
status: beta
since_version: "8.12.0"
source_files:
  - packages/shared/contracts/event-registry.json
  - packages/shared/commerce.ts
  - packages/shared/commerce-bridge.ts
  - packages/web/src/modules/commerce-detection.ts
  - packages/web/src/bridges/
  - Backend Architecture/aether-backend/shared/commerce_contracts/order.py
  - Backend Architecture/aether-backend/shared/integration_contracts/events.py
  - Backend Architecture/aether-backend/shared/integration_contracts/commerce_bridge.py
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
last_synced_commit: "bee65298"
---

# SDK Commerce Bridges

**Status (follow-on program, shipped):** the web SDK **detection engine** and
**commerce bridges** shipped in the UPR follow-on program (PR-C): the
detection engine at `packages/web/src/modules/commerce-detection.ts`, the
bridges at `packages/web/src/bridges/*`, the shared mapping at
`packages/shared/commerce-bridge.ts`, and the server-side bridge contract at
`shared/integration_contracts/commerce_bridge.py`. The acceptance criteria in
§4 below describe the shipped contract and its evidence. SDK event-registry
convergence remains OUT of scope — the dotted `commerce.*` types stay in the
runtime domain until a dedicated convergence program.

## 1. Why this exists

The UPR emits canonical, provider-neutral `commerce.*` `AetherEvent`s, but the
dotted `commerce.*` event types deliberately live in the **runtime domain** —
they are NOT merged into the SDK event registry
(`packages/shared/events.ts`, generated from
`packages/shared/contracts/event-registry.json`), mirroring the `comms`
precedent. The web SDK therefore cannot yet observe or re-emit these events.
Bridges close that gap without touching the registry.

## 2. What shipped

### 2.1 Web SDK detection engine

Detect commerce frames on the web — product pages, carts, checkout — and emit
a minimal, stable SDK signal that a commerce interaction occurred. The
detection engine lives in the SDK plane and produces raw SDK events only; it
does NOT emit runtime `commerce.*` types itself. Shipped at
`packages/web/src/modules/commerce-detection.ts`.

### 2.2 Commerce bridges

Map canonical `commerce.*` `AetherEvent`s to SDK event shapes and bridge
`OrderSnapshot` into SDK payloads (DECISION 1 vocabulary, §2.3):

- **Envelope bridge** — translate a runtime `AetherEvent` into an SDK-shaped
  event under the DECISION 1 vocabulary: the bare `sdk_event_type` keys the
  SDK signal; the dotted `canonical_event_type` stays visible in metadata.
  Envelope bridging is a projection — `confirmed=False`,
  `confirmation_state="not_found"` always; confirmation verdicts come only
  from `confirm_interaction`.
- **Payload bridge** — project the canonical JSON-safe `OrderSnapshot`
  (`shared/commerce_contracts/order.py`) into SDK payload structures:
  `{order_id, status, currency, total: {amount: "<exact decimal string>",
  currency}, created_at, updated_at, account_id}`, with amounts as strings
  (`model_dump(mode="json")`) so no amount drifts through floating point. Also
  a projection — `confirmed=False`, `confirmation_state="not_found"` always.
- **Server-side confirmation** — confirm a detected web commerce interaction
  against the corresponding server-side canonical event
  (`confirm_interaction`), using the idempotency-key lineage
  (`source_record_id`) so a web observation and its server truth reconcile.
  Verdicts: `matched` (lineage match, not yet confirmed) / `replay`
  (signal_id already in `canonical.context["confirmed_signal_ids"]`) /
  `unconfirmed` (lineage mismatch or missing) / `not_found` (canonical is
  None). `confirmed=True` only on `matched`.

### 2.3 DECISION 1 — the S2 vocabulary (canonical bridge contract)

The Python and TypeScript mirrors speak ONE vocabulary. This is the contract
the shipped bridges implement:

1. **`sdk_event_type` = BARE SDK signal name** (`product_view`,
   `cart_updated`, `checkout_started`, `order_confirmed`). The SDK keys on
   bare names — never prefix `commerce.`.
2. **`canonical_event_type` = DOTTED runtime event type**
   (`commerce.product.viewed`, `commerce.order.confirmed`, ...). This is what
   `AetherEvent.event_type` actually is.
3. **Mapping table = exactly the 4 semantically-valid pairs** (never a
   fabricated type):

   | canonical (`event_type`) | `sdk_event_type` |
   |---|---|
   | `commerce.product.viewed` | `product_view` |
   | `commerce.cart.updated` | `cart_updated` |
   | `commerce.checkout.started` | `checkout_started` |
   | `commerce.order.confirmed` | `order_confirmed` |

   **`commerce.order.created` MUST NOT map to `order_confirmed`** — a
   created-but-not-confirmed order must never be reported as confirmed
   (false-positive rule).
4. **Unmapped canonical types PASS THROUGH** (`sdk_event_type` = the
   `event_type`). The TS bridge must NOT throw `BridgeMappingError` on
   unmapped types — it mirrors Python exactly.
5. **`payload` = canonical JSON-safe `OrderSnapshot`**:
   `{order_id, status, currency, total: {amount: "<exact decimal string>",
   currency}, created_at, updated_at, account_id}`. Amounts are STRINGS
   (never `Decimal` objects, never floats). Python emits
   `model_dump(mode="json")`; TS mirrors this exact shape. The richer flat
   client view (subtotal/tax/shipping/items/confirmed_signal_id) is NOT part
   of the S2 payload.

## 3. The contract the bridges honor

The shipped bridges uphold the UPR invariants:

- **Deterministic** — the same canonical event yields the same SDK shape; no
  wall-clock/randomness in the mapping.
- **Provider-neutral** — mapping keys off `event_type` + canonical payload, never
  off `provider` / `provider_identity` (those stay metadata).
- **Idempotency** — a bridged/confirmed SDK event must not double-emit;
  reuse `AetherEvent.idempotency_key` lineage.
- **Tenant scoping** — server-authoritative; the bridge never widens scope.
- **No silent drops** — anything the bridge cannot map is surfaced, never
  swallowed.

## 4. Acceptance criteria (shipped)

All of the following hold — the detection engine, the envelope/payload
bridges, and the confirm route (with replay and false-positive tests) are
landed:

- [x] The web SDK detection engine emits a stable, versioned SDK signal, with
      tests covering product-page / cart / checkout / confirmation flows
      (`packages/web/src/modules/commerce-detection.ts`).
- [x] Envelope + payload bridges are deterministic, provider-neutral,
      idempotent, tenant-scoped, and drop-safe (contract §3 above), with a
      parity test against the canonical `AetherEvent` shapes
      (`packages/shared/commerce-bridge.ts` + server-side
      `shared/integration_contracts/commerce_bridge.py`). They implement the
      DECISION 1 vocabulary (§2.3): bare `sdk_event_type`, dotted
      `canonical_event_type`, the exact 4-mapping table (never a fabricated
      type), pass-through of unmapped canonical types (no
      `BridgeMappingError`), and the canonical JSON-safe `OrderSnapshot`
      payload with string amounts.
- [x] Server-side confirmation (`confirm_interaction`) reconciles a detected
      web interaction against a canonical `commerce.*` event using
      `source_record_id` lineage, with false-positive tests (no
      `commerce.order.created` → `order_confirmed` mapping) and replay tests
      (signal_id already in `canonical.context["confirmed_signal_ids"]`).
- [x] Both bridges are projections: `confirmed=False`,
      `confirmation_state="not_found"` always; confirmation verdicts come only
      from `confirm_interaction` (`matched` / `replay` / `unconfirmed` /
      `not_found`), with `confirmed=True` only on `matched`.
- [x] `make ci-check` passes including SDK contract and docs checks; this
      document's `source_files` are re-reviewed and `last_synced_commit`
      re-stamped at that gate.
- [x] SDK event-registry convergence remains OUT of scope — the dotted
      `commerce.*` types still live in the runtime domain until a dedicated
      convergence program.

## Related docs

- [COMMERCE-EVENT-CONTRACT](COMMERCE-EVENT-CONTRACT.md)
- [UNIVERSAL-PROVIDER-RUNTIME](UNIVERSAL-PROVIDER-RUNTIME.md)
- [ADR-009: Universal Provider Runtime](decisions/ADR-009-universal-provider-runtime.md)
