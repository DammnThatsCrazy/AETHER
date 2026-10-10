# 06 — Invariants

Invariants the program intends to uphold. An auditor should attempt to violate
each; the "Enforced by" column points at the mechanism.

## Value / accounting

- **I1 — No payout without a valid, current, unused, correctly-scoped proof.**
  Enforced by: pause check, expiry check, nonce check, Ed25519 introspection over
  the domain-separated message.
- **I2 — Exact amount.** The lamports credited to `user` equals the `amount` the
  oracle signed (bound into the message *and* used for the transfer). Enforced
  by: amount in signed message + single `amount` used for both check and debit.
- **I3 — Exact asset.** Only native SOL moves; `mint` must equal the native-SOL
  sentinel. Enforced by: `require!(mint == NATIVE_SOL_MINT)` and the vault being
  a plain SOL system account (no token CPI path exists).
- **I4 — Vault never underflows.** `vault.lamports >= amount` checked before the
  debit; `withdraw` has the same guard. Enforced by: explicit balance checks.
- **I5 — Totals never overflow.** `checked_add` on `total_distributed`,
  `total_claims`; `overflow-checks = true` in the release profile.
- **I6 — Conservation.** Every lamport leaving the vault is credited to exactly
  one recipient/admin in the same instruction (direct lamport moves sum to zero).

## Replay / domain isolation

- **I7 — Single-use nonce per domain.** A `nonce_key` can be recorded at most
  once; a second claim with the same domain+nonce reverts `NonceAlreadyUsed`.
- **I8 — No cross-domain replay.** A proof for domain A does not verify for
  domain B (chain/program/tenant/campaign/asset/amount/recipient all bound). See
  `replay-isolation-proof.md`. Enforced by: message reconstruction from on-chain
  + call data, then Ed25519 match.
- **I9 — Nonce record keys are domain-separated.** Same raw nonce, different
  domain → different stored key. Enforced by: `nonce_record_preimage` + SHA-256.

## Authorization / identity

- **I10 — Only admin performs admin actions.** Anchor `constraint` on
  update_oracle/pause/unpause/withdraw.
- **I11 — Only the current oracle can authorize.** Message verified against
  `state.oracle`; rotation invalidates old-oracle proofs immediately (I ⇒ old
  proofs fail).
- **I12 — PDA integrity.** state/vault/nonce are `seeds+bump` PDAs; a caller
  cannot substitute arbitrary accounts. Enforced by Anchor seed derivation.
- **I13 — Single initialization.** `init` on fixed-seed PDAs prevents re-init /
  seizure.

## Signature-verification integrity

- **I14 — The precompile validated the same bytes we check.** `num_signatures==1`
  and all `*_instruction_index == 0xFFFF` (current ix), so the precompile's
  validated `(pubkey,msg,sig)` are the exact bytes at the offsets we compare.
- **I15 — Verify ix is present and is the Ed25519 precompile at index 0.**
  Enforced by: `load_instruction_at_checked(0)` + program-id equality.

## Liveness / operational

- **I16 — Admin can always pause.** pause has no dependency on oracle/vault state.
- **I17 — Claims are blocked while paused.** first check in `claim_reward`.

## Invariants NOT currently guaranteed (see 10-known-limitations)

- Per-tenant / per-campaign **fund** isolation (single shared vault).
- Unbounded nonce capacity (tracker is capped at 1024 keys/account).
- Vault rent-exemption after large withdraw/claim (edge case).
- Admin key rotation without a program upgrade.
