# Deploy-Time Registries

These JSON files are **fail-closed allowlists** enforced by the deploy and
verify scripts. They contain **public addresses only — never private keys**.

| File | Purpose | Enforced by |
|------|---------|-------------|
| `oracle_signers.json` | Per-network allowlist of authorized ORACLE signer addresses | `scripts/deploy.js`, `deploy/multichain_deployer.py` |
| `contracts.json` | Per-network record of deployed contract addresses | `scripts/post_deploy_verify.js` (deploy.js appends automatically) |

## Enforcement rules

- **Local networks** (`hardhat`, `localhost`): registries are **not** enforced —
  dev loops stay frictionless.
- **Testnets and mainnets**: enforcement is **mandatory** and **fail-closed**:
  - `deploy` aborts unless `ORACLE_ADDRESS` is listed under
    `oracle_signers.json → networks.<network>`.
  - `post_deploy_verify` aborts unless the target contract address is listed
    under `contracts.json → networks.<network>`.
  - A missing file, missing network key, or empty list all **reject**.

## Workflow

1. Before a testnet/mainnet deploy, add the oracle signer address (from your
   key-management ceremony) to `oracle_signers.json` under the target network in
   a reviewed change.
2. Run `deploy.js`. On success it appends the deployed `AnalyticsRewards` and
   `RewardRegistry` addresses to `contracts.json` under that network.
3. Review the `contracts.json` diff, then run `post_deploy_verify.js`.

## Network tiers

Network classification lives in `scripts/lib/networks.js`:

- `LOCAL`  = `hardhat`, `localhost`
- `TESTNET` = `sepolia`, `amoy`, `arbitrumSepolia`, `baseSepolia`, `optimismSepolia`
- `MAINNET` = everything else (fail-closed: unknown names inherit MAINNET gating,
  including the external-audit gate).
