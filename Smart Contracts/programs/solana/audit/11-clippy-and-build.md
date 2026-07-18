# 11 — Clippy, Build & Captured Output

## Authoring-environment toolchain

```
cargo 1.94.1 (29ea6fb6a 2026-03-24)
rustc 1.94.1 (e408947bf 2026-03-25)
node  v22.22.2, yarn 1.22.22, npm 10.9.7
anchor: NOT INSTALLED
solana / solana-test-validator: NOT INSTALLED
```

Because `anchor`/`solana`/`cargo-build-sbf`/`solana-test-validator` are absent,
the **SBF build and on-validator TS tests could not be executed here** and are
authored + flagged. Everything that *could* run, did — captured below.

## A. Domain crate — executed here (offline, no toolchain)

```bash
cd "Smart Contracts/programs/solana/domain"
cargo test
cargo clippy --all-targets
cargo fmt --check
```

Result:

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

cargo clippy: Finished, 0 warnings
cargo fmt --check: clean
```

## B. Anchor program — type-check + clippy executed here (host target)

The host toolchain **did** resolve Anchor 0.30.1 / solana-program 1.18.26 and
type-check the program:

```bash
cd "Smart Contracts/programs/solana"
cargo check  -p aether-rewards
cargo clippy -p aether-rewards
```

Result:

```
cargo check  -> Finished `dev` profile (0 errors, exit 0)
cargo clippy -> Finished `dev` profile (0 errors, exit 0)
warnings: 17, ALL benign macro/host-target cfg warnings:
  - unexpected `cfg` condition value: `anchor-debug`  (Anchor #[derive(Accounts)])
  - unexpected `cfg` condition value: `custom-heap` / `custom-panic` / `solana`
    (Solana entrypoint macros; defined only under cargo build-sbf)
0 `clippy::` lints originate from program code.
```

Note on process: an initial `cargo check` surfaced 7 real errors, all from a
single root cause — the original beta `declare_id!` placeholder decoded to 33
bytes (not 32), so `declare_id!` failed and `crate::ID` was never generated
(6 cascading `cannot find value ID`). Fixed by using a valid 32-byte base58
placeholder id; re-check is clean. This is exactly the kind of issue the
type-check is meant to catch and is recorded here for transparency.

## C. Required before release — must run under the Solana toolchain

```bash
rustup toolchain install 1.79.0    # match the Solana 1.18.x platform tools
solana-install init 1.18.26
avm install 0.30.1 && avm use 0.30.1

cd "Smart Contracts/programs/solana"
anchor build                       # SBF build + IDL
cargo clippy -p aether-rewards --target sbf-solana-solana -- -D warnings  # (via build-sbf)
anchor test                        # TS integration on a local validator
```

Recommended CI clippy gate (once the toolchain is wired):

```bash
cargo clippy --workspace --all-targets -- -D warnings
```
