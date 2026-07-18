# Cross-Domain / Cross-Program Replay-Isolation Proof

This document is the evidence for the requirement:

> A proof/claim cannot replay across chains, programs, tenants, campaigns,
> recipients, assets, or amounts (domain-separated nonce/seed binding).

It combines (a) a **runnable code proof** (the `aether-domain` crate + its unit
tests, executed in the authoring environment) and (b) the **on-chain
enforcement** in `programs/aether_rewards/src/lib.rs`, cross-checked by the
Anchor/TS integration tests.

## 1. The isolation mechanism

An Ed25519 signature authorizes exactly one *message*. If the message commits to
the full execution context, a signature produced for one context is not a valid
signature for any other context — the verifier reconstructs different bytes and
rejects.

The canonical message is defined once, in the dependency-free crate
`domain/src/lib.rs` (`build_claim_message`), and reconstructed byte-for-byte
on-chain. It binds **ten** fields:

```
DOMAIN_TAG(24) | VERSION(1) | program_id(32) | chain_id(8) | tenant_id(16)
  | campaign_id(16) | mint(32) | recipient(32) | amount(8)
  | action_len(4) | action(action_len) | nonce(32) | expiry(8)
```

Mapping to the required isolation dimensions:

| Dimension | Bound by | Effect |
|---|---|---|
| Chain / cluster | `chain_id` (pinned in `ProgramState` at init) | testnet proof ≠ mainnet proof |
| Program deployment | `program_id` (= `crate::ID`) | proof for deploy A ≠ deploy B |
| Tenant | `tenant_id` | tenant A's proof ≠ tenant B |
| Campaign | `campaign_id` | campaign X's proof ≠ campaign Y |
| Recipient | `recipient` (= claim `user`) | can't redirect payment |
| Asset | `mint` (enforced == native-SOL sentinel) | proof for asset A ≠ asset B |
| Amount | `amount` | can't inflate the payout |
| Action | `action_len`+`action` (length-prefixed) | unambiguous; no boundary aliasing |
| In-domain replay | `nonce` + on-chain record | each nonce usable once per domain |
| Time | `expiry` | proof self-expires |

### Defense-in-depth: domain-separated replay records

Even the *replay record key* is domain-separated. The program stores
`SHA-256(NONCE_TAG | program | chain | tenant | campaign | mint | nonce)`
(`nonce_record_preimage` + on-chain `hash(...)`). So the same raw nonce value in
two different domains produces two different records — cross-domain nonce reuse
can neither collide nor be replayed, independent of the signature check.

`DOMAIN_TAG` (`AETHER_REWARD_CLAIM_V1__`) and `NONCE_TAG`
(`AETHER_REWARD_NONCE_V1__`) are distinct 24-byte tags, so a message can never
equal a nonce preimage, and neither can collide with any other Aether signing
domain.

## 2. Runnable code proof (executed here)

`domain/src/lib.rs` carries executable unit tests, one per isolation dimension,
each asserting the message bytes differ across the boundary. These run with a
plain `cargo test` — **no Solana/Anchor toolchain required**.

Captured output from the authoring environment (`cargo test` in `domain/`):

```
running 14 tests
test tests::action_label_length_prefix_prevents_boundary_ambiguity ... ok
test tests::amount_tamper_isolation ... ok
test tests::cross_asset_isolation ... ok
test tests::cross_chain_isolation ... ok
test tests::cross_campaign_isolation ... ok
test tests::cross_program_isolation ... ok
test tests::cross_recipient_isolation ... ok
test tests::cross_tenant_isolation ... ok
test tests::empty_action_label_is_canonical ... ok
test tests::expiry_isolation ... ok
test tests::golden_vector_is_stable ... ok
test tests::message_length_matches_formula ... ok
test tests::nonce_record_preimage_is_domain_separated ... ok
test tests::nonce_isolation ... ok

test result: ok. 14 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
```

`cargo clippy --all-targets` on the crate: **no warnings**.

Reproduce:

```bash
cd "Smart Contracts/programs/solana/domain"
cargo test
cargo clippy --all-targets
```

## 3. On-chain enforcement (authored; needs toolchain to execute)

In `claim_reward`:

1. `mint.to_bytes() == NATIVE_SOL_MINT` is enforced (`UnsupportedAsset`).
2. `ClaimDomain { program_id: crate::ID, chain_id: state.chain_id, tenant_id,
   campaign_id, mint }` is assembled from on-chain + call data.
3. `nonce_record_preimage(&domain, &nonce)` is hashed to the record key and
   checked/inserted in the tracker.
4. `build_claim_message(&binding)` reconstructs the exact signed bytes; the
   Ed25519 precompile instruction is introspected and must match oracle pubkey,
   signature, and message.

Because the program uses the **same crate** as the proof to build the bytes, the
14 passing unit tests describe the exact bytes the program verifies.

## 4. End-to-end proof (Anchor/TS, needs a validator)

`tests/aether_rewards.ts` exercises the property on a real validator:

- `cross-domain isolation`: oracle signs for `(TENANT_A, CAMPAIGN_A)`, tx submits
  `(TENANT_B, CAMPAIGN_B)` → rejected `InvalidSignature`.
- `cross-amount isolation`: oracle signs amount `X`, tx submits `2X` → rejected
  `InvalidSignature`.
- `replay`: same nonce twice → second rejected `NonceAlreadyUsed`.
- `wrong oracle`, `expiry`, `pause`, `unauthorized admin`, `oracle rotation`.

Run (requires `anchor` + `solana-test-validator`):

```bash
cd "Smart Contracts/programs/solana"
anchor test
```

## 5. Residual note on cross-program/chain *fund* isolation

Message binding proves a *proof* cannot be replayed across programs/chains. It
does **not** by itself isolate *funds* across tenants/campaigns: today all
campaigns share one global `ProgramState`/vault/nonce-tracker. That is a
blast-radius property, not a replay property. The recommended pre-mainnet change
(per-campaign vault + per-nonce PDA) is documented in `10-known-limitations.md`.
