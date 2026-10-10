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
  "services/api/value/derivatives/admin_routes.py": "sha256:94eb1c95b844e86a866fc44b88e831116ebd1a8892ce2535520848e35b57924b"
  "services/api/value/derivatives/materializer.py": "sha256:202d4cb73dfb080a617cfeb8db34dd7e03f085581b47d40640f3c3e68bb15130"
---

# Derivatives Reconciliation Runbook

Operator surface: `/derivatives/ops` (Kyber) → `/v1/admin/kyber/derivatives/runtime`.
Requires `DERIVATIVES_OPERATOR`; all actions audited. Aether never
places, modifies, or cancels orders — remediation is always evidence
review, never trading.

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
