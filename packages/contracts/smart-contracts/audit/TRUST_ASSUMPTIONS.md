# Trust Assumptions & Privileged Roles

## Privileged roles

| Role | Constant | Granted at deploy to | Powers | Can NOT |
|------|----------|----------------------|--------|---------|
| `DEFAULT_ADMIN_ROLE` | `0x00` | `_admin` | Grant/revoke `CAMPAIGN_MANAGER_ROLE`; `rotateOracle`; `pause`/`unpause`; `emergencyWithdraw*` (only whenPaused); is role-admin of all roles | Grant/revoke `ORACLE_ROLE` directly (reverts — must use `rotateOracle`); move funds while unpaused via emergency path; forge claims |
| `ORACLE_ROLE` | `keccak256("ORACLE_ROLE")` | `_oracle` | Its **signature** authorizes claims (it does not call the contract) | Change budgets, roles, or pause; sign for an amount ≠ campaign reward; bypass nonce/expiry |
| `CAMPAIGN_MANAGER_ROLE` | `keccak256("CAMPAIGN_MANAGER_ROLE")` | `_admin` | `createCampaign(WithCap)`, `pauseCampaign`, `resumeCampaign`, `addBudget` | Withdraw funds; rotate oracle; pause the whole contract |

`RewardRegistry` has its own `DEFAULT_ADMIN_ROLE` and `REGISTRY_MANAGER_ROLE`
(catalog metadata only; no fund custody).

## What we assume about each trusted party

### Admin (`DEFAULT_ADMIN_ROLE`)
- **Assumed** to be a multisig or timelock, **not** a single EOA. Enforced by the
  Governance Gate in `../RELEASE.md`, not by the contract.
- Trusted not to `emergencyWithdraw` maliciously. This is an intentional escape
  hatch for stuck funds / incident response and is deliberately constrained to the
  paused state so it cannot race legitimate in-flight claims.
- Compromise ⇒ total loss of contract balance (via pause + emergency withdraw) and
  ability to install a hostile oracle. This is the highest-value key; protect it
  with a multisig/timelock and hardware custody.

### Oracle signer (`ORACLE_ROLE`)
- Trusted to sign only legitimate, verified analytics actions, with correct
  `amount`, unique `nonce`, and sane `expiry`.
- Its key is held in the backend key-management system (out of this repo). It never
  appears on-chain or in source. Deploy tooling forbids well-known dev keys.
- Compromise ⇒ loss bounded by remaining campaign budgets (see `THREAT_MODEL.md` T9),
  recoverable by `pause()` + `rotateOracle()`.

### Campaign manager (`CAMPAIGN_MANAGER_ROLE`)
- Trusted to configure campaigns and fund budgets honestly. Cannot remove funds.
- Compromise ⇒ can misconfigure or pause campaigns and add budget (which requires
  their own tokens); cannot steal existing funds.

### Reward token
- **Assumed** to be a standard, non-malicious ERC-20: no transfer hooks
  (non-ERC-777), no fee-on-transfer, no rebasing, reverts on failure or returns a
  bool (handled via `SafeERC20`). A non-conforming token breaks budget accounting
  (see `KNOWN_LIMITATIONS.md`).

## Trust-minimized properties (do NOT require trust)

Even a fully hostile external caller cannot:
- claim without a fresh oracle signature bound to this chain and contract;
- replay a claim (nonce is single-use);
- exceed a campaign's budget or a user's cap;
- change the reward amount for a campaign;
- reenter the claim/withdraw paths;
- pause, withdraw, or manage roles.

## Governance expectations (operational, not enforced on-chain)

- `DEFAULT_ADMIN_ROLE` on both contracts held by a multisig/timelock.
- Oracle key ceremony + rotation runbook in place (`DEPLOYMENT.md`).
- Monitoring/alerting on `OracleUpdated`, pause/unpause, `emergencyWithdraw`, and
  all campaign lifecycle events.
