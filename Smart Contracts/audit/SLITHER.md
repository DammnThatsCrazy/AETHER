# Static Analysis — Slither

## How to run

Slither needs `solc 0.8.20` and the OpenZeppelin remapping. From `Smart Contracts/`:

```bash
# one-time toolchain
pip install slither-analyzer solc-select
solc-select install 0.8.20 && solc-select use 0.8.20

# run (filters out dependencies and the test-only mock)
slither . \
  --solc-remaps "@openzeppelin=node_modules/@openzeppelin" \
  --filter-paths "node_modules|contracts/test"
```

Slither drives `npx hardhat compile --force` under the hood, so the Hardhat
toolchain must be installed (`npm ci`).

## Run captured in this package

`slither-output.txt` is the verbatim output from this environment:

- Slither **0.11.5**, solc **0.8.20**.
- `. analyzed (20 contracts with 101 detectors)`, **10 results**, **0 high/critical**.

## Findings and disposition

| Detector | Location(s) | Severity | Disposition |
|----------|-------------|----------|-------------|
| `incorrect-equality` (dangerous strict equality) | `emergencyWithdraw` `balance == 0`; `RewardRegistry.getAction/getCampaign` `registeredAt == 0` | Informational | **Expected / safe.** `== 0` is a sentinel test (empty balance; unregistered entry), not an equality on attacker-influenced arithmetic. No change. |
| `timestamp` (block.timestamp comparison) | `claimReward` expiry; several `RewardRegistry` view checks | Informational | **Expected.** Expiry at minute–hour scale is insensitive to validator timestamp skew (see `KNOWN_LIMITATIONS.md` L10). |
| `assembly` (inline assembly) | `_recoverSigner` | Informational | **Expected.** Standard `ecrecover` signature-splitting assembly; bounded to a 65-byte input with EIP-2 low-s and `v ∈ {27,28}` checks. |
| `cyclomatic-complexity` | `claimReward` (13) | Informational | **Accepted.** All-in-one guarded claim path; each branch is test-covered (`KNOWN_LIMITATIONS.md` L8). |

## What Slither did NOT flag (notable absences)

No `reentrancy-eth`/`reentrancy-no-eth`, no `arbitrary-send`, no
`unprotected-upgrade`, no `uninitialized-state`, no `tx-origin`, no
`unchecked-transfer` (SafeERC20 is used), no `suicidal`. The reward token transfer
uses `SafeERC20.safeTransfer`, and the claim/withdraw paths are `nonReentrant` with
checks-effects-interactions ordering.

## Recommended follow-ups for the auditor

- Run `slither . --print human-summary` and `--print function-summary` for a
  structural overview.
- Consider `slither-check-erc` against the intended reward token, and Echidna/Foundry
  property tests for the invariants in `INVARIANTS.md`.
