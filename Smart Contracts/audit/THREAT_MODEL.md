# Threat Model

## Assets

1. **Reward-token balance** held by `AnalyticsRewards` (across all campaigns).
2. **Oracle signing authority** (ability to authorize claims).
3. **Admin authority** (rotate oracle, pause, emergency-withdraw, manage roles).
4. **Availability** of the claim path for legitimate users.

## Adversaries

- **External attacker** with no roles (arbitrary caller).
- **Malicious/compromised relayer** submitting others' claims.
- **Compromised oracle key.**
- **Compromised campaign manager.**
- **Compromised admin.**
- **Malicious reward-token contract** (out of scope by assumption; see below).

## Attack surface & mitigations

| # | Threat | Vector | Mitigation | Residual risk |
|---|--------|--------|------------|---------------|
| T1 | Replay a valid claim | Resubmit same `(nonce, sig)` | `usedNonces[nonce]` set in effects before transfer | None (nonce is single-use) |
| T2 | Cross-chain / cross-contract replay | Reuse a signature on another chain or a sibling deployment | `chainId` and `address(this)` are bound into the signed hash | None, provided the oracle always includes both (it does; verified in tests) |
| T3 | Signature malleability | Submit the `(r, n−s, flipped v)` twin of a valid sig | EIP-2 low-s check rejects high-s; `v ∈ {27,28}` enforced; nonce is the real anti-replay anyway | None |
| T4 | Forge a claim without the oracle key | Craft `(user, amount, …, sig)` | `ecrecover` must resolve to an `ORACLE_ROLE` holder | Requires the oracle private key |
| T5 | Expired-but-signed claim | Submit an old signature | `block.timestamp > expiry` reverts | None (miner timestamp skew is bounded and irrelevant at hour scale) |
| T6 | Drain a campaign beyond budget | Many claims | `amount ≤ totalBudget − spent`; `spent` updated pre-transfer | None |
| T7 | One user claims repeatedly | Loop claims | `maxClaimsPerUser` (when set); nonce uniqueness per claim | Unlimited if cap is 0 (by design; oracle also gates issuance) |
| T8 | Wrong-amount claim | Sign a larger `amount` | `amount == campaign.rewardAmount` enforced on-chain | Oracle could still sign a claim for the exact campaign amount to an arbitrary user (this is T9) |
| T9 | Oracle key compromise | Attacker signs valid claims | Loss bounded by **remaining campaign budgets**; admin can `pause()` and `rotateOracle()`; expiry + per-user caps limit blast radius | Up to remaining budget until detected and paused |
| T10 | Reentrancy on claim/withdraw | Malicious token callback | `nonReentrant` on `claimReward`; checks-effects-interactions ordering; `SafeERC20` | None for standard tokens; ERC-777/hook tokens are out of scope by assumption |
| T11 | Oracle role desync (monitoring blind spot) | Grant/revoke `ORACLE_ROLE` directly, leaving `oracleSigner` stale | `grantRole`/`revokeRole` **revert** for `ORACLE_ROLE`; rotation only via `rotateOracle` (atomic grant+revoke+mirror) | None |
| T12 | Emergency-withdraw abuse | Admin drains funds | Restricted to `DEFAULT_ADMIN_ROLE` **and** `whenPaused` (no race with in-flight claims); admin is trusted (multisig) | Admin is trusted; see `TRUST_ASSUMPTIONS.md` |
| T13 | Unauthorized campaign changes | Non-manager creates/pauses campaigns | `onlyRole(CAMPAIGN_MANAGER_ROLE)` | Manager is trusted |
| T14 | Griefing via front-run of a claim | Relayer front-runs user's submit | Funds always go to `user` regardless of `msg.sender`; nonce still consumed once | None (economically neutral) |
| T15 | Deploy with dev key / to wrong target | Operator error | Deploy scripts reject well-known Hardhat/Anvil keys on non-local; oracle/contract registries fail-closed; mainnet audit gate | Operational; mitigated by fail-closed tooling |
| T16 | Fee-on-transfer / rebasing token accounting drift | Non-standard reward token | **Assumption**: standard ERC-20 only. Documented in `KNOWN_LIMITATIONS.md` | Out of scope by assumption |

## Trust boundaries

- **Trusted:** oracle signer, campaign manager, admin (multisig/timelock), and the
  chosen reward-token contract.
- **Untrusted:** every external caller of `claimReward`, including relayers.

## Loss-bound summary

The maximum loss from an oracle-key compromise is the **sum of remaining campaign
budgets** at the moment of compromise, minus whatever per-user caps and expiry
windows prevent, until an admin pauses the contract. Keeping per-campaign budgets
small and rotation/pause response fast is the operational control for this risk.
