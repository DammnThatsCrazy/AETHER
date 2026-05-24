# Smart Contracts Release Checklist

This checklist defines the minimum release gates for `AnalyticsRewards` and `RewardRegistry`.

## 1) Build & Test Gate

1. Run unit tests in an environment with working solc `0.8.20` resolution:

   ```bash
   npm --prefix 'Smart Contracts' test
   ```

2. Archive full logs/artifacts for release evidence.
3. Do **not** release if tests were not executed successfully.

> Note: current local environment may fail with `HH502` (proxy/compiler download). See `TESTING.md`.

## 2) Deployment Gate

1. Set deployment env:
   - `REWARD_TOKEN_ADDRESS`
   - `ORACLE_ADDRESS`
   - `ADMIN_ADDRESS` (recommended multisig/timelock, not EOA)
2. Deploy:

   ```bash
   npx hardhat run scripts/deploy.js --network <network>
   ```

3. Record tx hashes, deployment block numbers, and final addresses.

## 3) Post-Deploy Verification Gate (mandatory)

Set verification env:
- `ANALYTICS_REWARDS_ADDRESS`
- `REWARD_REGISTRY_ADDRESS`
- `EXPECTED_ADMIN_ADDRESS`
- `EXPECTED_ORACLE_ADDRESS`
- `EXPECTED_REWARD_TOKEN_ADDRESS` (optional but recommended)

Run:

```bash
NETWORK=<network> npm --prefix 'Smart Contracts' run verify:postdeploy
```

Required pass checks:
- Admin role on AnalyticsRewards
- Admin role on RewardRegistry
- ORACLE_ROLE assignment
- `getOracleAddress()` equals expected oracle
- Contract not paused
- Reward token address matches expected (if provided)

## 4) Operational Readiness Gate

1. Confirm oracle key ceremony and recovery runbook.
2. Confirm alerts on:
   - `OracleUpdated`
   - pause/unpause
   - emergency withdrawals
   - campaign create/pause/resume/budget actions
3. Confirm incident contacts/on-call ownership.

## 5) Governance Gate

1. Confirm `DEFAULT_ADMIN_ROLE` controlled by multisig/timelock.
2. Confirm no privileged EOA-only custody remains.
3. Confirm emergency playbook approved by operators.
