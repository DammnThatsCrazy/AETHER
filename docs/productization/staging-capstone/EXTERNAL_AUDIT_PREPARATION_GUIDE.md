---
title: "External Audit Preparation Guide"
slug: productization/staging-capstone/external-audit-preparation-guide
section: operations
visibility: I
audience: [security, architect, exec]
status: stable
since_version: "8.12.0"
source_files:
  - Smart Contracts/audit/README.md
  - Smart Contracts/programs/solana/audit/README.md
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 2
---

# External Audit Preparation Guide

Getting the smart-contract rails ready for an external security audit. This is a
pointer + checklist — the audit PACKAGES already exist and are authoritative; do
not duplicate them here.

## The audit packages (authoritative)

- **EVM:** `Smart Contracts/audit/` — `README.md`, `SCOPE.md`, `ARCHITECTURE.md`,
  `THREAT_MODEL.md`, `TRUST_ASSUMPTIONS.md`, `STATE_TRANSITIONS.md`,
  `INVARIANTS.md`, `TEST_PLAN.md`, `EIP712_SIGNATURE_SPEC.md`, `DEPLOYMENT.md`,
  `SLITHER.md` (+ `slither-output.txt`), `KNOWN_LIMITATIONS.md`,
  `DEPENDENCIES.md`, `REPRODUCIBLE_BUILD.md`, `AUDIT_FINDING_TEMPLATE.md`.
- **SVM (Solana):** `Smart Contracts/programs/solana/audit/` — architecture,
  threat model, trust assumptions, privileged roles, state transitions,
  invariants, test commands, deployment, pause/rotation, known limitations,
  clippy/build, dependency inventory, reproducible build, scope manifest,
  finding template, `replay-isolation-proof.md`.

## Readiness checklist (before engaging an auditor)

1. **Scope frozen.** Confirm `SCOPE.md` / `14-scope-manifest.md` match the
   deployed contract/program set; no in-flight refactors.
2. **Static analysis clean or triaged.** Slither (`make` smart-contract analysis
   CI) and clippy runs recorded; every finding either fixed or documented in
   `KNOWN_LIMITATIONS.md` / `10-known-limitations.md`.
3. **Invariants + state transitions documented** and matched by the test plan.
4. **Reproducible build** verified from the documented toolchain.
5. **Threat model + trust assumptions + privileged roles** current, including
   the oracle-signer and upgrade-authority policies.
6. **`make audit-prep`** run; output attached to the engagement.

## Gate

Mainnet deployment with real funds is BLOCKED until the external audit is
complete and remediation is merged. The reward on-chain flag
(`EVM_REWARD_PROOFS_ENABLED`) and any mainnet deploy stay gated regardless of
code completeness. This is a `release-blocker` in the scorecard and stays open
until an audit report is committed.

## Auditor candidates

Trail of Bits / OpenZeppelin / Spearbit / Halborn (per the scorecard blocker).

## Never do

- Never deploy to mainnet before the audit clears the gate.
- Never edit the audit packages to hide a limitation — document it.

See also: `docs/runbooks/EVM_DEPLOY_EMERGENCY_RUNBOOK.md`,
`docs/runbooks/SVM_DEPLOY_EMERGENCY_RUNBOOK.md`.
