# 05 — State Transitions

## Lifecycle

```
        initialize
   (once, admin=payer)          fund_vault (anyone, repeatable)
uninit ───────────────► ACTIVE ─────────────────────────────► ACTIVE
                          │  ▲                                    │
                   pause  │  │ unpause                            │ claim_reward
                          ▼  │                                    ▼
                        PAUSED                            vault -= amount
                     (claims blocked;                     user  += amount
                      fund/withdraw/                       nonce recorded
                      rotate/unpause                       totals += 
                      still allowed)
```

`withdraw`, `update_oracle`, `fund_vault` are valid in both ACTIVE and PAUSED.
`claim_reward` is valid only in ACTIVE.

## Per-instruction pre/post conditions

### initialize(oracle, chain_id)
- Pre: state/nonce PDAs do not exist; `chain_id != 0`.
- Post: `ProgramState{admin=payer, oracle, chain_id, scheme_version=1,
  paused=false, totals=0, bumps}`; empty `NonceTracker`. Emits `ProgramInitialized`.
- Idempotency: `init` fails if already initialized (cannot re-seize).

### claim_reward(action, amount, tenant_id, campaign_id, mint, nonce, expiry, sig)
- Pre (all must hold, in order): `!paused`; `action.len() <= 64`; `amount > 0`;
  `mint == NATIVE_SOL_MINT`; `now < expiry`; `nonce_key` unused; Ed25519 proof
  matches (oracle, reconstructed message, sig); `vault.lamports >= amount`;
  tracker not full.
- Post: `vault -= amount`; `user += amount`; `nonce_key` appended;
  `total_distributed += amount` (checked); `total_claims += 1` (checked). Emits
  `RewardClaimed`.
- Atomicity: on any failed require, the whole tx reverts — no partial payout,
  no nonce burn.

### fund_vault(amount)
- Pre: `amount > 0`.
- Post: system-program CPI transfer funder→vault. Emits `VaultFunded`.

### update_oracle(new_oracle)  [admin]
- Post: `state.oracle = new_oracle`. Emits `OracleUpdated`. Future proofs must be
  signed by `new_oracle`; in-flight proofs from the old oracle become invalid.

### pause() / unpause()  [admin]
- pause: requires `!paused` → sets `paused=true` (`AlreadyPaused` otherwise).
- unpause: requires `paused` → sets `paused=false` (`NotPaused` otherwise).

### withdraw(amount)  [admin]
- Pre: `amount > 0`; `vault.lamports >= amount`.
- Post: `vault -= amount`; `admin += amount`. Emits `VaultWithdrawal`.

## State fields and who can change them

| Field | Mutated by | Monotonic? |
|---|---|---|
| `admin` | (none; fixed at init) | — |
| `oracle` | `update_oracle` | no |
| `chain_id` | (none; fixed at init) | — |
| `scheme_version` | (none; fixed at init) | — |
| `paused` | pause/unpause | toggles |
| `total_distributed` | claim_reward | increasing |
| `total_claims` | claim_reward | increasing |
| `used_nonce_keys` | claim_reward | append-only (until full) |
