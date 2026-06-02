---
title: Security, Governance & Enterprise Controls
slug: security/governance-controls
section: security
visibility: I
audience: [exec, ops, architect, security, compliance]
status: beta
since_version: "9.0.0"
source_files:
  - Backend Architecture/aether-backend/services/governance/routes.py
  - Backend Architecture/aether-backend/services/reliability/service.py
related:
  - compliance
  - reliability/operations
  - reliability/incident-response
canonical_owner: platform@aether
estimated_read_minutes: 4
---
# Security, Governance & Enterprise Controls

This document indexes Aether's security, compliance, and governance controls and
how the reliability layer integrates with them. For the full compliance posture
see [COMPLIANCE.md](COMPLIANCE.md).

## Tenant isolation & access control

- Tenant-scoped routes resolve the tenant from `request.state.tenant` and are
  strictly single-tenant.
- Internal Kyber routes require operator/admin permission
  (`require_permission("admin")`).
- No cross-tenant data is reachable on any tenant-facing route.

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

## Tenant-safe vs internal visibility

| Surface | Visibility |
|---|---|
| `/v1/status*` (Aether) | Tenant-safe, single-tenant, no infra internals |
| `/v1/admin/kyber/*` (Kyber) | Internal, operator/admin gated |

## Implemented controls

- Permission-gated admin routes; tenant-scoped read routes.
- Internal incident audit trail.
- Field-whitelisted tenant projections.

## Planned controls

- Forwarding incident audit entries into the central security audit ledger.
- RBAC granularity beyond the current admin/read split for reliability views.

## Known gaps

- Incident audit entries are stored in a dedicated internal table rather than the
  unified security audit ledger (planned).

## Rollout notes

- Reliability controls are additive and do not change existing governance,
  auditability, or security guarantees. No external SLA/certification is claimed.
