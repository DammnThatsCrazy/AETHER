# Aether Rewards (Solana) — External Audit Package

This directory is the complete, self-contained package for an external security
audit of the Aether Rewards Anchor program.

- **Program:** `aether_rewards` (Anchor / Rust, SBF)
- **Canonical source in scope:** `programs/aether_rewards/src/lib.rs` and the
  dependency-free `domain/src/lib.rs`.
- **Version:** `0.2.0` (hardened from the `0.1.x` beta snapshot retained at
  `../aether_rewards.rs` for diffing).
- **Maturity target of this package:** staging / testnet readiness + audit prep.
- **Mainnet real-value status:** **BLOCKED** until recorded external-audit
  evidence exists (see `10-known-limitations.md`).

## What the program does

Distributes native-SOL rewards from a program-owned vault to users who present a
reward proof signed by an off-chain oracle (Ed25519). Verification is done fully
on-chain via the Ed25519 precompile and instruction introspection. The program
is observation/coordination-oriented: it holds a *reward pool*, not user assets.
See `03-trust-assumptions.md` for the custody nuance.

## Contents

| File | Purpose |
|---|---|
| `01-architecture.md` | System + on-chain architecture, accounts, data flow |
| `02-threat-model.md` | Assets, adversaries, attack surface, mitigations |
| `03-trust-assumptions.md` | What must be trusted for safety to hold |
| `04-privileged-roles.md` | admin / upgrade authority / oracle powers |
| `05-state-transitions.md` | Per-instruction pre/post states + diagrams |
| `06-invariants.md` | Invariants an auditor should try to break |
| `07-test-commands.md` | Exact commands: Rust, TS, validator, clippy |
| `08-deployment-procedure.md` | Localnet + testnet deploy, mainnet gate |
| `09-pause-rotation-procedure.md` | Emergency pause + oracle/authority rotation |
| `10-known-limitations.md` | Known issues, scalability ceilings, blockers |
| `11-clippy-and-build.md` | Lint/build instructions + captured output |
| `12-dependency-inventory.md` | Dependency + toolchain inventory |
| `13-reproducible-build.md` | Pinned, reproducible build instructions |
| `14-scope-manifest.md` | Exact files in/out of audit scope + hashes |
| `15-audit-finding-template.md` | Issue template for reported findings |
| `replay-isolation-proof.md` | Cross-domain replay-isolation proof (code+test) |

## Authoring-environment note (important for reproducing results)

This package was authored in an environment with **`cargo`/`rustc` 1.94.1
available but `anchor`, `solana`, and `solana-test-validator` NOT installed**.
Consequently:

- The dependency-free `aether-domain` crate **was compiled and unit-tested here**
  (`cargo test` — 14/14 passing; `cargo clippy` — clean). See
  `11-clippy-and-build.md` and `replay-isolation-proof.md` for captured output.
- The Anchor program build (`anchor build` / `cargo build-sbf`) and the TS
  integration tests (which need a local validator) are **authored but not
  executed here**; they require the Solana/Anchor toolchain. Every such gap is
  flagged explicitly, never faked.
