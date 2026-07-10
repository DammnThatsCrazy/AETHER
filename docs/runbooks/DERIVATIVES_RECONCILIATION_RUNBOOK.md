---
title: "Derivatives Reconciliation Runbook"
slug: runbooks/derivatives-reconciliation
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/derivatives/admin_routes.py
  - Backend Architecture/aether-backend/services/derivatives/reconciliation.py
canonical_owner: platform@aether
last_synced_commit: "03ab3a6"
---

# Derivatives Reconciliation Runbook

Operator surface: `/derivatives/ops` (Kyber) → `/v1/admin/kyber/derivatives/runtime`.
Requires `DERIVATIVES_OPERATOR`; all actions audited. Aether never
places, modifies, or cancels orders — remediation is always evidence
review, never trading.

## Variance alert (`aether.derivatives.reconciliation.variance`, P2)

1. Open the variances list; note `variance_type` (account_size,
   account_realized_pnl, …), expected vs observed, severity.
2. Check stream gaps first — an open gap on the account's markets is
   the most common cause (missed fills → stale projection).
3. If a gap explains it: trigger backfill for the gap window, wait for
   recovery, re-run reconciliation; the variance should not reappear.
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
