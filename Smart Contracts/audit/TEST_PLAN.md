# Test Plan & Commands

## Commands

```bash
cd "Smart Contracts"

# Install exact toolchain (see DEPENDENCIES.md)
npm ci            # or: npm install

# Compile (solc 0.8.20, optimizer 200 runs, viaIR)
npx hardhat compile

# Full unit/behavioral suite
npx hardhat test

# Coverage (optional)
npx hardhat coverage

# Gas measurement (in-process network; no keys needed)
npx hardhat run scripts/estimate_gas.js
# ...or price against a live chain:
#   npx hardhat run scripts/estimate_gas.js --network sepolia
```

## Current results (this environment)

- `npx hardhat compile` → **success** (20 files, evm target `paris`).
- `npx hardhat test` → **39 passing**.
- Slither → runs clean of high/critical findings (see `SLITHER.md`).

## Coverage map (test → property)

| Test (describe → it) | Exercises |
|----------------------|-----------|
| Deployment → token/roles/getter/zero-address reverts | constructor wiring, `getOracleAddress` |
| Campaign Management → create / dup / pause-resume / addBudget / cap / count | campaign lifecycle, access control |
| Claim Rewards → valid claim | happy path, `RewardClaimed`, transfer to `user` (I13) |
| Claim Rewards → reject expired | I8 expiry |
| Claim Rewards → reject reused nonce | I4 replay |
| Claim Rewards → reject wrong signer | I5 oracle authorization |
| Claim Rewards → reject paused campaign | campaign `active` gate |
| Claim Rewards → reject amount ≠ reward | I2 fixed reward |
| Claim Rewards → **reject exceeding budget** (drains a 1-claim budget) | I1 budget non-overspend |
| Claim Rewards → track user claim count | per-user counter |
| Claim Rewards → reject zero-address user | I14 |
| Claim Rewards → reject when contract paused | `whenNotPaused` |
| View Functions → nonce status / budget remaining | view correctness |
| Emergency → pause/unpause | Pausable |
| Emergency → **emergencyWithdraw only whenPaused** | I11 |
| Emergency → **emergencyWithdraw admin-only** | I10 |
| Signature Malleability → **reject high-s** / **reject bad v** | I7 EIP-2 |
| Domain Separation → **reject wrong contract** / **reject wrong chainId** | I6 domain binding |
| Oracle Rotation → **old signer rejected after rotation**, new accepted | I5/I9 rotation |
| Oracle Rotation → **invalid params revert** | rotation guards |
| Oracle Rotation → **admin-only** | I10 |
| Oracle Rotation → **direct grant/revoke ORACLE_ROLE blocked** | I9 mirror consistency |
| Oracle Rotation → non-oracle roles still grantable | AccessControl preserved |
| Per-User Claim Cap → **enforce maxClaimsPerUser** | per-user cap (I) |

Bold rows were added/repaired for this readiness pass. The pre-existing
"reject exceeding budget" test asserted the wrong revert (`InvalidRewardAmount`
fires before the budget check when `amount ≠ rewardAmount`); it now drains a
single-claim budget so it genuinely reaches `InsufficientCampaignBudget`.

## Gaps / recommended additional testing for the auditor

- **Foundry invariant/fuzz** campaign against I1/I2/I4 and the solvency invariant
  (I3) — see `INVARIANTS.md` "suggested targets".
- **Non-standard token** tests (fee-on-transfer, returns-false) to confirm the
  documented assumption boundary in `KNOWN_LIMITATIONS.md`.
- **Gas snapshotting** in CI to catch regressions on the `claimReward` hot path
  (currently ~155k gas; see gas output in `DEPLOYMENT.md`).
