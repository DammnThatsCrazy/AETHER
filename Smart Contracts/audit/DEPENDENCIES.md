# Dependency Inventory

Versions captured from this environment's lockfile / installed modules. Pin these
for a reproducible audit (see `REPRODUCIBLE_BUILD.md`).

## Solidity / contracts

| Dependency | Version | Source | Used for |
|------------|---------|--------|----------|
| Solidity compiler | `solc 0.8.20+commit.a1b79de6` | hardhat-managed (`hardhat.config.js → solidity.version`) | Compilation; also installable via `solc-select` for Slither |
| `@openzeppelin/contracts` | **5.6.1** (declared `^5.0.0` in `package.json`) | npm | `AccessControl`, `Pausable`, `ReentrancyGuard`, `IERC20`, `SafeERC20`, `ERC20` (mock) |

### OpenZeppelin modules imported

```
@openzeppelin/contracts/access/AccessControl.sol
@openzeppelin/contracts/utils/Pausable.sol
@openzeppelin/contracts/utils/ReentrancyGuard.sol
@openzeppelin/contracts/token/ERC20/IERC20.sol
@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol
@openzeppelin/contracts/token/ERC20/ERC20.sol          (test mock only)
```

> Note: OZ v5 requires Solidity ≥ 0.8.20, which matches the pinned compiler.

## JavaScript toolchain

| Dependency | Version | Notes |
|------------|---------|-------|
| Node.js | `v22.22.2` | Runtime for Hardhat/ethers |
| Hardhat | **2.28.6** (declared `^2.22.0`) | Compile/test/deploy framework |
| `@nomicfoundation/hardhat-toolbox` | **4.0.0** | Bundles ethers, chai matchers, network-helpers, gas reporter, verify |
| ethers | **6.16.0** | Used by scripts and tests (v6 API) |

Compiler settings (`hardhat.config.js`): optimizer **enabled, 200 runs**,
**viaIR: true**, evm target resolved to `paris`.

## Python toolchain (deploy tooling + static analysis)

| Dependency | Version | Notes |
|------------|---------|-------|
| Python | `3.11.15` | Runs `deploy/*.py` and Slither |
| `slither-analyzer` | **0.11.5** | Static analysis (see `SLITHER.md`) |
| `solc-select` | current | Provides `solc 0.8.20` binary for Slither |
| `python-dotenv` | (optional) | Env loading for deployers, per file headers |
| `web3` | (optional) | Only for the live path in `deploy/deployer.py` |

## Supply-chain notes for the auditor

- Exact transitive versions are pinned in `Smart Contracts/package-lock.json`; use
  `npm ci` (not `npm install`) to install from the lockfile.
- No external network calls are made by the contracts. Deploy scripts read RPC URLs
  and keys from environment/secret references only.
- Registries under `deploy/registry/` contain **public addresses only** — never keys.
