# 13 — Reproducible Build

Goal: anyone can rebuild the exact on-chain bytecode from this source and verify
it matches what is deployed.

## Pinned inputs

- Anchor CLI `0.30.1`
- Solana platform tools `1.18.26` (provides the SBF rustc, ~`1.79.0`)
- `anchor-lang = "=0.30.1"` (exact pin in `Cargo.toml`)
- Committed `Cargo.lock` (workspace root)

## Deterministic build (recommended: Anchor verifiable build in Docker)

```bash
cd "Smart Contracts/programs/solana"

# Option 1 -- Anchor's verifiable, containerized build (most reproducible):
anchor build --verifiable
#   builds inside the pinned backpack/anchor docker image, producing a
#   deterministic target/verifiable/aether_rewards.so

# Option 2 -- local pinned toolchain:
solana-install init 1.18.26
avm use 0.30.1
anchor build
```

## Verify against a deployed program

```bash
# hash of the freshly built artifact
sha256sum target/verifiable/aether_rewards.so     # or target/deploy/aether_rewards.so

# dump the on-chain program and hash it
solana program dump <PROGRAM_ID> onchain.so --url "$RPC"
sha256sum onchain.so

# the two hashes MUST match; record the value in program-registry.json (idl_sha256
# / add a program_sha256 field) at release time.
```

Optionally publish an on-chain verifiable build attestation:

```bash
anchor verify -p aether_rewards <PROGRAM_ID> --provider.cluster "$RPC"
```

## Lockfile provenance (important)

The `Cargo.lock` committed here was resolved on the authoring **host** toolchain
(rustc 1.94.1) because the Solana toolchain was unavailable. Before release:

1. Install the pinned Solana/Anchor toolchain.
2. `rm Cargo.lock && anchor build` (regenerates the lock under the SBF toolchain).
3. Diff the regenerated lock; if versions move, investigate before committing.
4. Commit the toolchain-resolved lock as the canonical one.

## Determinism checklist

- [ ] Build in the pinned container (`--verifiable`) or pinned local toolchain.
- [ ] `Cargo.lock` present and toolchain-resolved.
- [ ] `overflow-checks = true` in release profile (set in workspace `Cargo.toml`).
- [ ] `lto = "fat"`, `codegen-units = 1` (set) for stable output.
- [ ] Record `program_sha256` + IDL hash in the registry at release.
- [ ] On-chain dump hash == local build hash.
