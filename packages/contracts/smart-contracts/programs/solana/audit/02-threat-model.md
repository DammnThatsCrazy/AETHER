# 02 — Threat Model

## Assets at risk

1. **Vault SOL** — the reward pool held by the vault PDA.
2. **Reward integrity** — that only oracle-authorized, unexpired, single-use,
   correctly-scoped claims pay out, at the exact amount/asset/recipient.
3. **Availability** — that legitimate claims can be processed and that the admin
   can pause under emergency.

## Trust boundary

Everything off-chain (oracle signing service, relayer, analytics pipeline) is
outside the chain's trust boundary. On-chain, the program trusts only: the
Ed25519 precompile, the Instructions sysvar, the Clock sysvar, and the PDAs it
derives. The oracle **key** is trusted to authorize payouts; compromise of that
key is the dominant risk (see below).

## Adversaries and attacks

| # | Adversary / attack | Mitigation | Residual risk |
|---|---|---|---|
| A1 | Replay a previously valid proof (same domain) | `nonce` recorded as domain-separated key; second use → `NonceAlreadyUsed` | Tracker capacity ceiling (see A9) |
| A2 | Replay a proof across chain / program / tenant / campaign / asset / amount / recipient | Domain-separated signed message; reconstructed on-chain; mismatch → `InvalidSignature` | None at proof level; fund-blast-radius is separate (L1) |
| A3 | Forge a proof (no oracle key) | Ed25519 verification via precompile + oracle pubkey match | Reduces to breaking Ed25519 |
| A4 | Wrong/old oracle after rotation | `state.oracle` compared to precompile pubkey | None |
| A5 | Submit an expired proof | `now < expiry` check | Depends on validator clock (bounded skew) |
| A6 | Ed25519 cross-instruction data substitution (point offsets at another ix) | `*_instruction_index` must be `0xFFFF` (this ix) | None |
| A7 | Ed25519 ix not present / not first | `load_instruction_at_checked(0)` + program-id check | Convention: verify ix must be index 0 |
| A8 | Inflate payout / change asset / redirect recipient | amount, mint, recipient all bound into signed message; mint also enforced == native sentinel | None |
| A9 | Nonce-tracker exhaustion / compute DoS (linear scan, single account) | Capacity guard (`NonceTrackerFull`); documented ceiling | **Real limitation** — see `10` (migrate to per-nonce PDA) |
| A10 | Drain vault via admin | Only `admin` (constraint); event emitted | **Centralization** — admin is trusted (L2); mainnet requires multisig |
| A11 | Vault underflow / arithmetic overflow | balance check before debit; `checked_add` on totals; `overflow-checks=true` in release | None known |
| A12 | Re-init / seize state | `init` on fixed-seed PDA fails if it already exists | None |
| A13 | Fake vault/state accounts | All are `seeds+bump` PDAs; Anchor enforces derivation | None |
| A14 | Griefing: reward account rent | reward is a lamport credit to a system account; recipient may be non-existent | Purely additive to recipient |
| A15 | Reorg double-processing | nonce record is on-chain state; a reorg that unwinds the record also unwinds the payout (atomic) | Standard chain finality assumptions |

## Oracle key compromise (dominant risk)

If the oracle private key leaks, an attacker can mint valid proofs and drain the
vault up to its balance. Mitigations: (a) hold the key in HSM/KMS; (b) keep the
vault balance bounded to expected outflow; (c) `pause()` on detection; (d)
`update_oracle()` to rotate; (e) monitor `RewardClaimed` events for anomalies.
This risk, not a chain bug, is the reason mainnet real-value is gated on audit +
operational controls.

## Out of scope for the program (but part of the system threat model)

- The oracle service's correctness and its key custody (off-chain).
- Sybil / eligibility logic (the program pays whatever the oracle signs).
- RPC / relayer censorship and MEV (does not affect payout correctness).
