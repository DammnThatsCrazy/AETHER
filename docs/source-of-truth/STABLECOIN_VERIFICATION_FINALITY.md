# Stablecoin Verification and Finality

Aether Stablecoin Intelligence remains observation-first. A transaction hash is never treated as proof of payment by itself; verification compares tenant-scoped stored observations with provider evidence, registered deployment identity, receipt status, event/log identity, and chain-tip confirmations.

## EVM receipt verification

`StablecoinEVMReceiptVerifier` reads an existing observation, enforces tenant scope, resolves the canonical deployment from the registry, fetches `eth_getTransactionReceipt`, and verifies that the receipt or selected log points at the registered stablecoin contract before finality changes are allowed. Missing receipts move observations to `pending`, failed receipts move eligible observations to `failed` or `reverted`, and successful receipts advance to `confirmed` or `finalized` based on a configurable confirmation threshold.

## Finality history

Finality changes are delegated to `StablecoinFinalityService`, which preserves transition history and marks reverted observations for downstream correction. Observed or pending observations that have enough confirmations advance through `confirmed` before `finalized` so the history remains explainable and auditable.

## Remaining rollout boundary

This layer is not a live polling scheduler and does not execute payments. Live provider polling, Solana instruction verification, explorer/RPC disagreement comparison, production replay queues, and staging provider evidence remain separate rollout requirements.
