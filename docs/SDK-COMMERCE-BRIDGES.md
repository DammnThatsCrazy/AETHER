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
  - Backend Architecture/aether-backend/shared/commerce_contracts/order.py
  - Backend Architecture/aether-backend/shared/integration_contracts/events.py
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
last_synced_commit: "c6aa7606"
---

# SDK Commerce Bridges

**Documentation only — NO code ships from this document.** This spec exists so
the follow-on is scoped and ready: what the **web SDK detection engine** and
**commerce bridges** will do, the contract they must honor, and the acceptance
criteria for when they ship. It is an explicitly deferred follow-on of
[ADR-009](decisions/ADR-009-universal-provider-runtime.md), NOT built in this
program.

## 1. Why this exists

The UPR emits canonical, provider-neutral `commerce.*` `AetherEvent`s, but the
dotted `commerce.*` event types deliberately live in the **runtime domain** —
they are NOT merged into the SDK event registry
(`packages/shared/events.ts`, generated from
`packages/shared/contracts/event-registry.json`), mirroring the `comms`
precedent. The web SDK therefore cannot yet observe or re-emit these events.
Bridges close that gap without touching the registry.

## 2. What the follow-on will build

### 2.1 Web SDK detection engine

Detect commerce frames on the web — product pages, carts, checkout — and emit
a minimal, stable SDK signal that a commerce interaction occurred. The
detection engine lives in the SDK plane and produces raw SDK events only; it
does NOT emit runtime `commerce.*` types itself.

### 2.2 Commerce bridges

Map canonical `commerce.*` `AetherEvent`s to SDK event shapes and bridge
`OrderSnapshot` into SDK payloads:

- **Envelope bridge** — translate a runtime `AetherEvent`
  (`commerce.order.created`, ...) into an SDK-shaped event that downstream SDK
  consumers already understand, keeping the canonical `event_type` visible in
  metadata.
- **Payload bridge** — project `OrderSnapshot` / `CommerceOrder`
  (`shared/commerce_contracts/order.py`) into SDK payload structures, using
  `Money` (exact `Decimal` amount + ISO-4217 currency) unchanged so no amount
  drifts through floating point.
- **Server-side confirmation** — confirm a detected web commerce interaction
  against the corresponding server-side canonical event, using the
  idempotency-key lineage (`source_record_id`) so a web observation and its
  server truth reconcile.

## 3. The contract the bridges MUST honor

Any bridge that ships must uphold the UPR invariants:

- **Deterministic** — the same canonical event yields the same SDK shape; no
  wall-clock/randomness in the mapping.
- **Provider-neutral** — mapping keys off `event_type` + canonical payload, never
  off `provider` / `provider_identity` (those stay metadata).
- **Idempotency** — a bridged/confirmed SDK event must not double-emit;
  reuse `AetherEvent.idempotency_key` lineage.
- **Tenant scoping** — server-authoritative; the bridge never widens scope.
- **No silent drops** — anything the bridge cannot map is surfaced, never
  swallowed.

## 4. Acceptance criteria (when it ships)

The follow-on ships only when all of the following hold:

- [ ] The web SDK detection engine emits a stable, versioned SDK signal with
      tests covering product-page / cart / checkout / confirmation flows.
- [ ] Envelope + payload bridges are deterministic, provider-neutral,
      idempotent, tenant-scoped, and drop-safe (contract §3 above), with a
      parity test against the canonical `AetherEvent` shapes.
- [ ] Server-side confirmation reconciles a detected web interaction against a
      canonical `commerce.*` event using `source_record_id` lineage, with
      false-positive / replay tests.
- [ ] `make ci-check` passes including SDK contract and docs checks; this
      document's `source_files` are re-reviewed and `last_synced_commit`
      re-stamped at that gate.
- [ ] SDK event-registry convergence remains OUT of scope — the dotted
      `commerce.*` types still live in the runtime domain until a dedicated
      convergence program.

## Related docs

- [COMMERCE-EVENT-CONTRACT](COMMERCE-EVENT-CONTRACT.md)
- [UNIVERSAL-PROVIDER-RUNTIME](UNIVERSAL-PROVIDER-RUNTIME.md)
- [ADR-009: Universal Provider Runtime](decisions/ADR-009-universal-provider-runtime.md)
