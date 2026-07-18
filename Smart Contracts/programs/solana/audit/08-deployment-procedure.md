# 08 — Deployment Procedure

All secrets (keypairs, RPC URLs) come from environment / secret references. No
keypair is ever committed or embedded. See `registry/upgrade-authority-policy.md`.

## Prerequisites

- `solana` CLI 1.18.26, `anchor` CLI 0.30.1, `cargo-build-sbf`, node/yarn.
- A funded deployer keypair (path via env), held in a secret manager.

## 0. One-time: program keypair + id sync

```bash
cd "Smart Contracts/programs/solana"
anchor keys sync     # generates target/deploy/aether_rewards-keypair.json (gitignored)
                     # and rewrites declare_id! + Anchor.toml to the real id
```

The committed `declare_id!` is a **placeholder** valid 32-byte id
(`7pbSKNKWPHqUVPmvkBwogxtyyp57P9n7FdDzRxQUCM2o`); `anchor keys sync` replaces it.

## 1. Localnet

```bash
solana-test-validator --reset &
export ANCHOR_PROVIDER_URL=http://127.0.0.1:8899
export ANCHOR_WALLET="$HOME/.config/solana/id.json"
bash scripts/deploy_localnet.sh
# then initialize (oracle pubkey + chain_id 104):
AETHER_ORACLE_PUBKEY=<ORACLE_PUBKEY> AETHER_CHAIN_ID=104 anchor migrate
```

## 2. Testnet (credential-gated)

Inject from your secret manager:

```bash
export AETHER_TESTNET_RPC_URL="https://<private-or-public-testnet-rpc>"
export AETHER_DEPLOYER_KEYPAIR="/secrets/aether-testnet-deployer.json"
export AETHER_UPGRADE_AUTHORITY="<GOVERNANCE_OR_MULTISIG_PUBKEY>"
export AETHER_ORACLE_PUBKEY="<ORACLE_PUBKEY>"
export AETHER_CHAIN_ID=102

bash scripts/deploy_testnet.sh      # build, deploy, set-upgrade-authority, verify, register
AETHER_CHAIN_ID=102 anchor migrate  # initialize state
yarn smoke:testnet                  # read-only verification
```

`deploy_testnet.sh` refuses to run unless the required secret refs are present,
moves upgrade authority to `$AETHER_UPGRADE_AUTHORITY`, verifies it with
`solana program show`, and records `program_id` + authority in the registry.

## 3. Mainnet — BLOCKED

Mainnet real-value deployment is **BLOCKED** and there is intentionally no
`deploy_mainnet.sh`. Release gate (all required):

1. Recorded external-audit report with findings triaged/closed (attach id + hash
   to `registry/program-registry.json` mainnet entry).
2. Upgrade authority AND runtime `admin` are a multisig (Squads or equivalent).
3. Reproducible build verified (`13`), on-chain bytecode hash matches.
4. Oracle key in HSM/KMS with monitored rotation runbook.
5. Vault funding bounded to expected outflow; incident/pause runbook rehearsed.
6. Pre-mainnet limitations addressed or explicitly risk-accepted with sign-off
   (see `10`), especially nonce-tracker scaling and fund-isolation.

## Post-deploy checklist

- [ ] `solana program show <id>` upgrade authority == policy target
- [ ] state PDA initialized; `chain_id` matches cluster (`yarn registry:verify`)
- [ ] oracle pubkey == expected
- [ ] vault funded to planned amount (integer lamports)
- [ ] registry updated (program_id, upgrade_authority, chain_id, idl hash)
- [ ] event monitoring on `RewardClaimed`/`VaultWithdrawal` live
