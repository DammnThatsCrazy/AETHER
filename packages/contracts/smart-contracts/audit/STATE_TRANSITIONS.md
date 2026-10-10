# State Transitions

## Contract-level pause (Pausable)

```
        deploy
          │
          ▼
   ┌─────────────┐   pause()  [DEFAULT_ADMIN_ROLE]   ┌──────────┐
   │  UNPAUSED   │ ───────────────────────────────►  │  PAUSED  │
   │ (claims ok) │ ◄───────────────────────────────  │(no claims)│
   └─────────────┘   unpause() [DEFAULT_ADMIN_ROLE]  └──────────┘
```

- `claimReward` requires `whenNotPaused`.
- `emergencyWithdraw` / `emergencyWithdrawAmount` require `whenPaused` — they can
  only run while the contract is paused, which prevents racing in-flight claims.

## Campaign lifecycle

```
   createCampaign / createCampaignWithCap   [CAMPAIGN_MANAGER_ROLE]
                     │
                     ▼
              ┌──────────────┐  pauseCampaign   ┌──────────────┐
              │   ACTIVE     │ ───────────────► │   INACTIVE   │
              │ (claims ok)  │ ◄─────────────── │ (no claims)  │
              └──────────────┘  resumeCampaign  └──────────────┘
                     │
                     │ addBudget (either state) increases totalBudget
                     ▼
              spent grows on each claim; must satisfy spent ≤ totalBudget
```

Campaign fields and their mutability:

| Field | Set at | Mutable by | How |
|-------|--------|-----------|-----|
| `id` | create | — | immutable |
| `name` | create | — | immutable |
| `rewardAmount` | create | — | immutable (per-claim amount is fixed for the campaign) |
| `totalBudget` | create | manager | `addBudget` (increase only) |
| `spent` | 0 | claim path | `+= amount` on each successful claim |
| `active` | true | manager | `pauseCampaign` / `resumeCampaign` |
| `maxClaimsPerUser` | create | — | immutable |

> Note: there is no `removeBudget` — budget can only be added. Funds leave a
> campaign only through claims or a contract-wide `emergencyWithdraw` (whenPaused).

## Oracle rotation

```
   ORACLE_ROLE held by O_old, oracleSigner == O_old
                     │
                     │ rotateOracle(O_old, O_new)   [DEFAULT_ADMIN_ROLE]
                     │   requires: O_old,O_new != 0, O_old != O_new,
                     │             hasRole(ORACLE_ROLE, O_old)
                     ▼
   grant ORACLE_ROLE→O_new, revoke ORACLE_ROLE→O_old, oracleSigner = O_new
                     │  emits OracleUpdated(O_old, O_new)
                     ▼
   ORACLE_ROLE held by O_new, oracleSigner == O_new
```

- Direct `grantRole(ORACLE_ROLE, …)` / `revokeRole(ORACLE_ROLE, …)` **revert**
  with `OracleRoleManagedViaRotateOracle()` — rotation is the only path, keeping
  `oracleSigner` and role membership in lockstep.
- `getOracleAddress()` reverts if `oracleSigner` ever loses `ORACLE_ROLE`, surfacing
  any desync to monitoring (this state is not reachable through the public API).

## Nonce lifecycle

```
   unused  ──(successful claim consumes it)──►  used (permanent)
```

Nonces are global (not per-user, not per-campaign). A nonce is set to `used` in
the effects phase before the token transfer and can never be reused.

## Per-user claim counter

`userClaimCounts[user][campaignId]` increments by 1 per successful claim and is
compared against `maxClaimsPerUser` (when non-zero) before the counter is bumped.
