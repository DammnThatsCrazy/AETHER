---
title: "SVM (Solana) Deploy & Emergency Runbook"
slug: runbooks/svm-deploy-emergency
section: operations
visibility: I
audience: [ops, dev-senior, security]
status: stable
since_version: "8.12.0"
source_files:
  - Smart Contracts/programs/solana/audit/08-deployment-procedure.md
  - Smart Contracts/programs/solana/audit/09-pause-rotation-procedure.md
  - Smart Contracts/programs/solana/registry/upgrade-authority-policy.md
canonical_owner: platform@aether
last_synced_commit: "845b1c14"
---

# SVM (Solana) Deploy & Emergency Runbook

Operational entry point for the Solana reward program. It points to the audit
package rather than restating it. Authoritative references:

- Deployment procedure: `Smart Contracts/programs/solana/audit/08-deployment-procedure.md`
- Pause / rotation / incident procedure: `Smart Contracts/programs/solana/audit/09-pause-rotation-procedure.md`
- Upgrade-authority policy: `Smart Contracts/programs/solana/registry/upgrade-authority-policy.md`
- Threat model / privileged roles: `audit/02-threat-model.md`, `audit/04-privileged-roles.md`
- Deploy scripts: `programs/solana/migrations/deploy.ts`,
  `programs/solana/scripts/deploy_testnet.sh`, `scripts/smoke_test.sh`

## Mainnet gate (do not skip)

As with EVM, mainnet deployment is BLOCKED pending external audit. See
`EXTERNAL_AUDIT_PREPARATION_GUIDE`. Localnet/testnet follow
`audit/08-deployment-procedure.md`.

## Deploy (localnet / testnet)

1. `scripts/deploy_localnet.sh` or `scripts/deploy_testnet.sh`, then
   `migrations/deploy.ts` and `register_program.ts`.
2. Run `scripts/smoke_test.sh` and confirm the program id + upgrade authority
   match `registry/upgrade-authority-policy.md`.

## Emergency: pause & rotation

Follow `audit/09-pause-rotation-procedure.md` exactly. Key points:

- The program supports an admin pause; a paused program rejects claim
  instructions while leaving state readable.
- Oracle/authority rotation follows the upgrade-authority policy — never rotate
  to a key outside the registry.
- Replay isolation is proven in `audit/replay-isolation-proof.md`; do not
  weaken the nonce/PDA checks to expedite an incident.

## Never do

- Never deploy to mainnet-beta before the external audit clears the gate.
- Never change the upgrade authority outside `upgrade-authority-policy.md`.
- Never bypass the pause to "just process one claim" during an incident.

See also: `docs/runbooks/EVM_DEPLOY_EMERGENCY_RUNBOOK.md`,
`docs/productization/staging-capstone/EXTERNAL_AUDIT_PREPARATION_GUIDE.md`.
