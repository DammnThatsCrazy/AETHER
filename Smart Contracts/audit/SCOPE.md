# Audit Scope Manifest

## In scope (product contracts)

| Contract | Path | LOC (approx) | Notes |
|----------|------|--------------|-------|
| `AnalyticsRewards` | `contracts/AnalyticsRewards.sol` | ~570 | Core reward distribution, signature verification, campaigns, emergency controls |
| `RewardRegistry` | `contracts/RewardRegistry.sol` | ~440 | On-chain catalog of action types + campaigns; holds no funds |
| `IAnalyticsRewards` | `contracts/interfaces/IAnalyticsRewards.sol` | ~130 | External interface for `AnalyticsRewards` |

## In scope (deploy/verify tooling — operational security)

| File | Path | Notes |
|------|------|-------|
| Hardhat deploy | `scripts/deploy.js` | Fail-closed gates: audit, registry, default-key |
| Post-deploy verify | `scripts/post_deploy_verify.js` | On-chain invariant checks + registry enforcement |
| Gas estimation | `scripts/estimate_gas.js` | Deployment + runtime gas measurement |
| Shared gate libs | `scripts/lib/*.js` | networks, registry, audit_gate, default_keys, failure |
| Multi-chain deployer | `deploy/multichain_deployer.py` | EVM path enforces the same gates |
| EVM gate module | `deploy/evm_guards.py` | Python mirror of the JS gates |
| Legacy EVM deployer | `deploy/deployer.py` | Simulated deployer; gates applied |

## Out of scope

- `contracts/test/MockERC20.sol` — test-only ERC-20 mock, never deployed to production.
- `programs/**` — non-EVM (Solana/SUI/NEAR/Cosmos) programs, owned by a separate
  workstream and audited separately.
- The off-chain oracle **backend** (Python signer service) — not in this repo path
  and out of this package's boundary. Its signing scheme is documented in
  `EIP712_SIGNATURE_SPEC.md` as an integration checkpoint, but its source is not
  reviewed here.
- The ERC-20 **reward token** itself — assumed to be a standard, non-malicious,
  non-rebasing, non-fee-on-transfer token (see `TRUST_ASSUMPTIONS.md`).

## Commit / version pinning

> Fill these in at audit intake (do not run git from the agent environment):

- Repository: `AETHER`
- Package version: `@aether/smart-contracts` **8.7.1** (`Smart Contracts/package.json`)
- Audited commit: `<GIT_COMMIT_SHA>` — record the exact reviewed commit here and in
  `AUDIT_EVIDENCE.json → scope.commit`.
- Compiler: `solc 0.8.20` (see `DEPENDENCIES.md` / `REPRODUCIBLE_BUILD.md`).

## Deployed addresses under review

> None yet on mainnet (blocked by the audit gate). Testnet/staging addresses, once
> deployed, are recorded in `deploy/registry/contracts.json` per network and should
> be referenced here at audit time:

| Network | AnalyticsRewards | RewardRegistry |
|---------|------------------|----------------|
| _(testnet, TBD)_ | `<address>` | `<address>` |
