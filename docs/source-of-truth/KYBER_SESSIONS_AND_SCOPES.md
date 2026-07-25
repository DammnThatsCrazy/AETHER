---
title: Kyber Sessions and Tenant Access Scopes
slug: kyber/sessions-and-scopes
section: kyber
visibility: I
audience: [architect, security, ops]
status: beta
source_files:
  - Backend Architecture/aether-backend/services/kyber/sessions/service.py
  - Backend Architecture/aether-backend/services/kyber/sessions/step_up.py
  - Backend Architecture/aether-backend/services/kyber/access/scopes.py
  - Backend Architecture/aether-backend/services/kyber/access/dependencies.py
---

# Kyber Sessions and Tenant Access Scopes

Kyber is the Olympus Labs internal operating plane. Everyone who signs into it
is an Olympus workforce principal, never an Aether tenant. This page is the
source of truth for how a Kyber session is issued, how long each layer of its
authority lasts, how an operator enters a single tenant, and the exact order in
which the backend decides whether a request is allowed.

One rule underpins everything below and is stated here so nothing later
contradicts it:

> **A client-supplied tenant id never grants authority.** A tenant id in a path,
> query string, header or body is only ever *compared* against the tenant named
> by the operator's open access scope. When the two disagree the request is
> denied. It is never silently re-scoped, and the existing scope is never
> widened to cover it.

---

## 1. The four authority layers

A Kyber operator holds one opaque session handle. What that handle is *worth*
depends on which of four independent windows is still open. They are layers,
not alternatives: a step-up does not extend a session, and a session does not
extend a device registration.

| # | Layer | Lifetime source | What it unlocks |
|---|---|---|---|
| 1 | **Presence** | `presence_minutes` | The console shell and low-risk aggregate health. No tenant detail, no evidence, no commands, no exports, no workforce administration. |
| 2 | **Operator authority** | `session_absolute_minutes` (hard ceiling) + `session_idle_minutes` (sliding) | Everything the principal's capabilities allow, up to their disclosure ceiling. |
| 3 | **Step-up** | `step_up_minutes` | Record-level evidence (D4/D5) and high-impact / fleet-destructive action classes. |
| 4 | **Device registration** | `device_registration_days` | Whether this machine may be used at all. Owned by the device plane, not by the session plane. |

### 1.1 Per-role defaults

Every value is a default a deployment may override through configuration. The
lifetimes live on the backend; the frontend reads what was granted and never
decides how long anything lasts.

| Role template | Absolute | Idle | Step-up | Presence | Device reg. | Max disclosure | Max action class |
|---|---|---|---|---|---|---|---|
| `founder_operator` | 24 h | 4 h | 15 min | 7 d | 90 d | D5 | 5 |
| `emergency_root` | 15 min | 15 min | 15 min | **0** | 30 d | D5 | 5 |
| `cto_engineering_command` | 16 h | 2 h | 10 min | 7 d | 60 d | D4 | 4 |
| `operations_command` | 16 h | 2 h | 10 min | 7 d | 60 d | D4 | 3 |
| `founding_engineer` | 12 h | 2 h | 10 min | 7 d | 60 d | D4 | 3 |
| `head_of_product` | 12 h | 1 h | 10 min | 7 d | 30 d | D3 | 0 |
| `product_manager` | 12 h | 1 h | 10 min | 7 d | 30 d | D3 | 0 |
| `designer` | 12 h | 1 h | 10 min | 7 d | 30 d | D1 | 0 |
| `security_auditor` | 8 h | 1 h | 10 min | 7 d | 30 d | D4 | 1 |
| `observer` | 8 h | 1 h | 10 min | 7 d | 30 d | D1 | 0 |

`emergency_root` has a presence window of zero on purpose: break-glass is never
a working session, cannot be left logged in, and expires automatically.

When a principal holds several templates the windows compose to the **most
restrictive** value, not the most generous. Holding a working template
alongside a break-glass one must not lengthen the break-glass session. When no
template resolves at all — including when the identity service is unavailable —
the fallback is the shortest window Kyber defines (15 minutes absolute and
idle, zero presence).

### 1.2 The idle window slides

`idle_expires_at` is pushed forward on every successful validation, clamped by
the absolute ceiling. An unattended console closes early; an actively used one
does not; neither outlives the hard ceiling.

This is a deliberate correction. `services/auth/sessions/service.py` sets its
idle expiry once at creation and never moves it, which makes its "idle" timeout
a second absolute cap and kills an actively used session mid-work. Kyber does
not copy that behaviour.

Authority does **not** silently degrade into presence when its ceiling passes.
A session past `authority_expires_at` is expired and the operator
re-authenticates.

### 1.3 The handle itself

* Opaque, `kses_` + 48 hex characters. It is a lookup key and carries no claims.
* Only `sha256(token)` is persisted, in `kyber_workforce_sessions.token_hash`.
  Presenting the digest instead of the handle proves nothing.
* The raw value is returned by `create_session` and `rotate` and by nothing
  else — not in a log line, not in a response body, not in an audit record.
* Transported in `__Host-kyber_session`: `Secure; HttpOnly; SameSite=Strict;
  Path=/` and **no `Domain` attribute**, which the `__Host-` prefix requires and
  which is what makes cookie fixation from a sibling subdomain impossible.
  `Secure` may be relaxed only when `AETHER_ENV` is `local`, `dev`,
  `development`, `test` or `testing`; every other value — including unset or
  misspelled — keeps it on.

### 1.4 Authentication strength is derived, never supplied

| Factors actually verified | Strength | Status |
|---|---|---|
| `google_oidc` alone | `identity_only` | `restricted` |
| `google_oidc` + `webauthn` + `device_proof` on a usable approved device | `device_bound` | `active` |
| the above plus a live step-up grant | `stepped_up` | `active` |

A caller cannot assert its own strength: the value is computed from the factor
list plus a live device-usability check, so claiming `device_bound` without a
device proof yields `identity_only`.

### 1.5 Rotation

The handle is replaced — invalidating the previous one immediately — on:

* any authentication-strength change,
* any privilege change (role bindings or capability grants),
* every step-up elevation.

Rotation is the session-fixation defence. A handle an attacker planted before
the victim authenticated, or captured before an elevation, is worthless
afterwards. `sessions/validation.requires_rotation` is the pure predicate;
`rotate()` and `grant_and_rotate()` perform it and return the new raw handle so
the caller can set the new cookie — a rotation whose token nobody receives
would lock the operator out of their own session.

### 1.6 Termination

| Trigger | Effect |
|---|---|
| `revoke(session_id)` | That session ends. |
| `revoke_for_device(device_id)` | Every session bound to that device ends. |
| `revoke_for_operator(operator_id)` | Every session for the principal ends **and every tenant access scope they hold is closed**. |
| `reconcile_privileges(operator_id, new_template_ids)` | Sessions whose cached template set no longer matches are revoked. |
| Absolute / idle / presence window elapses | The session expires; validation fails closed regardless of whether the sweep has run. |

---

## 2. Step-up elevation

A step-up grant proves the human at the keyboard re-asserted possession of the
registered authenticator *now*.

* **Bound to the session and the device.** Lifting a grant out of a captured
  session and replaying it elsewhere fails on the binding.
* **Short and absolute.** Expiry comes from `step_up_minutes` and is never
  extended; activity does not slide it.
* **Single-purpose when narrowed.** A grant that names a capability satisfies
  only that capability. A grant with no capability is a general elevation.
* **Consumable.** A consumed grant never satisfies a later check.
* **Verified.** `grant()` refuses to mint an elevation it did not itself see
  verified; a missing verification provider is never read as a passing one.

Every unusable elevation — expired, consumed, revoked, wrong device, wrong
capability, absent — reports the identical `step_up_required`, so the response
cannot be used to probe state.

---

## 3. Tenant access scopes

Reading one tenant's data is not standing permission. It is an act, taken for a
stated reason, for a bounded time, on exactly one tenant. A scope
(`kyber_access_scopes`) is that act made durable.

This replaces an in-process dictionary keyed by operator id. Each row below is
a property the dictionary lacked:

| Previously | Now |
|---|---|
| Lost on restart, per worker process | Persisted and shared |
| Bound to the operator only | Bound to the session **and** the device |
| Implicitly re-scoped on the next request | Exactly one tenant; a mismatch is a denial |
| No expiry | TTL of 1–480 minutes (default 60), swept and enforced lazily |
| Entry logged, exit not | Open, exit, expiry and revoke all audited |

### 3.1 Lifecycle

1. **Open** — `open_scope` takes an operator, session, device, environment,
   tenant, purpose, reason, optional ticket reference, disclosure level and TTL.
   The reason must be at least **10 characters** (the floor the previous
   tenant-entry endpoint enforced, kept because the ledger is only as useful as
   the reasons in it). The purpose must come from the closed
   `AccessScopePurpose` set: `incident_response`, `customer_support`,
   `compliance_audit`, `security_investigation`, `data_request`, `diagnostics`,
   `break_glass`, `product_validation`. TTL is clamped to 1–480 minutes. The
   requested disclosure level is clamped to what the caller's role and
   capability already allow — a scope can lower what is visible, never raise it.
2. **Supersede** — a session holds at most one active scope. Opening another
   closes the previous one with status `exited`, and the transition is audited.
3. **Resolve** — `resolve_for_tenant(session_id, tenant_id)` returns
   `(scope, None)` or `(None, reason)`.
4. **Close** — `exit_scope` (status `exited`), `expire_due` / lazy expiry
   (status `expired`), `revoke_for_session` / `revoke_for_operator`
   (status `revoked`). All four are audited; all are idempotent.

### 3.2 Resolution outcomes

| Situation | Result |
|---|---|
| No scope on this session | `(None, "scope_missing")` |
| The session's scope for this tenant has elapsed | `(None, "scope_expired")` |
| The scope names a different tenant than the request | `(None, "scope_tenant_mismatch")` |
| Live scope naming exactly this tenant | `(scope, None)` |

The mismatch branch leaves the existing scope untouched. Denying is the whole
point: a request naming a different tenant is either a bug or an attempt to
pivot, and both answers are no.

---

## 4. The authorization sequence

`require_kyber_access(capability, *, disclosure, action_class, tenant_scope)` in
`access/dependencies.py` is the single canonical entry point. Handlers never
re-derive authority, and the frontend never derives it at all — it renders what
`KyberAccessContext` reports.

Every step fails closed, in this order:

| # | Step | Denial reasons |
|---|---|---|
| 1 | Session handle present, live, within its absolute and (sliding) idle windows, not replayed from another device | `no_session`, `session_expired`, `session_revoked`, `session_restricted`, `device_mismatch` |
| — | Request shape for mutating methods: origin allow-list, `Sec-Fetch-Site: same-origin`, CSRF header vs. cookie | *(no `DenialReason` — a forged request is malformed, not an authorization outcome)* |
| 2 | Principal resolves and is `active` + `kyber_enabled` | `principal_unknown`, `principal_inactive` |
| 3 | Directory record is fresh (privileged roles lose authority while stale) | `directory_stale` |
| 4 | Device resolves, is usable, and matches the session binding | `device_unapproved`, `device_revoked`, `device_mismatch` |
| 5 | Route classification — an injected `RoutePolicy` may tighten the declared requirements, never loosen them | — |
| 6 | Capability held; a live `deny` grant always wins over an allowing template | `capability_missing` |
| 7 | Environment permitted by **every** bound role template and by the principal | `environment_not_allowed` |
| 8 | Requested action class within the principal's ceiling | `action_class_exceeded` |
| 9 | Tenant scope resolved (when `tenant_scope != "none"`) and naming the requested tenant | `scope_missing`, `scope_expired`, `scope_tenant_mismatch`, `device_mismatch` |
| 10 | Effective disclosure = `min(role ceiling, capability ceiling, scope level, requested)` | `disclosure_exceeded` |
| 11 | Fresh step-up when the capability, action class or effective disclosure demands it | `step_up_required` |
| 12 | Durable `KyberAccessDecision` written; context returned | — |

### 4.1 Failing closed on a missing dependency

The identity, device, directory and proof services are reached through
`AccessProviders` (`get_providers` / `set_providers`). When a provider cannot be
resolved, **every authorization path denies**. An unavailable verifier is never
treated as a passing verifier, and a partially deployed Kyber refuses requests
rather than failing to start.

### 4.2 Evidence

Every decision — allow and deny alike — is recorded through the existing
`services/security/policy_engine.PolicyEngine`, so Kyber decisions land in the
same governance ledger as everything else. The `kyber_access_decisions` row is
the Kyber-specific detail hanging off that decision and carries
`policy_decision_id` when one exists. **There is no second audit ledger.** If
the policy engine has no Kyber method yet, the fallback writes an
`audit_ledger` entry directly, so a decision is never unrecorded. A denial still
names the operator, session, device and tenant involved — a denial that
identifies nobody is not evidence.

Metrics emitted: `kyber_session_active`, `kyber_session_revoked_total`,
`kyber_access_decision_total`, `kyber_access_denied_total`, `kyber_scope_active`,
`kyber_auth_success_total`, `kyber_auth_failure_total`.

---

## 5. Denial reasons

The complete closed set from `access/contracts.DenialReason`. Every value is
safe to return to the caller: none of them disclose whether a principal, device
or tenant exists.

| Reason | Meaning | HTTP |
|---|---|---|
| `no_session` | No handle presented, or it resolves to nothing. | 401 |
| `session_expired` | The absolute (or presence) ceiling or the idle window has passed. | 401 |
| `session_revoked` | The session was ended by an operator, a device revocation or a principal lifecycle change. | 401 |
| `session_restricted` | A presence-only session reached an authority route. Presence routes still serve it. | 403 |
| `principal_unknown` | No workforce principal backs the session — or the identity service is unavailable. | 401 |
| `principal_inactive` | The principal is suspended, offboarded, or has `kyber_enabled = false`. | 403 |
| `device_unapproved` | No trusted device resolved, or it is not approved — or the device service is unavailable. | 403 |
| `device_revoked` | The device was revoked or its risk state blocks use. | 403 |
| `device_mismatch` | The device proved by the request is not the one the session, or the scope, is bound to. | 403 |
| `device_proof_invalid` | A device-proof assertion failed verification. | 401 |
| `capability_missing` | The capability is not held, or a live `deny` grant overrides an allowing template. | 403 |
| `disclosure_exceeded` | The requested level is above the minimum of role, capability and scope ceilings. | 403 |
| `action_class_exceeded` | The action class is above the principal's ceiling. | 403 |
| `scope_missing` | The route needs a tenant scope and none is open. | 403 |
| `scope_expired` | The scope for this tenant has elapsed. | 403 |
| `scope_tenant_mismatch` | The requested tenant is not the tenant the scope names. | 403 |
| `step_up_required` | No live, correctly bound, correctly narrowed elevation covers this request. | 403 |
| `approval_required` | A second-person approval is outstanding. | 403 |
| `environment_not_allowed` | A bound role template, or the principal, excludes this environment. | 403 |
| `directory_stale` | Directory reconciliation is overdue or unavailable and the request is privileged. | 403 |
| `legacy_identity_disabled` | A legacy (non-workforce) identity attempted a Kyber route. | 403 |

Request-shape rejections (`csrf_invalid`, `origin_not_allowed`,
`origin_missing`, `fetch_site_not_same_origin`) are deliberately **not** in this
set. They are malformed requests, and reporting them as an authorization
outcome would mislead an operator into thinking their session or role was at
fault.

---

## 6. Endpoints

Neither router is mounted in `main.py`; both are mounted by the Kyber console
assembly.

### `/v1/kyber/auth` — sessions

| Method | Path | Capability |
|---|---|---|
| GET | `/session` | presence (`kyber.workforce.self.read`) |
| POST | `/step-up/options` | `kyber.workforce.self.read` |
| POST | `/step-up/verify` | `kyber.workforce.self.read` |
| GET | `/sessions` | `kyber.workforce.self.read` (self only) |
| POST | `/sessions/{session_id}/revoke` | `kyber.workforce.self.read`; another operator's session additionally requires `kyber.workforce.manage` |

There is deliberately no endpoint that mints a session, extends one, or returns
a raw handle for an existing one. Sign-in lives in the identity plane, where the
Google assertion and the device proof are verified.

`GET /session` returns a fresh CSRF token in the response body and sets the
HttpOnly cookie copy. The application echoes the body value in `X-Kyber-CSRF`;
script cannot read the cookie, so a cross-site request cannot produce a matching
pair.

### `/v1/kyber/scopes` — tenant access

| Method | Path | Capability |
|---|---|---|
| POST | `""` | `kyber.tenant.mirror.read_masked` |
| GET | `/current` | `kyber.workforce.self.read` |
| GET | `""` | `kyber.workforce.self.read`; listing other operators' scopes requires `kyber.audit.read` |
| DELETE | `/{scope_id}` | `kyber.workforce.self.read` (own scopes only) |

No route widens a scope, changes its tenant, or extends it. A different tenant
or a longer window means opening a new scope, which produces a new audit record.

---

## 7. Configuration

| Variable | Type | Default | Purpose |
|---|---|---|---|
| `AETHER_ENV` | string | `local` | Governs cookie `Secure` (relaxed only for `local`/`dev`/`development`/`test`/`testing`) and the repository backend. |
| `KYBER_ALLOWED_ORIGINS` | comma-separated string | empty | Origin allow-list for mutating Kyber requests. Outside local/dev an unset value yields an empty list, so every mutating request fails closed until the console origin is configured. |
