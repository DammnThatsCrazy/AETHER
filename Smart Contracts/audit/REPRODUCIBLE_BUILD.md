# Reproducible Build & Analysis

Goal: an auditor can reproduce byte-for-byte the compiled artifacts and re-run the
full test + static-analysis pipeline from a clean checkout.

## 1. Pin the inputs

- Source commit: `<GIT_COMMIT_SHA>` (record in `SCOPE.md` and `AUDIT_EVIDENCE.json`).
- Compiler: `solc 0.8.20` (exact: `0.8.20+commit.a1b79de6`).
- Compiler settings (from `hardhat.config.js`, do not change):
  ```
  optimizer: { enabled: true, runs: 200 }
  viaIR:     true
  version:   0.8.20
  ```
- Dependencies: install from the lockfile (see `DEPENDENCIES.md`).

## 2. Clean, deterministic build

```bash
cd "Smart Contracts"
npm ci                       # install exact versions from package-lock.json
npx hardhat clean            # remove any cached artifacts
npx hardhat compile          # deterministic given the pinned solc + settings
```

Artifacts land in `artifacts/` and `artifacts/build-info/` (the build-info JSON
contains the full standard-json input + solc version — this is what Slither and
`hardhat verify` consume, and what to diff for reproducibility).

## 3. Reproduce the tests

```bash
npx hardhat test             # expect: 39 passing
```

## 4. Reproduce the static analysis

```bash
pip install slither-analyzer solc-select
solc-select install 0.8.20 && solc-select use 0.8.20
slither . \
  --solc-remaps "@openzeppelin=node_modules/@openzeppelin" \
  --filter-paths "node_modules|contracts/test"
# compare against audit/slither-output.txt
```

## 5. Reproduce gas figures

```bash
npx hardhat run scripts/estimate_gas.js      # in-process network
```

## 6. Source verification on explorers

`scripts/deploy.js` prints the exact `npx hardhat verify` commands with the
constructor arguments. Because the compiler version + settings are pinned, the
on-chain bytecode matches the local build and Etherscan-style verification
succeeds. Constructor args:

- `RewardRegistry(admin)`
- `AnalyticsRewards(rewardToken, admin, oracle)`

## Determinism notes

- No timestamps, block numbers, or randomness enter the compiled bytecode.
- `viaIR: true` — ensure the same solc patch version is used; IR codegen can differ
  across patch releases, so pin `0.8.20+commit.a1b79de6` exactly.
- Metadata hash: solc embeds a metadata (IPFS) hash by default; for bit-identical
  bytecode across machines, either compare the `build-info` standard-json input or
  set `settings.metadata.bytecodeHash = "none"` consistently on both sides. This is
  not currently set, so verify via the build-info input rather than raw bytecode
  equality if reproducing on a different machine.
