# Deployment, Verification & Operational Runbooks

All secrets are supplied via **environment/secret references** — no private key
ever appears in source, config, or the registries (which hold public addresses
only). Deploy tooling **rejects the well-known Hardhat/Anvil default keys** on any
non-local network.

## Network tiers & fail-closed gates

Classification lives in `scripts/lib/networks.js` (JS) and `deploy/evm_guards.py`
(Python), kept in sync:

| Tier | Networks | Oracle/contract registry | Mainnet audit gate |
|------|----------|--------------------------|--------------------|
| LOCAL | `hardhat`, `localhost` | not enforced | not enforced |
| TESTNET | `sepolia`, `amoy`, `arbitrumSepolia`, `baseSepolia`, `optimismSepolia` | **enforced** | not enforced |
| MAINNET | everything else (fail-closed default) | **enforced** | **enforced** |

Three gates run before any non-local deploy (`scripts/deploy.js` and
`deploy/multichain_deployer.py` both enforce them):

1. **Mainnet audit gate** — mainnet-class deploys abort unless
   `audit/AUDIT_EVIDENCE.json` exists and is valid (`signoff.approved: true`, etc.).
2. **Default-key rejection** — refuses well-known dev keys/addresses.
3. **Oracle-signer registry** — `ORACLE_ADDRESS` must be allow-listed in
   `deploy/registry/oracle_signers.json` for the target network.

Post-deploy verification additionally requires the deployed **contract addresses**
to be registered in `deploy/registry/contracts.json` (deploy.js writes them there
automatically after a successful non-local deploy).

## A. Local (Hardhat) deploy

```bash
cd "Smart Contracts"
# In-process network (ephemeral):
REWARD_TOKEN_ADDRESS=0x<token> ORACLE_ADDRESS=0x<oracle> \
  npx hardhat run scripts/deploy.js
# Against a standalone node:
#   npx hardhat node        # terminal 1
#   ... --network localhost # terminal 2
```

Gates are skipped locally. Confirmed working in this environment.

## B. Testnet / staging deploy (env-driven)

```bash
cd "Smart Contracts"

# 1) Register the oracle signer (reviewed change):
#    edit deploy/registry/oracle_signers.json -> networks.sepolia += ["0x<oracle>"]

# 2) Provide secrets by reference (example uses shell env; use your secret store):
export DEPLOYER_KEY="$(secrets get aether/testnet/deployer_key)"   # NOT a dev key
export ETHEREUM_TESTNET_RPC="$(secrets get aether/testnet/rpc)"
export REWARD_TOKEN_ADDRESS=0x<token>
export ORACLE_ADDRESS=0x<oracle>            # must match the registry entry
export ADMIN_ADDRESS=0x<multisig>           # recommended: multisig/timelock

# 3) Deploy:
npx hardhat run scripts/deploy.js --network sepolia
#    -> on success, appends addresses to deploy/registry/contracts.json

# 4) Verify source on the explorer (command printed by deploy.js):
npx hardhat verify --network sepolia <registry> "<admin>"
npx hardhat verify --network sepolia <rewards> "<token>" "<admin>" "<oracle>"

# 5) Post-deploy invariant + registry verification:
export ANALYTICS_REWARDS_ADDRESS=0x<rewards>
export REWARD_REGISTRY_ADDRESS=0x<registry>
export EXPECTED_ADMIN_ADDRESS=0x<admin>
export EXPECTED_ORACLE_ADDRESS=0x<oracle>
export EXPECTED_REWARD_TOKEN_ADDRESS=0x<token>
NETWORK=sepolia npm run verify:postdeploy
```

The multi-chain deployer wraps the same flow with the same gates:

```bash
python3 deploy/multichain_deployer.py --chain ethereum --network testnet \
  --token-address 0x<token> --oracle-address 0x<oracle>
```

## C. Mainnet deploy (blocked until audited)

Identical to testnet, but the **mainnet audit gate must be satisfied first**:
place a valid `audit/AUDIT_EVIDENCE.json` (see `AUDIT_EVIDENCE.template.json`).
Until then, both deployers abort mainnet-class deploys. Example of the block:

```
MAINNET AUDIT GATE: refusing to deploy to 'mainnet'. No external-audit evidence
at audit/AUDIT_EVIDENCE.json. Mainnet real-value activation stays BLOCKED ...
```

## Gas reference (measured on the in-process network)

| Operation | Gas units |
|-----------|-----------|
| deploy `RewardRegistry` | ~1,538,764 |
| deploy `AnalyticsRewards` | ~1,889,074 |
| `createCampaign` | ~226,756 |
| `claimReward` (hot path) | ~155,271 |
| `addBudget` | ~54,273 |
| `pauseCampaign` | ~32,643 |
| `rotateOracle` | ~63,838 |

Re-run `npx hardhat run scripts/estimate_gas.js --network <chain>` to price against
a specific chain's fee market before budgeting.

## Runbook: pause / unpause (incident response)

```bash
# Pause (freezes all claims). DEFAULT_ADMIN_ROLE (multisig) only.
cast send <rewards> "pause()"           # or via the multisig UI
# Verify:
cast call <rewards> "paused()(bool)"    # -> true
# Resume once safe:
cast send <rewards> "unpause()"
```

Trigger conditions: suspected oracle-key compromise, anomalous claim volume, token
contract incident, or explorer verification mismatch.

## Runbook: oracle rotation

```bash
# Atomic grant(new) + revoke(old) + oracleSigner mirror. Admin only.
cast send <rewards> "rotateOracle(address,address)" <O_old> <O_new>
# Verify:
cast call <rewards> "getOracleAddress()(address)"   # -> O_new
# Also update the registry allowlist (reviewed change):
#   deploy/registry/oracle_signers.json -> add O_new (and remove O_old)
```

Notes: direct `grantRole`/`revokeRole` on `ORACLE_ROLE` revert by design. If a key
is compromised, `pause()` first, rotate, then `unpause()`.

## Runbook: emergency withdrawal

```bash
cast send <rewards> "pause()"                              # required precondition
cast send <rewards> "emergencyWithdraw(address)" <safe>    # all tokens -> safe
# or a specific amount:
cast send <rewards> "emergencyWithdrawAmount(address,uint256)" <safe> <amount>
```

`emergencyWithdraw*` revert unless the contract is paused, preventing races with
in-flight claims. Destination should be a secured treasury/multisig.
