---
title: "Stablecoin Observer Runbook"
slug: runbooks/stablecoin-observer
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/stablecoins/rpc_observer.py
  - Backend Architecture/aether-backend/services/stablecoins/solana_observer.py
canonical_owner: platform@aether
last_synced_commit: "41c79d4"
---

# Stablecoin Observer Runbook

Operator surface: `/stablecoins/ops` (Kyber) → `/v1/admin/kyber/stablecoins`.
Requires `STABLECOIN_OPERATOR`; all actions audited. This runbook covers the
**on-chain observation** path (receipt/transaction observation and finality
confirmation). For depeg/valuation and reconciliation triage see the companion
`docs/runbooks/STABLECOIN_OPERATIONS_RUNBOOK.md`.

The two chain observers — `StablecoinEVMReceiptVerifier` (evm) and
`StablecoinSolanaTransactionVerifier` (svm) — are `CREDENTIAL_WAITING`: they are
implemented and require configured `json_rpc` endpoints; no live chain
observation has been validated in staging.

## Rollout flags

`AETHER_STABLECOIN_INGESTION_ENABLED`, `AETHER_STABLECOIN_INTELLIGENCE_ENABLED`
(plus a kill switch). Live finality tracking and price feeds are credential
gated; keep them off until per-chain RPC endpoints are configured and one
finality checkpoint has been validated in staging.

## Finality checkpoint not advancing

1. A stalled finality checkpoint usually means the RPC endpoint is unreachable
   or rate-limited, not a data problem. Check the observer's connector
   checkpoint `advanced_at` and the RPC health.
2. Finality confirmations demote on reorg: a checkpoint that regresses after a
   parent-hash change is correct — the observer rolled back to the fork point.
   Confirm the demoted range re-observes cleanly on the next scan.
3. Never mark a transaction final by hand; finality is derived only from
   observed confirmations.

## Depeg / valuation classification

Handled by valuation + peg logic; see `STABLECOIN_OPERATIONS_RUNBOOK.md`. The
observer feeds observations only — it does not classify depeg.

## Never do

- Never place or influence any on-chain action — observation only.
- Never enable live finality/price feeds without configured RPC + a validated
  staging checkpoint (see `CREDENTIAL_WAITING_PROMOTION_GUIDE`).
- Never hand-edit observations, receipts, or finality state.

See also: `docs/source-of-truth/STABLECOIN_VERIFICATION_FINALITY.md`,
`docs/source-of-truth/STABLECOIN_RECONCILIATION.md`,
`docs/runbooks/STABLECOIN_OPERATIONS_RUNBOOK.md`.
