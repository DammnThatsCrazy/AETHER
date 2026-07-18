# 04 — Privileged Roles & Authorities

| Role | Stored / located | Set by | Rotatable | Powers | Cannot |
|---|---|---|---|---|---|
| **Upgrade authority** | BPF loader (off-state) | deployer, then handed to governance | yes (`set-upgrade-authority`, or `--final` to freeze) | replace program bytecode | — (unbounded until frozen) |
| **`admin`** | `ProgramState.admin` | set to payer at `initialize` | not in current code (see limitation) | `pause`, `unpause`, `update_oracle`, `withdraw` | forge claims, sign proofs |
| **`oracle`** | `ProgramState.oracle` | `initialize`, rotated by `update_oracle` | yes (admin only) | authorize claims by signing the canonical message off-chain | change on-chain state directly, pause, withdraw |
| **`funder`** | tx signer of `fund_vault` | anyone | n/a | add SOL to the vault | withdraw, claim |
| **`user`/recipient** | claim account | bound in proof | n/a | receive the exact reward the oracle signed | choose amount/asset/nonce |
| **relayer/fee payer** | tx fee payer | anyone | n/a | submit the tx, pay fees | alter proof contents |

## Authority enforcement in code

- `admin` is enforced by an Anchor `constraint = admin.key() == program_state.admin`
  on `UpdateOracle`, `AdminAction` (pause/unpause), and `Withdraw`.
- `oracle` is enforced cryptographically: the reconstructed message is verified
  against `state.oracle` via the Ed25519 precompile introspection.
- `initialize` uses `init` on fixed-seed PDAs; it can run exactly once.

## Powers matrix (what each role can move)

| Action | upgrade auth | admin | oracle (key) | anyone |
|---|:--:|:--:|:--:|:--:|
| Replace code | ✅ | — | — | — |
| Pause / unpause | (via upgrade) | ✅ | — | — |
| Rotate oracle | (via upgrade) | ✅ | — | — |
| Withdraw vault | (via upgrade) | ✅ | — | — |
| Cause a payout | (via upgrade) | — | ✅ (sign proof) | — |
| Fund vault | — | — | — | ✅ |

## Custody / multisig requirements

- **Mainnet:** upgrade authority AND `admin` MUST be a multisig (e.g. Squads),
  ideally under separate custody. See `registry/upgrade-authority-policy.md`.
- **Testnet:** dedicated hot keys held in a secret manager are acceptable.
- **Oracle key:** HSM/KMS at all tiers; rotate on any suspicion.

## Known gap

There is **no `admin` handoff instruction** (e.g. `transfer_admin` with a
two-step accept). Admin is fixed to the initializer. Rotating admin currently
requires a program upgrade. Tracked in `10-known-limitations.md`.
