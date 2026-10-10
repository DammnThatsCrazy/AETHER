# Architecture

## Actors

| Actor | On/Off chain | Description |
|-------|--------------|-------------|
| **User / tenant** | off → on | Performs an analytics action, then submits (or relays) the signed claim on-chain. **Holds the claim; Aether never submits it.** |
| **Oracle signer** | off | An `ORACLE_ROLE` holder. Observes verified analytics actions and signs claim payloads. Its private key lives in the backend key-management system, never on-chain and never in this repo. |
| **Campaign manager** | on | `CAMPAIGN_MANAGER_ROLE`. Creates/funds/pauses/resumes campaigns. |
| **Admin** | on | `DEFAULT_ADMIN_ROLE`. Rotates the oracle, pauses the contract, runs emergency withdrawals, manages roles. Intended to be a multisig/timelock. |
| **Relayer** (optional) | on | Any address may submit a valid signed claim on behalf of `user`; funds always go to `user`, not the submitter. |

## Components

```
                        off-chain                         on-chain
  ┌──────────────┐   sign(payload)   ┌───────────────────────────────────┐
  │ Oracle signer│ ────────────────► │ AnalyticsRewards                  │
  │ (backend)    │                   │  - verify oracle signature        │
  └──────────────┘                   │  - nonce replay guard             │
        ▲  reads reward config       │  - expiry check                   │
        │                            │  - campaign budget + per-user cap │
  ┌──────────────┐                   │  - transfer ERC-20 to user        │
  │ RewardRegistry│◄─────────────────┤  (holds all reward tokens)        │
  │ (catalog)     │                  └───────────────────────────────────┘
  └──────────────┘                              ▲   submit claim
                                                │
                                        ┌───────────────┐
                                        │ User / relayer│
                                        └───────────────┘
```

## Data flow: a single claim

1. User performs an analytics action; the backend verifies it off-chain.
2. The oracle signer computes:
   `messageHash = keccak256(abi.encodePacked(user, actionType, amount, nonce, expiry, chainId, contractAddress))`
   and signs it as an EIP-191 personal-sign message. (See `EIP712_SIGNATURE_SPEC.md`.)
3. The backend returns `{user, actionType, amount, nonce, expiry, signature}` to the user.
4. The user (or a relayer) calls `claimReward(user, actionType, amount, nonce, expiry, signature)`.
5. The contract:
   - rejects if paused, `user == 0`, `amount == 0`, nonce already used, or expired;
   - recovers the signer (EIP-2 low-s enforced, `v ∈ {27,28}`) and requires `ORACLE_ROLE`;
   - derives `campaignId = keccak256(actionType)`, requires the campaign to exist and be active;
   - requires `amount == campaign.rewardAmount`;
   - requires `amount ≤ remaining budget`;
   - enforces `maxClaimsPerUser` (0 = unlimited);
   - **effects then interactions**: marks the nonce used, debits budget, bumps the
     user's claim count, then `safeTransfer`s tokens to `user`;
   - emits `RewardClaimed`.

## On-chain / off-chain split

- **On-chain (trust-minimized):** signature verification, replay/expiry protection,
  budget accounting, per-user caps, custody of reward tokens, role management,
  pause and emergency withdrawal.
- **Off-chain (trusted oracle):** deciding *which* actions are eligible and issuing
  signatures. The oracle is a trusted component; compromise of its key allows
  minting claims up to campaign budgets (see `THREAT_MODEL.md`). This is the
  primary trust assumption and is mitigated by budgets, expiry, per-user caps,
  pause, and single-transaction oracle rotation.

## Custody model

The contract holds the entire reward-token balance across all campaigns. Budgets
are logical partitions of that balance tracked by `campaign.totalBudget` and
`campaign.spent`. There is no per-user balance held by the contract — tokens are
transferred out immediately on a successful claim.
