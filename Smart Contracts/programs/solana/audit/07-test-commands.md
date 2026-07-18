# 07 — Test Commands

## A. Domain-separation crate (runs anywhere; no Solana/Anchor toolchain)

```bash
cd "Smart Contracts/programs/solana/domain"
cargo test            # 14 unit tests: replay-isolation across all dimensions
cargo clippy --all-targets
cargo fmt --check
```

Captured result in the authoring environment (rustc/cargo 1.94.1):

```
running 14 tests ... test result: ok. 14 passed; 0 failed
cargo clippy: 0 warnings
```

This is the executable replay-isolation proof (see `replay-isolation-proof.md`).

## B. Program type-check + lint (host toolchain; no validator)

```bash
cd "Smart Contracts/programs/solana"
cargo check  -p aether-rewards
cargo clippy -p aether-rewards
```

Captured result (Anchor 0.30.1 / solana-program 1.18.26 resolved on host):

```
cargo check  -> Finished (0 errors)   # 17 warnings, all benign Anchor/Solana
cargo clippy -> Finished (0 errors)   # macro cfg warnings (anchor-debug,
                                      # custom-heap, custom-panic, solana) that
                                      # disappear under `cargo build-sbf`.
                                      # 0 `clippy::` lints from program code.
```

## C. Full SBF build + Anchor/TS integration tests (needs toolchain + validator)

Prerequisites (NOT present in the authoring environment):
`solana` CLI, `anchor` CLI, `cargo-build-sbf`, `solana-test-validator`, `yarn`.

```bash
cd "Smart Contracts/programs/solana"
yarn install
anchor build                     # SBF build + IDL generation
anchor test                      # boots solana-test-validator, runs tests/*.ts
# or, against an already-running validator:
solana-test-validator --reset &
anchor test --skip-local-validator
```

`tests/aether_rewards.ts` asserts:

| Test | Proves |
|---|---|
| initializes program state | init sets oracle/chain_id/scheme_version |
| funds the vault | fund_vault works |
| valid claim + exact atomic amount | I1, I2, I3 (recipient gets exactly `amount` lamports) |
| rejects wrong asset | UnsupportedAsset (I3) |
| rejects replay | NonceAlreadyUsed (I7) |
| rejects wrong oracle | InvalidSignature (I11) |
| enforces expiry | ExpiredProof |
| cross-domain isolation | tenant/campaign mismatch → InvalidSignature (I8) |
| cross-amount isolation | tampered amount → InvalidSignature (I2/I8) |
| pause blocks / unpause restores | I16, I17 |
| unauthorized admin rejected | I10 |
| oracle rotation | I11 (new works, old fails) |
| PDA state isolation | I12 |

## D. Verify a deployment (read-only)

```bash
yarn registry:verify --cluster testnet         # decodes state PDA, checks chain_id
bash scripts/smoke_test.sh testnet
```
