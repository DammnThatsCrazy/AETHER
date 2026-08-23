# Deployment Guards Summary

Every guard below is **fail-closed**: a violation aborts the deployment/activation
before any real-value path can proceed. Mainnet-class is defined as anything that
is not explicitly local or a known testnet (unknown names are treated as mainnet).

## Smart-contract deploy-time gates

| Gate | Enforced by | Behavior |
|------|-------------|----------|
| **Mainnet external-audit gate** | `scripts/lib/audit_gate.js` (`assertAuditEvidence`) and `deploy/evm_guards.py` (`assert_audit_evidence`) | Mainnet-class deploy fails unless `audit/AUDIT_EVIDENCE.json` exists, is valid JSON, and `validateEvidence` passes: `auditor.name` set; `report.sha256` is 64-hex **and** matches `report.file` on disk when present; `report.file` set; `scope.commit` set; `scope.contracts` non-empty; `signoff.approved === true`; `signoff.approver` set. Testnets/local unaffected. |
| **Default-key rejection** | `scripts/lib/default_keys.js` and `deploy/evm_guards.py` (`assert_not_default_key`) | Any well-known Hardhat/Anvil private key is refused on non-local networks. |
| **Oracle-signer registry** | `deploy/evm_guards.py` (`assert_oracle_registered`) + `scripts/lib/registry.js` | `ORACLE_ADDRESS` must be allow-listed per network in `deploy/registry/oracle_signers.json`. |
| **Contract registry (post-deploy)** | `scripts/post_deploy_verify.js` | Re-checks on-chain invariants after deployment. |

## Backend reward-activation gate (on-chain claim proofs)

| Gate | Enforced by | Behavior |
|------|-------------|----------|
| **EVM mainnet audit gate** | `services/rewards/onchain_gate.py` (`assert_mainnet_audit_evidence`), wired in `services/rewards/routes.py` `/evaluate` | For an EVM **mainnet** `onchain_claim` reward, activation fails closed (403) unless a non-revoked `reward_external_audit_evidence` row exists for the exact `(tenant_id, chain_id, contract_address)`. Local/testnet unaffected. Evidence is recorded via `POST /v1/rewards/audit-evidence` and can be revoked to re-gate. |
| **Contract registry gate** | `ContractRegistryRepository.find_for_proof` (backend) | Proof generation requires the contract to be operator-verified in the tenant's registry (prevents a tenant registering an arbitrary contract and obtaining proofs for it). |

## What records the audit evidence (the honest path)

Evidence is **recorded by a human** only after a real external audit completes:

1. Auditor completes the review against `audit/CODE_REVIEW_CHECKLIST.md`.
2. Report + `AUDIT_EVIDENCE.json` (from `AUDIT_EVIDENCE.template.json`, with
   `signoff.approved: true` and the report SHA-256) are added under
   `Smart Contracts/audit/` — a **reviewed change**.
3. Backend operators additionally record the evidence row for each
   `(tenant, chain_id, contract_address)` via `POST /v1/rewards/audit-evidence`
   before mainnet on-chain rewards activate.

**Nothing auto-fabricates either artifact.** The template keeps
`signoff.approved: false`, and `AUDIT_EVIDENCE.json` does not exist in the
repository until a real audit sign-off.

## Re-gating

- Revoking a backend evidence row (`POST /v1/rewards/audit-evidence/{id}/revoke`)
  re-blocks mainnet activation for that contract immediately.
- Deleting/invalidating `AUDIT_EVIDENCE.json` re-blocks mainnet-class deploys
  immediately.
