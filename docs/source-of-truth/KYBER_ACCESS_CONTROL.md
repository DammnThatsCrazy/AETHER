---
title: Kyber Access Control
slug: kyber/access-control
section: kyber
visibility: I
audience: [architect, security, ops]
status: beta
source_files:
  - Backend Architecture/aether-backend/services/security/request_context.py
  - Backend Architecture/aether-backend/services/security/route_registry.py
  - Backend Architecture/aether-backend/services/security/policy_engine.py
  - Backend Architecture/aether-backend/services/kyber/access/capabilities.py
  - Backend Architecture/aether-backend/services/kyber/access/roles.py
  - config/route_registry.yaml
---

# Kyber Access Control

Kyber is the internal Olympus operator console. Its callers are **workforce
principals** — Google Workspace identities bound to a trusted device, carrying
role templates, capability grants and purpose-bound tenant access scopes. They
are not Aether tenants, and no Aether tenant may reach Kyber, including one
holding `Role.ADMIN`.

This document is the authority for four things: the capability vocabulary, the
role-template → `AccessRole` mapping, disclosure levels, and how a route
declares the authority it requires.

---

## 1. Authority has four independent dimensions

A Kyber request is authorized along dimensions that are deliberately *not*
collapsed into a single "admin" bit:

| Dimension | Question it answers | Where it lives |
|---|---|---|
| **Capability** | *What operation?* | `services/kyber/access/capabilities.py` |
| **Disclosure** | *How much may be revealed?* | `services/kyber/access/disclosure.py` |
| **Tenant scope** | *Whose data?* | tenant access scopes (purpose-bound, expiring) |
| **Action class** | *How much can it break?* | `action_class` on each capability |

Holding a capability does not imply a disclosure level, and neither implies a
tenant scope. There is no `canViewAll`: reading fleet aggregates does not imply
reading one tenant, reading a tenant does not imply reading raw evidence, and no
read capability implies any command.

---

## 2. Capability vocabulary

A capability is the *name* a route declares. Each resolves to a
`(GovernanceDomain, PermissionAction, PermissionScope)` triple the existing
`AccessControlService` already evaluates, plus the two dimensions the governance
model does not carry: a disclosure ceiling and an action class.

`ALL_CAPABILITY_IDS` is the closed set. A route may not declare anything else —
an unknown id fails at load (see §5).

| Group | Capability ids |
|---|---|
| Platform / fleet | `kyber.platform.health.read`, `kyber.platform.cost.read`, `kyber.platform.release.read` |
| Graph | `kyber.graph.platform.read`, `kyber.graph.fleet.read`, `kyber.graph.cohort.read`, `kyber.graph.tenant.read`, `kyber.graph.evidence.read` |
| Tenant inspection | `kyber.tenant.mirror.read_masked`, `kyber.tenant.mirror.read`, `kyber.tenant.raw.read` |
| Incidents | `kyber.incident.read`, `kyber.incident.manage`, `kyber.incident.close` |
| Command plane | `kyber.command.retry`, `kyber.command.requeue`, `kyber.command.replay`, `kyber.command.recompute`, `kyber.command.rebuild`, `kyber.command.pause`, `kyber.command.rollback`, `kyber.command.kill_switch` |
| Exports & governance | `kyber.export.create`, `kyber.audit.read`, `kyber.policy.read` |
| Workforce administration | `kyber.device.approve`, `kyber.workforce.manage`, `kyber.role.manage`, `kyber.workforce.self.read` |

Workforce administration is separated from every read capability on purpose: an
operator who can see everything still cannot grant themselves more.

### Action classes

| Class | Meaning | Consequence |
|---|---|---|
| 0 | read / search / compare | — |
| 1 | note / acknowledge | — |
| 2 | retry / requeue | command capability required |
| 3 | recompute / replay a bounded window | command capability required |
| 4 | pause / rollback / high-impact tenant action | fresh step-up required |
| 5 | fleet-wide / global / destructive | fresh step-up required |

A principal's ceiling comes from its role templates (`max_action_class_for`). A
route whose declared class exceeds that ceiling is denied at the boundary.

### Tenant-scoped capabilities

A capability with `tenant_scoped=True` names *one tenant* and therefore requires
an active, purpose-bound tenant access scope naming that same tenant. Where the
route carries a `{tenant_id}` the authorization boundary matches the scope
against that tenant; where it does not, the boundary can only require that some
scope is active and leaves the precise target to the route's own Kyber
dependency, which knows which tenant the resource belongs to.

---

## 3. Role templates → AccessRole

Role templates (`services/kyber/access/roles.py`) are the only way a principal
acquires capabilities. `ROLE_TEMPLATES` maps each template to its
`access_roles`, `capabilities`, `max_disclosure`, `max_action_class`, session
and device lifetimes, and allowed environments.

* `access_roles_for(template_ids)` → the governance `AccessRole`s used by the
  existing access-control and audit surfaces.
* `capabilities_for(template_ids)` → the union of granted capability ids.
* `max_disclosure_for` / `max_action_class_for` → the principal's ceilings.

The workforce `AccessRole` values are `olympus_founder`,
`olympus_engineering`, `olympus_product`, `olympus_observer` (alongside the
pre-existing `olympus_admin` / `olympus_operator`). Every workforce principal
resolves to `actor_type='olympus_operator'` with `tenant_id=None` — an operator
is never scoped to a tenant by identity, only by an access scope.

---

## 4. Disclosure levels

| Level | Reveals |
|---|---|
| `D0` | Platform topology: services, releases, dependency shape |
| `D1` | Fleet aggregates: cross-tenant counts/rates, never a tenant row |
| `D2` | Masked tenant summaries: one tenant, identifiers masked |
| `D3` | Tenant-visible Aether data — exactly what the tenant sees (Tenant Mirror) |
| `D4` | Event-level evidence: individual events, lineage, decisions |
| `D5` | Restricted raw evidence: unmasked raw records; always step-up gated |

Levels are ordered and composed by **minimum**: `effective_disclosure(...)`
takes the least-revealing of every constraint in play (role ceiling, route
declaration, purpose, environment, device state, session strength, consent).
`D2` and above name a tenant and require a scope; `D4` and above require fresh
step-up.

---

## 5. Route registry v3 — declaring authority

`config/route_registry.yaml` is `schema_version: 3`. Policy is still derived
from the path (prefix → domain → sensitivity/risk; any path containing `/kyber`
is operator-required, audited and high risk). v3 adds an **optional per-route
declaration**:

```yaml
kyber_routes:
  - route: "GET /v1/kyber/tenants/{tenant_id}/operational-envelope"
    capability: kyber.tenant.mirror.read
    disclosure: D3
    action_class: 0
```

* `route` is `"<METHOD> <FastAPI path template>"`; `METHOD` may be `*`.
* `capability` **must** be in `ALL_CAPABILITY_IDS` — an unknown id raises
  `ROUTE_REGISTRY_UNKNOWN_CAPABILITY` at load, so a typo is a startup failure
  rather than a silently unenforced route.
* `disclosure` must parse as `D0`..`D5`; `action_class` must be `0..5`;
  duplicate `route` keys are rejected.

`classify(path, method=None)` layers the declaration over the derived policy and
returns `required_capability`, `minimum_disclosure` and `action_class`. The
single-argument form `classify(path)` still works, and a route with no
declaration classifies exactly as it did under v2 with the three new fields
defaulting to `None`/`0`.

**Undeclared is not unguarded.** A Kyber route with no entry still requires an
operator, because `kyber_operator_required` is derived from the path. It is
simply not yet capability-classified — a gap to close, never a state to leave a
shipped route in. New routes are declared below the marked insertion point in
the catalog.

Validated by `scripts/release/check_route_registry.py` and
`tests/unit/test_route_registry_coverage.py`.

---

## 6. Enforcement points

### Middleware (the leverage point)

`middleware/middleware.py::_evaluate_route_policy` classifies every request
against the registry independently of route dependencies. After the operator
check it enforces the declared capability:

* no resolvable workforce context → deny;
* capability not held → deny;
* declared `action_class` above the principal's ceiling → deny;
* tenant-scoped capability with no matching active scope → deny.

Denials use the distinct code `ROUTE_POLICY_KYBER_CAPABILITY_REQUIRED`
(separate from `ROUTE_POLICY_KYBER_OPERATOR_REQUIRED`, so the two failure modes
are distinguishable in logs and dashboards). This is what carries capability
authority to ~158 existing `require_kyber_operator` call sites without editing
them.

### Policy decisions

`PolicyEngine.check_kyber_access(...)` records the outcome under
`policy_key="kyber.access"`. That key is in `_SENSITIVE_KEYS`, so **allowed**
decisions are persisted alongside denials — an operator access log that records
only refusals is not an access log. It runs through the shared `_finalize`
path: the decision lands in `security_policy_decisions` and a linked
`audit_ledger` entry is written. There is no second table and no second ledger.
The method records a decision; it does not re-evaluate authority, because a
second divergent copy of the rules is precisely the failure this design avoids.

---

## 7. Compatibility adapter and migration path

`is_kyber_operator` / `require_kyber_operator`
(`services/security/request_context.py`) keep their names, signatures and
exception types — `UnauthorizedError` when nothing identifies the caller,
`ForbiddenError` when the caller is identified but not an operator. What changed
is the order of resolution:

1. **Workforce session first.** A valid Kyber session resolves the caller to an
   `ActorContext` with `actor_type='olympus_operator'`, `tenant_id=None` and
   roles from `access_roles_for(role_template_ids)`. No Aether tenant and no
   tenant permission is needed or consulted.
2. **Legacy fallback**, only while `KYBER_LEGACY_OPERATOR_IDENTITY_ALLOWED` is
   true: the `kyber:operator` permission grant or the operator tenant-id
   allowlist, inspected against the RAW permission list so a `Role.ADMIN` tenant
   cannot pass.
3. **Otherwise deny**, with `legacy_identity_disabled` in the message.

`is_kyber_operator(tenant)` keeps its positional contract; the new optional
`request` argument is what admits a workforce session.

Worker-owned modules under `services/kyber/access/` are imported **lazily**
inside functions. Every failure mode — module absent, import raising, or an
unawaitable coroutine returned to synchronous code — resolves to "no workforce
session", which callers treat as **deny**.

### Migration sequence

1. Ship the adapter with `KYBER_WORKFORCE_IDENTITY_ENABLED=true` and
   `KYBER_LEGACY_OPERATOR_IDENTITY_ALLOWED=true`. Both identities work.
2. Onboard workforce principals and devices; watch
   `route_policy_kyber_capability_observed` with
   `KYBER_BACKEND_AUTHZ_ENFORCED=true` and route policy in observe mode.
3. Declare the remaining Kyber routes in `kyber_routes`.
4. Set `KYBER_LEGACY_OPERATOR_IDENTITY_ALLOWED=false`. Legacy operator identity
   is retired across all call sites by one flag.

---

## 8. Flags and rollback

`config/settings.py::KyberWorkforceConfig`, attribute `settings.kyber_workforce`.

| Attribute | Env var | Default |
|---|---|---|
| `workforce_identity_enabled` | `KYBER_WORKFORCE_IDENTITY_ENABLED` | true (non-local) |
| `device_trust_required` | `KYBER_DEVICE_TRUST_REQUIRED` | true (non-local) |
| `backend_authz_enforced` | `KYBER_BACKEND_AUTHZ_ENFORCED` | true (non-local) |
| `scope_v2_enabled` | `KYBER_SCOPE_V2_ENABLED` | true |
| `step_up_required` | `KYBER_STEP_UP_REQUIRED` | true (non-local) |
| `legacy_operator_identity_allowed` | `KYBER_LEGACY_OPERATOR_IDENTITY_ALLOWED` | true local, false otherwise |
| `google_client_id` | `KYBER_GOOGLE_CLIENT_ID` | — |
| `google_client_secret` | `KYBER_GOOGLE_CLIENT_SECRET` | — |
| `google_redirect_uri` | `KYBER_GOOGLE_REDIRECT_URI` | — |
| `google_hosted_domain` | `KYBER_GOOGLE_HOSTED_DOMAIN` | — |
| `google_discovery_url` | `KYBER_GOOGLE_DISCOVERY_URL` | Google OIDC discovery |
| `webauthn_rp_id` | `KYBER_WEBAUTHN_RP_ID` | — |
| `webauthn_rp_name` | `KYBER_WEBAUTHN_RP_NAME` | `Kyber` |
| `webauthn_origin` | `KYBER_WEBAUTHN_ORIGIN` | — |
| `bootstrap_enabled` | `KYBER_BOOTSTRAP_ENABLED` | false |
| `bootstrap_founder_email` | `KYBER_BOOTSTRAP_FOUNDER_EMAIL` | — |
| `bootstrap_founder_google_subject` | `KYBER_BOOTSTRAP_FOUNDER_GOOGLE_SUBJECT` | — |
| `directory_sync_enabled` | `KYBER_DIRECTORY_SYNC_ENABLED` | false |
| `directory_max_stale_hours` | `KYBER_DIRECTORY_MAX_STALE_HOURS` | 24 |
| `session_cookie_secure` | `KYBER_SESSION_COOKIE_SECURE` | true (non-local) |

### Rollback

* `KYBER_BACKEND_AUTHZ_ENFORCED=false` turns off capability enforcement
  entirely — pre-migration behaviour, no code change.
* Route policy in observe mode (`ROUTE_REGISTRY_ENFORCED=false`) keeps the
  checks running but warns and increments
  `route_policy_kyber_capability_observed` instead of denying.
* `KYBER_LEGACY_OPERATOR_IDENTITY_ALLOWED=true` restores the legacy operator
  path.

### Staging / production fail-closed

Mirroring the `ROUTE_POLICY_ENFORCEMENT_REQUIRED` precedent, `Settings()` raises
`KYBER_WORKFORCE_ENFORCEMENT_REQUIRED:` on a deploy target when workforce
identity is disabled, backend authz is in observe mode, device trust is off,
legacy operator identity is still accepted alongside workforce identity, the
founder bootstrap path is open, or the Google client id / redirect URI /
WebAuthn RP id / origin are unset while workforce identity is on.

---

## 9. Related fixes

Two authorization branches that predated this plane were corrected alongside it:

* `services/operational_intelligence/routes.py` gated the graph reconciliation
  and cross-tenant graph-health paths on `getattr(tenant, "is_platform_admin",
  False)`. `TenantContext` has no such field, so the branch was permanently
  False and the documented operator path could not work. Both now use the
  canonical gate plus a required active tenant access scope.
* `services/noesis/service.py::_resolve_scope` authorized cross-tenant Kyber
  access on `tenant.role == Role.ADMIN` — the very tenant the canonical gate
  rejects — and entered fleet-wide mode by substring-matching the user's
  natural-language message. It now uses the canonical gate, requires an active
  scope for single-tenant cross-tenant reads, and requires both an explicit
  `tenant_id` aggregate token and the `kyber.graph.fleet.read` capability for
  fleet-wide mode. The Noesis response contract is unchanged.
