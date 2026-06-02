---
title: Security & Governance Controls
slug: enterprise/security-governance-controls
section: enterprise
visibility: I
audience: [exec, buyer, ops, security]
status: stable
since_version: "13.0.0"
---

# Security, Compliance & Governance Controls

Aether/Kyber ships a **governance control plane** that lets enterprise and
government buyers run a security review against demonstrable controls. It answers:

- who accessed what
- who approved what
- what policy allowed or blocked an action
- what tenant data was exported
- whether tenant isolation is being enforced
- how operator access is controlled
- how data retention is configured
- what evidence exists for security review

> **Not certified.** These are *security-review evidence* primitives. Aether does
> **not** claim SOC 2, ISO 27001, FedRAMP, or any other certification through this
> control plane. Statements here describe implemented software behavior only.

## Components

| Control | Doc | Status |
|---|---|---|
| Access control (role → permission → scope) | [ACCESS-CONTROL.md](./ACCESS-CONTROL.md) | Implemented |
| Policy engine (allow/block decisions) | [POLICY-ENGINE.md](./POLICY-ENGINE.md) | Implemented |
| Security audit ledger (tamper-evident) | [AUDIT-EVENT-LEDGER.md](./AUDIT-EVENT-LEDGER.md) | Implemented |
| Tenant isolation verifier | [TENANT-ISOLATION-VERIFICATION.md](./TENANT-ISOLATION-VERIFICATION.md) | Implemented |
| Break-glass operator access | [BREAK-GLASS-ACCESS.md](./BREAK-GLASS-ACCESS.md) | Implemented |
| Data retention + data requests | [DATA-RETENTION.md](./DATA-RETENTION.md) | Implemented |
| Audit export governance | [AUDIT-EXPORTS.md](./AUDIT-EXPORTS.md) | Implemented |
| Integration security | [INTEGRATION-SECURITY.md](./INTEGRATION-SECURITY.md) | Implemented |
| Governance evidence packs | [GOVERNANCE-EVIDENCE-PACKS.md](./GOVERNANCE-EVIDENCE-PACKS.md) | Implemented |

## Architecture

The control plane lives in `services/security/` (backend) and is additive: it
**wraps**, never removes, existing `require_permission(...)` checks and OODA
approval flows. Shared contracts are in `packages/shared/security-governance.ts`
and `services/security/contracts.py`.

```
Request → existing auth/tenant context
        → AccessControlService.require_access()  (role/scope eval + audit)
        → PolicyEngine.check_*()                 (allow/block + audit)
        → SecurityAuditEvent ledger              (tamper-evident record)
```

## Tenant vs Kyber visibility

- **Tenant (`/v1/security/...`)** — a tenant sees **only its own** permissions,
  audit events, policy decisions, retention policies, and data requests. No
  cross-tenant data and **no Olympus operator internals** are exposed.
- **Kyber (`/v1/admin/kyber/security/...`)** — operators see aggregates,
  governed records, the isolation verifier, operator-access model, and evidence
  packs. Kyber views are **aggregate-only** by construction.

## Operator access model

Olympus operators have scoped roles (`assigned_tenant` / `all_tenants_aggregate`
/ `all_tenants_admin`). Access to a specific tenant's private records requires an
assigned role or an approved, time-boxed **break-glass** grant. Every break-glass
grant and every access used under it is audited.

## Policy enforcement model

`PolicyEngine` returns a `PolicyDecision` (allowed / reason / severity) and writes
a `SecurityAuditEvent` for sensitive policy keys. It enforces, e.g.: dispatch
requires an approved decision; elevated/critical dispatch requires an
`approval_id`; cross-tenant access is blocked; audit export requires permission;
disabled or unsafe integration dispatch is blocked; audit logs cannot be deleted.

## Audit event model

Every sensitive action produces a `SecurityAuditEvent` with an `integrity_hash`
chained to the previous event for the same tenant, so deletion/reordering is
detectable. Audit metadata is sanitized — secrets never reach the ledger.

## Data retention model

Per-resource `DataRetentionPolicy` records define `retention_days` and a
`delete_behavior` (`hard_delete` / `soft_delete` / `anonymize` /
`preserve_audit_stub`). Audit logs are never hard-deleted; billing records are
preserved; deletions require a manifest and are processed as structured,
audited `DataRequest` records.

## Evidence pack purpose

`GovernanceEvidencePack`s bundle, per control area, a control summary, relevant
policies, audit-event summaries, verifier results, and **explicit known gaps**.
They are evidence for a security reviewer — not a certification artifact.

## Known gaps (honest)

- No external certification/attestation is claimed or implied.
- Retention enforcement is declarative; automated retention sweeps are planned.
- Audit-ledger chaining is best-effort within the JSONB store; an external WORM
  sink is planned.
- Operator role provisioning/federation lives in the existing auth layer and is
  not unified into this control plane yet.

## Rollout notes

- Additive: existing permission checks and approval flows are untouched.
- Routes are registered in `main.py`; UIs are new pages in `apps`/`frontend`.
- Backend tests: `tests/security/`. Frontend tests: Kyber + Aether security pages.
