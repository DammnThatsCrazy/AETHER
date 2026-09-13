---
title: "EVM Deploy & Emergency Runbook"
slug: runbooks/evm-deploy-emergency
section: operations
visibility: I
audience: [ops, dev-senior, security]
status: stable
since_version: "0.1.0"
source_files:
  - contracts/smart-contracts/contracts/AnalyticsRewards.sol
  - contracts/smart-contracts/audit/DEPLOYMENT.md
  - contracts/smart-contracts/audit/KNOWN_LIMITATIONS.md
canonical_owner: platform@aether
source_hashes:
  "contracts/smart-contracts/audit/DEPLOYMENT.md": "sha256:e728330b15261c786e1b195a882ba3997e8f3e12cf871f3e46cc9543821d945b"
  "contracts/smart-contracts/audit/KNOWN_LIMITATIONS.md": "sha256:4b0d06c0e8a27f62731e308482f5c201c786b638d7c65fc61571fcd777a0d34e"
  "contracts/smart-contracts/contracts/AnalyticsRewards.sol": "sha256:899d5684ce989049b36863123e9fa0c44fc9b1d01f16c2ef0838d408e7b0832f"
---

# EVM Deploy & Emergency Runbook

This runbook is the operational entry point for the EVM reward contracts. It
does **not** restate the audit package — it points to it and covers the
break-glass steps. Authoritative references:

- Deployment + verification procedure: `contracts/smart-contracts/audit/DEPLOYMENT.md`
- Threat model: `contracts/smart-contracts/audit/THREAT_MODEL.md`
- Known limitations (read before any mainnet action): `contracts/smart-contracts/audit/KNOWN_LIMITATIONS.md`
- Deploy scripts: `contracts/smart-contracts/scripts/deploy.js`,
  `contracts/smart-contracts/scripts/post_deploy_verify.js`,
  `contracts/smart-contracts/deploy/multichain_deployer.py`
- Signer/registry: `contracts/smart-contracts/deploy/registry/`

## Mainnet gate (do not skip)

Mainnet deployment with real funds is BLOCKED until an external audit (Trail of
Bits / OpenZeppelin / Spearbit / Halborn) is complete. Run `make audit-prep`
and see `EXTERNAL_AUDIT_PREPARATION_GUIDE`. Testnet deploys follow
`audit/DEPLOYMENT.md` with the fail-closed network gate.

## Deploy (testnet / staging)

1. Confirm the network gate and env/secret refs per `audit/DEPLOYMENT.md`
   (deploy is fail-closed on an unrecognized network).
2. `scripts/deploy.js` → `scripts/post_deploy_verify.js` (verifies the contract
   is not left paused and the oracle signer matches the registry).
3. Record the deployment address in `deploy/registry/` and the multichain
   deployment JSON.

## Emergency: pause

`AnalyticsRewards.sol` exposes admin-only break-glass functions:

- `pause()` / `unpause()` — global halt of claims.
- `pauseCampaign(campaignId)` — halt a single campaign.
- `rotateOracle(oldOracle, newOracle)` — replace a compromised oracle signer
  (nonce replay protection remains in force).
- `emergencyWithdraw(to)` / `emergencyWithdrawAmount(to, amount)` — recover
  budget from a paused contract to the admin destination only.

All require `DEFAULT_ADMIN_ROLE`. Estimate gas first with
`scripts/estimate_gas.js`. After any emergency action re-run
`post_deploy_verify.js` and record the incident.

## Never do

- Never deploy to mainnet before the external audit clears the gate.
- Never rotate the oracle to a key not in `deploy/registry/oracle_signers.json`.
- Never `unpause` before the root cause is understood and recorded.

See also: `docs/runbooks/SVM_DEPLOY_EMERGENCY_RUNBOOK.md`,
`docs/productization/staging-capstone/EXTERNAL_AUDIT_PREPARATION_GUIDE.md`,
`docs/runbooks/REWARD_DELIVERY_RUNBOOK.md`.
