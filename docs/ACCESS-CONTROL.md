---
title: Access Control
slug: enterprise/access-control
section: operations
visibility: I
audience: [ops, security]
status: stable
since_version: "0.1.0"
---

# Access Control

`AccessControlService` (`services/backend/services/security/access_control.py`) maps `AccessRole`s
to `PermissionGrant`s and evaluates `domain × action × scope` access checks.

## Implemented controls

- 13 roles: `tenant_owner`, `tenant_admin`, `tenant_operator`, `tenant_analyst`,
  `tenant_viewer`, `tenant_billing_admin`, `tenant_security_admin`,
  `olympus_operator`, `olympus_support`, `olympus_admin`, `olympus_security`,
  `olympus_revops`, `auditor`.
- 20 domains, 8 actions (`read`/`write`/`approve`/`dispatch`/`export`/`configure`/`delete`/`admin`).
- 4 scopes: `own_tenant`, `assigned_tenant`, `all_tenants_aggregate`,
  `all_tenants_admin`. Aggregate scope can authorize aggregate views only — never
  a single tenant's private records.
- `evaluate()` returns a `PolicyDecision`; denials and sensitive allows emit a
  `SecurityAuditEvent`.
- `require_access()` keeps the legacy `require_permission(...)` gate and layers
  role evaluation + audit on top (additive).

## Role assignment

Tenant users are mapped from the existing auth `Role` (`admin`/`editor`/`viewer`)
plus permissions (`tenant_roles_from_context`).

**No Aether tenant may access Kyber.** Kyber security routes are gated by
`require_kyber_operator()`, which is fail-closed: an operator is recognised ONLY
by a signal that tenant tokens never carry — the configured `kyber:operator`
permission (`KYBER_OPERATOR_PERMISSION`) present in the token's **raw permission
list**, or membership in the operator allowlist (`KYBER_OPERATOR_TENANT_IDS`).
The check deliberately does **not** use `has_permission()`, which returns `True`
for every permission when `role == Role.ADMIN`; a role-admin Aether tenant is
therefore still **denied**. A verified operator with `admin` is mapped to
`olympus_admin`; other verified operators map to `olympus_operator`.

Within the Kyber security routes, **reads** require operator access while
**privileged mutations** (retention policy create/update, data-request
processing, evidence-pack generation, and break-glass approve/deny/revoke)
additionally require the `admin` permission, so a read-only `kyber:operator`
token cannot perform privileged actions.

## Platform operators

Olympus staff and invited advisors run the platform; they are not billed
customers. A **platform operator** tenant resolves to the top plan (`omega`,
every service) and bypasses the customer controls in the request middleware:
the per-plan burst rate limit, the monthly quota and its overage metering, and
the ML extraction-defense budget. Each such request increments
`platform_operator_request_total`. External tenants keep every control.

A tenant is an operator only through a signal it cannot grant itself:
`PLATFORM_OPERATOR_TENANT_IDS`, set per environment, or, in staging, the tenant
bound by the single-use first-admin bootstrap
(`shared/auth/platform_operator.py`). This does **not** grant Kyber access, which
stays behind `KYBER_OPERATOR_TENANT_IDS` and the operator permission above.

## Staging sign-in (internal only)

Staging is for Olympus staff and invited advisors. An Auth0 sign-in there never
provisions a new tenant (`SSO_SELF_SIGNUP_ENABLED` defaults to `false` when
`AETHER_ENV=staging`). A sign-in whose `sub` is not yet linked succeeds only
when its identity-provider-verified email:

1. matches an existing active user with no Auth0 link (for example the staging
   first-admin user), which is then linked; or
2. has an unexpired pending organization invitation, which is accepted: the
   person joins the inviting tenant with the invited role.

Anything else gets `403` ("Sign-in is by invitation only"). A tenant admin's
first organization request creates the organization profile, owned by that
admin, so the operator tenant can invite teammates via
`POST /v1/account/organization/invitations`. Other environments keep self-serve
Auth0 sign-up.

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
