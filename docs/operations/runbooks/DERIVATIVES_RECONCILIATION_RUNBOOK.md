---
title: "Derivatives Reconciliation Runbook"
slug: runbooks/derivatives-reconciliation
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: "0.1.0"
source_files:
  - services/api/value/derivatives/admin_routes.py
  - services/api/value/derivatives/materializer.py
canonical_owner: platform@aether
source_hashes:
  "services/api/value/derivatives/admin_routes.py": "sha256:db52f0ac372e4cde3a12c90390a475f0c6ecd8918beff296e6fc0e8ab98814f9"
  "services/api/value/derivatives/materializer.py": "sha256:06eb7520f79a89ba20de9ee7785da10b3e8ee70b49ee2022bbae0956f88c61ce"
---

# Derivatives Reconciliation Runbook

Operator surface: `/derivatives/ops` (Kyber) → `/v1/admin/kyber/derivatives/runtime`.
Requires `DERIVATIVES_OPERATOR`; all actions audited. Aether never
places, modifies, or cancels orders — remediation is always evidence
review, never trading.

Market reference: an intake or sync that reports `market_reference_missing`
means the market has no row in the global registry yet. Check
`GET /market-sources`; if the venue's source is `null`, provision it with
`POST /market-sources/{venue}` (Olympus `public_reference` grant under the
reserved `olympus` scope), then re-run the link sync. GMX and Drift have no
market fetcher yet.

The fleet and conformance endpoints surface the real read-only venue adapters
(Hyperliquid, dYdX, GMX, Drift) alongside the simulator via `all_adapters()`, so
`POST /conformance/{adapter_id}` in step 4 below covers every registered venue.

## Variance alert (`aether.derivatives.reconciliation.variance`, P2)

1. Open the variances list; note `variance_type` (`size_mismatch`,
   `realized_pnl_mismatch`, … from the position materializer, or `account_*`
   from account-level snapshots), expected vs observed, severity.
2. Check stream gaps first — an open gap on the account's markets is
   the most common cause (missed fills → stale projection).
3. If a gap explains it: trigger backfill for the gap window, wait for
   recovery, then confirm the variance list. The
   `derivatives_position_materializer` worker (needs
   `AETHER_DERIVATIVES_RUNTIME_ENABLED` plus the reconciliation flag) re-derives
   each position from stored fills every minute and compares it with the venue's
   latest reported position; an unchanged disagreement is stored once, so a
   variance that persists across passes is still open, and one that stops being
   re-detected has converged. Verify a cleared variance against the venue
   statement before closing it.
4. If no gap: run adapter conformance (`POST /conformance/{adapter_id}`).
   A conformance failure is an adapter bug — file it, don't touch data.
5. Venue-side restatements arrive as corrections (new rows); confirm
   via the venue's own statement before marking the variance reviewed.

## Stream gap stalled (`aether.derivatives.stream.gap.stalled`, P2)

1. Gaps self-recover when the sequence progresses past the revealing
   message. A stalled gap means the stream is dead or the venue skipped
   sequences permanently.
2. Check the connector checkpoint's `advanced_at`; a stale checkpoint
   with an open gap means the adapter stopped — restart/credential
   issue, not data issue.
3. After recovery, run reconciliation on affected accounts to confirm
   projections caught up.

## Never do

- Never hand-edit positions, fills, or variances.
- Never mark a variance reviewed without a recorded explanation.
