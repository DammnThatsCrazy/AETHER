# Aether AnalyticsRewards — External Audit Package

This directory is the self-contained package handed to an external smart-contract
auditor for the Aether EVM reward flow. It documents the system, its trust
boundaries, its invariants, and how to reproduce the build and the analysis.

## System in one paragraph

`AnalyticsRewards` distributes ERC-20 reward tokens for verified analytics
actions. Aether **never custodies user funds and never submits claims** — an
off-chain oracle (an `ORACLE_ROLE` holder) signs a per-claim payload, and the
tenant/user (or their relayer) submits it on-chain. The contract verifies the
oracle signature, enforces a per-claim nonce (replay protection) and expiry,
checks the campaign's on-chain budget and per-user cap, then transfers tokens.
`RewardRegistry` is an auxiliary on-chain catalog of action types and campaigns
read by the off-chain oracle; it holds no funds.

## Contents

| File | What it covers |
|------|----------------|
| `SCOPE.md` | Exact in-scope / out-of-scope files, commit, and contract addresses |
| `ARCHITECTURE.md` | Components, actors, data flow, on-chain/off-chain split |
| `THREAT_MODEL.md` | Assets, adversaries, attack surface, mitigations, residual risk |
| `TRUST_ASSUMPTIONS.md` | Privileged roles, what each can/can't do, trust boundaries |
| `STATE_TRANSITIONS.md` | Contract/campaign/oracle state machines and transitions |
| `INVARIANTS.md` | Properties that must always hold (with enforcement points) |
| `EIP712_SIGNATURE_SPEC.md` | Signature scheme (EIP-191 today), domain separation, EIP-712 upgrade path |
| `TEST_PLAN.md` | Test inventory + exact commands to run the suite |
| `DEPLOYMENT.md` | Deploy/verify procedure, gates, pause & oracle-rotation runbooks |
| `KNOWN_LIMITATIONS.md` | Accepted limitations and design trade-offs |
| `SLITHER.md` | How to run Slither + interpretation of findings |
| `slither-output.txt` | Captured Slither run output |
| `DEPENDENCIES.md` | Pinned toolchain + library inventory |
| `REPRODUCIBLE_BUILD.md` | Deterministic build + how to reproduce analysis |
| `AUDIT_FINDING_TEMPLATE.md` | Issue template for reporting findings |
| `AUDIT_EVIDENCE.template.json` | Shape of the sign-off file that unblocks mainnet |

## Mainnet is gated on this package

Real-value (mainnet-class) deployment is **blocked in code** until a completed
audit sign-off is recorded at `audit/AUDIT_EVIDENCE.json` (see
`AUDIT_EVIDENCE.template.json` for the required shape). Testnets and local
networks are unaffected. The gate is enforced by both `scripts/deploy.js` and
`deploy/multichain_deployer.py`. This file being present is **not** sufficient —
only a valid `AUDIT_EVIDENCE.json` with `signoff.approved: true` opens the gate.

## Status of this package

Authored for staging/testnet readiness and audit intake. The contract compiles
(`solc 0.8.20`), the full Hardhat suite passes (39/39), and Slither runs clean of
high/critical findings (see `SLITHER.md`). No external audit has been performed
yet; `AUDIT_EVIDENCE.json` intentionally does not exist, so mainnet stays blocked.
