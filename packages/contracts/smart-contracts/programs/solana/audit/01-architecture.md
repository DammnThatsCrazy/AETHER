# 01 — Architecture

## Roles / off-chain components

- **User / recipient** — the account that receives a reward. Does not need to
  sign the claim; it is bound into the oracle-signed proof by pubkey.
- **Oracle** — an off-chain Ed25519 signer (HSM/KMS-held). Observes analytics
  events and issues signed reward proofs. Its pubkey is stored on-chain and
  rotatable by the admin.
- **Relayer / fee payer** — submits the claim transaction (pays fees). Can be the
  user or an Aether relayer. Has no privileged power.
- **Admin** — governance authority stored in `ProgramState.admin`: pause/unpause,
  rotate oracle, withdraw from vault.
- **Upgrade authority** — the BPF loader authority that can replace the program.
  Governed separately (see `04-privileged-roles.md`).

## On-chain accounts

| Account | Kind | Seeds | Purpose |
|---|---|---|---|
| `ProgramState` | PDA data account | `["aether_state"]` | admin, oracle, chain_id, scheme_version, paused, totals, bumps |
| `Vault` | PDA system account | `["aether_vault", state]` | holds native SOL reward pool |
| `NonceTracker` | PDA data account | `["aether_nonces", state]` | domain-separated used-nonce keys (replay protection) |
| Instructions sysvar | native sysvar | fixed address | Ed25519 introspection source |

All three PDAs are singletons per deployment (one global state). The vault and
nonce tracker are derived from the state key, binding them to that state.

## Instruction set

| Instruction | Auth | Effect |
|---|---|---|
| `initialize(oracle, chain_id)` | admin (payer) | create state + vault + nonce tracker; pin oracle + chain_id + scheme_version |
| `claim_reward(action, amount, tenant_id, campaign_id, mint, nonce, expiry, sig)` | oracle proof | verify proof, transfer lamports vault→user, record nonce |
| `fund_vault(amount)` | permissionless | deposit SOL into the vault via system CPI |
| `update_oracle(new_oracle)` | admin | rotate oracle pubkey |
| `pause()` / `unpause()` | admin | toggle claim processing |
| `withdraw(amount)` | admin | move lamports vault→admin |

## Claim data flow

```
             off-chain                          on-chain (single transaction)
  ┌───────────────────────────┐        ┌──────────────────────────────────────┐
  │ oracle observes event      │        │  ix[0] Ed25519Program verify           │
  │ builds canonical message   │        │        (oracle_pubkey, message, sig)   │
  │  = aether_domain::         │        │                                        │
  │    build_claim_message(..) │        │  ix[1] aether_rewards::claim_reward     │
  │ signs with Ed25519 (KMS)   │──────► │    1 !paused                           │
  │ returns {sig, params}      │        │    2 action_len ok                     │
  └───────────────────────────┘        │    3 amount > 0                        │
                                        │    4 mint == NATIVE_SOL_MINT           │
  relayer assembles tx:                 │    5 now < expiry                      │
    [ed25519_ix, claim_ix]              │    6 nonce_key unused (domain-sep)     │
                                        │    7 reconstruct message; introspect   │
                                        │      ix[0] == expected                  │
                                        │    8 vault balance >= amount           │
                                        │    9 tracker not full                   │
                                        │   10 lamports vault -> user            │
                                        │   11 record nonce_key                  │
                                        │   12 update totals (checked)           │
                                        │   13 emit RewardClaimed                 │
                                        └──────────────────────────────────────┘
```

## Signature verification design

The program does **not** call `ed25519_verify` directly (SBF cannot). Instead the
transaction must include the native **Ed25519 precompile** instruction at index
0; the program loads it from the Instructions sysvar and checks that the
precompile validated the exact `(oracle_pubkey, message, signature)` triple.
Hardening: the precompile's `*_instruction_index` fields must be the
current-instruction sentinel `0xFFFF`, so the validated bytes are the same bytes
the program introspects (no cross-instruction substitution).

## Canonical message crate

`domain/` is a dependency-free crate that is the single source of truth for the
signed-message and nonce-record byte layouts. It is consumed by the program and
independently unit-tested (see `replay-isolation-proof.md`). Keeping it separate
means an auditor can review the exact byte layout without the Anchor/SBF stack.
