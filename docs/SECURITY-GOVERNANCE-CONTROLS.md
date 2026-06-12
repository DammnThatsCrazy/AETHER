---
title: Security, Governance & Enterprise Controls
slug: security/governance-controls
section: security
visibility: I
audience: [exec, buyer, ops, architect, security, compliance]
status: stable
since_version: "9.0.0"
source_files:
  - Backend Architecture/aether-backend/services/security/policy_engine.py
  - Backend Architecture/aether-backend/services/security/access_control.py
  - Backend Architecture/aether-backend/services/governance/routes.py
  - Backend Architecture/aether-backend/services/reliability/service.py
related:
  - compliance
  - reliability/operations
  - reliability/incident-response
canonical_owner: platform@aether
estimated_read_minutes: 6
last_synced_commit: 236aa4e
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

| Surface | Visibility |
|---|---|
| `/v1/security/*`, `/v1/status*` (Aether) | Tenant-safe, single-tenant, no infra internals |
| `/v1/admin/kyber/*` (Kyber) | Internal, operator/admin gated |

## Operator access model

**No Aether tenant may access Kyber for any reason.** The Kyber security routes
(`/v1/admin/kyber/security/*`) are gated fail-closed by `require_kyber_operator()`:
an operator is recognised only by the `kyber:operator` permission (checked against
the token's raw permission list, not `has_permission()`) or membership in the
`KYBER_OPERATOR_TENANT_IDS` allowlist — signals a normal tenant token never
carries. A tenant holding the legacy `admin` permission — even `Role.ADMIN` — is
denied. Reads require operator access; privileged mutations additionally require
the `admin` permission.

Olympus operators have scoped roles (`assigned_tenant` / `all_tenants_aggregate`
/ `all_tenants_admin`). Access to a specific tenant's private records requires an
assigned role or an approved, time-boxed **break-glass** grant. Break-glass
approval must come from a **different operator than the requester** (no
self-approval). Every break-glass grant and every access used under it is audited.

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

## Reliability integration with governance/audit

- **Incident audit trail** — every incident create/update is recorded via
  `IncidentAuditRepository` and logged (best-effort, never breaks the flow).
  This trail is internal only.
- **Security audit health** — the `security_audit` service and
  `rb_security_audit_event_failure` runbook (sev1) protect audit-event integrity
  and chain of custody during incidents.
- **Tenant-safe surfaces** — tenant System Status exposes only whitelisted,
  single-tenant fields; infrastructure internals, other tenants, and
  security-sensitive internals are never exposed. Enforced by no-leakage tests.

For the full compliance posture see [COMPLIANCE.md](COMPLIANCE.md).

## Known gaps (honest)

- No external certification/attestation is claimed or implied.
- Retention enforcement is declarative; automated retention sweeps are planned.
- Audit-ledger chaining is best-effort within the JSONB store; an external WORM
  sink is planned.
- Operator role provisioning/federation lives in the existing auth layer and is
  not unified into this control plane yet.
- Incident audit entries are stored in a dedicated internal table rather than the
  unified security audit ledger (planned).

## Rollout notes

- Additive: existing permission checks and approval flows are untouched.
- Routes are registered in `main.py`; UIs are new pages in `frontend/`.
- Backend tests: `tests/security/`. Frontend tests: Kyber + Aether security pages.
- Reliability controls are additive and do not change existing governance,
  auditability, or security guarantees. No external SLA/certification is claimed.
