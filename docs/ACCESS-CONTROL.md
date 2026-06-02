---
title: Access Control
slug: enterprise/access-control
section: enterprise
visibility: I
audience: [ops, security]
status: stable
since_version: "13.0.0"
---

# Access Control

`AccessControlService` (`services/security/access_control.py`) maps `AccessRole`s
to `PermissionGrant`s and evaluates `domain × action × scope` access checks.

## Implemented controls

- 13 roles: `tenant_owner`, `tenant_admin`, `tenant_operator`, `tenant_analyst`,
  `tenant_viewer`, `tenant_billing_admin`, `tenant_security_admin`,
  `olympus_operator`, `olympus_support`, `olympus_admin`, `olympus_security`,
  `olympus_revops`, `auditor`.
- 16 domains, 8 actions (`read`/`write`/`approve`/`dispatch`/`export`/`configure`/`delete`/`admin`).
- 4 scopes: `own_tenant`, `assigned_tenant`, `all_tenants_aggregate`,
  `all_tenants_admin`. Aggregate scope can authorize aggregate views only — never
  a single tenant's private records.
- `evaluate()` returns a `PolicyDecision`; denials and sensitive allows emit a
  `SecurityAuditEvent`.
- `require_access()` keeps the legacy `require_permission(...)` gate and layers
  role evaluation + audit on top (additive).

## Role assignment

Tenant users are mapped from the existing auth `Role` (`admin`/`editor`/`viewer`)
plus permissions (`tenant_roles_from_context`). Kyber admin principals are treated
as `olympus_admin` for aggregate access.

## Tenant vs Kyber visibility

Tenants resolve only their own grants via `GET /v1/security/me/permissions`.
Operator role definitions are visible in Kyber at
`GET /v1/admin/kyber/security/operator-access`.

## Planned controls

- Unified role provisioning/federation for Olympus operators.
- Fine-grained per-tenant operator assignment lists.

## Known gaps / not certified

- No certification is claimed. Role assignment provisioning still originates in
  the existing auth layer; this service evaluates, it does not provision.
