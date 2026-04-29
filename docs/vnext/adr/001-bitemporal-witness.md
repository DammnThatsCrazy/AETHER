# ADR-001: Bitemporal Storage + Witness Signatures

Status: Proposed
Owner: Backend Architecture
Flag: `AETHER_FEATURE_BITEMPORAL` and `AETHER_FEATURE_WITNESS` (independent, default off)

## Context

Today the graph stores `created_at` and `updated_at` on most edges and nodes,
but there is no distinction between *valid time* (when the fact was true in the
world) and *transaction time* (when AETHER recorded it). This makes it
impossible to answer "what did the system believe on day D?" — a recurring
need for audit, dispute resolution, and counterfactual replay. Separately, all
ingestion paths trust the SDK to send accurate events; there is no
cryptographic chain of custody from emitter to graph.

## Decision

Two additive layers, independently flag-gated.

### Bitemporal mixin

Single failure surface: `Backend Architecture/aether-backend/shared/bitemporal/mixin.py`.

```python
class BitemporalMixin:
    valid_from: datetime
    valid_to: datetime | None        # None = currently valid
    tx_from: datetime                # when AETHER recorded it
    tx_to: datetime | None           # None = current row
    superseded_by: UUID | None       # forward pointer for closed rows
```

Mounted onto `Backend Architecture/aether-backend/shared/graph/graph.py` node
and edge base classes. Existing reads continue to return current rows
(`tx_to IS NULL AND valid_to IS NULL`) — no consumer changes required. New
read path: `GraphClient.as_of(valid_at=..., tx_at=...)` returns a snapshot
view backed by the same tables.

### Witness verifier middleware

Single failure surface:
`Backend Architecture/aether-backend/middleware/witness_verifier.py`.

Each SDK event optionally carries:

```ts
witness?: {
  alg: "ed25519",
  kid: string,           // KMS key id
  sig: string,           // base64 over canonical JSON of the event body
  emitted_at: string,    // RFC3339, used for replay window
}
```

Middleware verifies signature against a tenant-scoped key registry, attaches
`witness_status: "verified" | "unsigned" | "expired" | "invalid"` to the
inbound event envelope, and lets the event continue. Verification is
**advisory** during a configurable grace period (`WITNESS_GRACE_DAYS`,
default 30) and becomes **enforced** after a per-tenant cutover.

## Consequences

- Touches: graph base classes, two ingestion middleware files, the SDK type
  in `packages/shared/events.ts` (additive optional field).
- Does **not** touch: any model `predict()` path, agent controller, oracle,
  Shiki UI render path. Witness status surfaces in audit logs only until a
  follow-up ADR exposes it in Shiki.
- API impact: `GET /v1/graph/...` unchanged. New `GET /v2/graph/as-of?...`
  added behind the bitemporal flag.
- Storage: roughly 2x row count for high-churn entities over time. Mitigated
  by table partitioning on `tx_from` and a TTL on closed rows older than
  the regulatory retention window.

## Build sequence

1. Land `BitemporalMixin` and Alembic migration that adds the four columns
   plus `superseded_by`, all nullable. Backfill `valid_from := created_at`,
   `tx_from := created_at`. No existing column changes.
2. Add a write-path adapter so existing `.save()` calls close the prior row
   (`tx_to := now()`) and insert a new one. Wrap in a transaction; assert
   exactly one current row per logical id.
3. Add `GraphClient.as_of(...)` and a thin `/v2/graph/as-of` endpoint.
4. Land `witness_verifier.py` with verification disabled by default.
   Attach `witness_status` to the event envelope; emit a metric
   (`witness_status_total{status=...}`).
5. Stand up the per-tenant key registry as a new `witness_keys` table with
   rotation columns (`active_from`, `revoked_at`).
6. Flip `AETHER_FEATURE_WITNESS` to advisory in staging; observe metric for
   one week before enforcing.

## Failure modes & rollback

- **Migration is forward-only but reversible-by-flag.** Setting
  `AETHER_FEATURE_BITEMPORAL=off` causes `GraphClient` to bypass the
  as-of path and continue reading current rows. Schema columns remain but
  go unused.
- **Witness verifier failure** (key registry down, KMS unavailable):
  middleware fails open with `witness_status: "unverified"` and an alert.
  Ingestion never blocks on signature verification while the flag is in
  advisory mode. In enforced mode, an explicit per-tenant kill switch
  (`tenant.enforce_witness = false`) reverts to advisory in <1 min.
- **Hot-row contention.** If a logical id receives a high write rate,
  the close-and-insert pattern creates lock contention. Mitigated by row-level
  locking on `(logical_id, tx_to IS NULL)`; if contention exceeds threshold,
  the write path falls back to in-place update with the old row preserved
  in an append-only audit table.

## Acceptance

- `GET /v2/graph/as-of?valid_at=...` returns the historical snapshot with
  p95 < 200 ms on a 10 M-row test fixture.
- `witness_status_total{status="verified"}` exceeds 95 % of inbound events
  for at least one onboarded tenant before promoting `AETHER_FEATURE_WITNESS`
  to Accepted.
- Disabling either flag returns the system to v8.8.0 behavior with no read
  or write errors in a synthetic load test.
