# 03 — Trust Assumptions

For the safety and correctness properties to hold, the following must be true.
Each is a place an auditor should probe.

## Cryptographic / platform

1. **Ed25519 is secure** and the Solana Ed25519 precompile correctly rejects
   invalid signatures. The program relies on the precompile having validated the
   signature; it only checks that the precompile instruction present in the tx
   references the exact `(oracle_pubkey, message, signature)` it reconstructs.
2. **SHA-256 (Solana `hash` syscall) is collision-resistant** — used to derive
   domain-separated nonce record keys.
3. **The Solana runtime** enforces PDA ownership, `init` uniqueness, lamport
   conservation, and the account constraints Anchor generates.
4. **Clock sysvar** is within acceptable skew — expiry enforcement depends on it.

## Program / deployment

5. **The deployed bytecode matches the audited source.** Enforced operationally
   by the reproducible build (`13`) and by controlling the upgrade authority
   (`04`). A malicious upgrade authority invalidates all guarantees.
6. **`declare_id!` matches the deploy keypair** (`anchor keys sync`), so the
   program id bound into proofs (`crate::ID`) equals the real deployment.
7. **`chain_id` is set correctly at init** to the intended cluster's Aether id.
   A wrong `chain_id` would still be internally consistent but would break the
   cross-chain isolation intent for that deployment.

## Governance / operational (the trusted humans)

8. **The oracle private key is confidential** (HSM/KMS). Its compromise allows
   minting arbitrary valid proofs up to the vault balance. This is the dominant
   trust assumption.
9. **The `admin` authority is honest/available.** `admin` can pause, rotate the
   oracle, and **withdraw the entire vault**. On testnet a single key is
   acceptable; on mainnet `admin` MUST be a multisig.
10. **The upgrade authority is honest and well-custodied** (multisig on mainnet).
11. **Vault funding is bounded** to expected outflow, capping the blast radius of
    an oracle-key compromise.

## Custody clarification (Aether "never custodies")

Aether's product principle is observation/coordination, not custody of user
assets. This program is consistent with that in that it **never holds
user-deposited funds** — the vault is an operator-funded *reward pool*. However,
the program *does* custody that pool, and `admin.withdraw` can move it. Reviewers
should treat the vault as operator funds under a trusted, centralized admin, not
as trustless escrow. The pre-mainnet roadmap (`10`) includes moving to a
non-custodial distribution model (e.g., a pre-committed Merkle distributor) to
align fully with the non-custody principle for real value.
