---
title: Kyber Workforce Identity
slug: kyber/workforce-identity
section: kyber
visibility: I
audience: [architect, security, ops]
status: beta
source_files:
  - Backend Architecture/aether-backend/services/kyber/identity/principals.py
  - Backend Architecture/aether-backend/services/kyber/identity/invitations.py
  - Backend Architecture/aether-backend/services/kyber/identity/oidc.py
  - Backend Architecture/aether-backend/services/kyber/identity/bootstrap.py
  - Backend Architecture/aether-backend/services/kyber/identity/directory_sync.py
---

# Kyber Workforce Identity

Kyber is the Olympus Labs internal operating plane. This document is the source
of truth for **who a Kyber user is**, how they come to exist, how they
authenticate, and how their access ends.

---

## 1. Invariants

These hold everywhere. A change to any of them is a change to this document
first and to code second.

### 1.1 Workforce identity is not tenant identity

An Olympus operator is a `WorkforcePrincipal` in
`olympus_workforce_principals`. It is not an Aether tenant, not an Aether user,
and not a tenant user holding an elevated permission. The two identity spaces
never intersect:

* no Aether authentication path can create a workforce principal, and
* no workforce principal can authenticate through a tenant login.

Workforce rows carry `tenant_id = NULL` by design — an Olympus employee does
not belong to a tenant. Only access scopes and access decisions name a tenant,
and they name the tenant being *inspected*, not the operator's own.

### 1.2 Invite-only, in the strong sense

There is no self-service signup. Authenticating with a Google account in the
right Workspace domain grants nothing: the callback resolves the Google subject
to a principal, and **no principal means denied**, not "admitted with an empty
role set". Admission happens exactly twice in a principal's life — once when an
invitation is issued, once when it is redeemed — and both are audited.

### 1.3 Google is the password authority

Kyber holds no password, no password hash, no recovery question and no second
factor of its own. Google Workspace owns credentials, MFA policy, recovery and
suspension. The practical consequences:

* disabling a Google account immediately prevents new Kyber logins, because the
  OIDC flow itself cannot complete;
* Kyber never needs to implement password reset, credential rotation or
  breach-response for a secret it does not have; and
* a compromise of the Kyber database discloses no credential — invitation and
  session tokens are stored as sha256 digests only.

There is no "Kyber password" to add later. Adding one would create a second,
weaker authority over the same accounts.

### 1.4 Nothing authority-bearing reaches the browser

The authorization-code + PKCE exchange runs entirely server-side. The browser
receives a redirect to Google and, afterwards, an opaque session cookie. It
never receives an `id_token`, an `access_token`, a refresh token or a claim
set. The frontend renders `GET /v1/kyber/me` and derives no authority itself.

### 1.5 Authority resolution fails closed

`PrincipalService.effective_capabilities` returns the **empty set** when the
principal is unknown, not `active`, has `kyber_enabled = False`, or names an
environment outside its `allowed_environments`. Expired and revoked bindings
and grants are ignored. A live `deny` capability grant always beats a role
template that would allow the same capability, so removing one capability from
one operator never requires rebuilding a shared role.

---

## 2. Lifecycle states

`employment_status` is the single state field. `kyber_enabled` is an
independent kill switch that disables Kyber access without asserting anything
about employment.

| State | Meaning | Capabilities | How it is entered |
|---|---|---|---|
| `invited` | An invitation was issued; nobody has redeemed it | none | `POST /v1/kyber/workforce/invitations` |
| `active` | Redeemed, Google subject bound | resolved from live bindings and grants | invitation acceptance, or founder bootstrap |
| `suspended` | Access withdrawn, reversibly | none | manual suspend, or directory reconciliation |
| `offboarded` | Terminal | none | offboard funnel, or directory user absent |

Transitions worth stating explicitly:

* An `invited` principal holds **no role bindings**. Templates requested by the
  invitation are bound at acceptance, not at issue, so an unredeemed invitation
  confers nothing even if the principal row is read directly.
* `activate()` binds the Google subject. Re-activating with a *different*
  subject is rejected — rebinding the identity key is precisely how one
  operator would inherit another's authority.
* `offboarded` is terminal. `activate()` on an offboarded principal raises;
  re-admitting someone means a new invitation and a new principal.
* `suspend` and `offboard` are idempotent and both emit audit records on every
  call, including repeats.

---

## 3. Invitations

`InvitationService.create_invitation` returns `(invitation, raw_token)`. The
raw token is `secrets.token_urlsafe(32)`, returned **exactly once**, in the
creation response only. What is persisted is `sha256(token)`. Re-sending an
invitation means revoking it and issuing another; there is no path that
recovers the original token.

Enforced at issue:

* TTL is clamped to **1–48 hours** (default 24).
* Every requested role template must exist; an unknown id is rejected rather
  than silently dropped, because dropping it would create a principal with less
  authority than the inviter believes they granted.
* `founder_operator` and `emergency_root` are **refused**. Both confer
  authority over the workforce itself, so an invitation can never bootstrap
  `kyber.workforce.manage` or `kyber.role.manage` for its own recipient. Those
  templates are assigned by a founder after acceptance, through
  `POST /v1/kyber/workforce/principals/{operator_id}/roles`.

Enforced at acceptance:

* single use — the invitation is marked `accepted` before any authority is
  granted, so a concurrent second redemption finds it consumed;
* expiry and revocation are rejected;
* the **verified** email Google asserted must equal the invited email, so a
  forwarded invitation grants nothing; and
* a Google subject already bound to a different principal is rejected.

Every rejection records an audit event with a coarse reason and raises an
error that does not disclose whether the invitation exists.

---

## 4. Google OIDC

Authorization-code flow with PKCE (S256). State, nonce and the PKCE verifier
live in a server-side `OidcTransactionStore` with a TTL of minutes. Consuming a
state **deletes** it, so a replayed callback finds nothing.

Every ID-token check fails closed with a distinct, non-disclosing reason:

| Check | Denial reason |
|---|---|
| `iss` in `{https://accounts.google.com, accounts.google.com}` | `issuer_invalid` |
| `aud` equals the configured client id | `audience_invalid` |
| `exp` present and not past (120s leeway) | `expiry_missing` / `token_expired` |
| `iat` present and not future (120s leeway) | `issued_at_missing` / `token_not_yet_valid` |
| `nonce` matches the stored transaction | `nonce_mismatch` |
| `email_verified is True` | `email_unverified` |
| `hd` equals the configured hosted domain, when one is configured | `hosted_domain_mismatch` |
| RS256 signature verifies against the JWKS key matching `kid` | `id_token_signature_invalid` |
| A JWT implementation capable of RS256 is present | `jwt_unavailable` |

The last row matters more than it looks. Test environments may substitute a
stub for `jwt`; treating an unverifiable token as verified would turn a test
convenience into an authentication bypass. The absence of the means to verify
is itself a denial.

`MockOidcProvider` implements the same interface for local development and
tests. Its **constructor** raises `RuntimeError` unless `AETHER_ENV` is
`local`, `dev` or `test` — a mock identity provider reachable in production
would be a complete bypass, so the guard is not a runtime branch that could be
misconfigured around.

---

## 5. Founder bootstrap

Invite-only leaves one question: who invites the first person? The bootstrap
answers it once and closes behind itself.

`POST /v1/kyber/auth/bootstrap` succeeds only when **all** of these hold:

1. `KYBER_BOOTSTRAP_ENABLED` is explicitly on;
2. `count_principals() == 0`;
3. the verified Google email matches `KYBER_BOOTSTRAP_FOUNDER_EMAIL`, and —
   when set — the subject matches `KYBER_BOOTSTRAP_FOUNDER_GOOGLE_SUBJECT`; and
4. no `bootstrap_completed` marker exists in `kyber_authentication_events`.

It creates exactly one `founder_operator` principal, writes the durable
`bootstrap_completed` marker, and emits an immutable
`kyber.bootstrap.completed` audit event. The marker is what makes a second
bootstrap fail even if the operator forgets to turn the environment gate back
off, and even if the founder principal is later deleted — the environment gate
is never the only thing standing between an attacker and a founder account.

### Procedure

1. Create the Google Workspace OAuth client; set `KYBER_GOOGLE_CLIENT_ID`,
   `KYBER_GOOGLE_CLIENT_SECRET`, `KYBER_GOOGLE_REDIRECT_URI` and
   `KYBER_GOOGLE_HOSTED_DOMAIN`.
2. Set `KYBER_BOOTSTRAP_FOUNDER_EMAIL` (and ideally
   `KYBER_BOOTSTRAP_FOUNDER_GOOGLE_SUBJECT`).
3. Set `KYBER_BOOTSTRAP_ENABLED=true` and restart.
4. Complete the Google login and call `POST /v1/kyber/auth/bootstrap`.
5. **Set `KYBER_BOOTSTRAP_ENABLED=false` and restart.** The marker already
   blocks a second run; turning the gate off removes the route's reachability
   as well.
6. Verify: `GET /v1/kyber/workforce/principals` shows exactly one `active`
   `founder_operator`, and the audit ledger contains
   `kyber.bootstrap.completed`.

---

## 6. Directory reconciliation — and its honest limits

Kyber does not own employment; Google Workspace does. `DirectorySyncService`
reconciles principals against the Admin SDK: a suspended or archived Workspace
user is suspended in Kyber, and an absent one is put through the full
offboarding funnel.

**The limitation, stated plainly:** the Admin SDK integration is *optional*.
It is active only when `KYBER_DIRECTORY_SYNC_ENABLED` is on **and**
`KYBER_GOOGLE_ADMIN_ACCESS_TOKEN` is present. When it is not configured,
reconciliation is a no-op that logs and counts the reason and deliberately does
**not** stamp `last_directory_sync_at` — a principal is never marked fresh by a
reconciliation that did not happen.

Consequently, in a deployment without Admin SDK configuration:

> **Manual suspension is the authoritative immediate control, and it is the
> only one.** Automated offboarding does not run. Disabling the Google account
> still prevents *new* logins, because the OIDC flow cannot complete — but it
> does not by itself revoke an existing Kyber session, device or tenant scope.
> `POST /v1/kyber/workforce/principals/{operator_id}/suspend` (immediate,
> reversible) and `.../offboard` (terminal) are what actually end live access.

`directory_freshness(operator_id)` returns `(fresh, reason)` for the access
dependency:

| Situation | Result |
|---|---|
| Principal unknown | `(False, "principal_unknown")` |
| Principal not active | `(False, "principal_inactive")` |
| Principal holds no privileged capability | `(True, None)` |
| Sync unconfigured, `KYBER_DIRECTORY_SYNC_REQUIRED` off | `(True, "directory_sync_unconfigured")` |
| Sync unconfigured, `KYBER_DIRECTORY_SYNC_REQUIRED` on | `(False, "directory_sync_unconfigured")` |
| Sync configured and overdue | `(False, "directory_stale")` |

"Privileged" means holding any of `kyber.workforce.manage`,
`kyber.role.manage`, `kyber.device.approve`, `kyber.tenant.raw.read`,
`kyber.command.pause`, `kyber.command.rollback` or
`kyber.command.kill_switch` — the capabilities whose misuse cannot be undone by
revoking a session afterwards. Deployments that want the fail-closed posture
unconditionally set `KYBER_DIRECTORY_SYNC_REQUIRED=true`; the default is off so
that a deployment without the Admin SDK still functions rather than denying
every privileged request from day one.

---

## 7. Offboarding funnel

`lifecycle.offboard_principal(operator_id, actor_id=…, reason=…)` is the single
entry point. Removing access is four acts — end the employment record, kill the
sessions, revoke the devices, close the tenant scopes — and doing three of them
is indistinguishable from doing none.

Order is deliberate: the principal is moved to `offboarded` with
`kyber_enabled = False` **first and unconditionally**, so even a fully failed
downstream revocation leaves an operator who cannot authenticate or
re-authorize. The session, device and scope planes are then called through
function-level imports behind `ImportError` guards, and the returned report
names exactly which subsystems were reached:

```json
{
  "operator_id": "op_…",
  "employment_status": "offboarded",
  "revocations": {
    "sessions_revoked": 2,
    "devices_revoked": 1,
    "scopes_revoked": 0,
    "unavailable": [],
    "errors": []
  },
  "complete": true
}
```

A non-empty `unavailable` or `errors` sets `complete: false`, increments
`kyber_offboard_partial_total`, and records the audit event with outcome
`failed`. A partial offboard is never reported as a successful one.

---

## 8. HTTP surface

| Method | Path | Required capability |
|---|---|---|
| GET | `/v1/kyber/auth/login` | none (starts a login) |
| GET | `/v1/kyber/auth/callback` | none (completes a login) |
| POST | `/v1/kyber/auth/logout` | authenticated session |
| GET | `/v1/kyber/me` | authenticated session (`kyber.workforce.self.read`) |
| POST | `/v1/kyber/workforce/invitations` | `kyber.workforce.manage` |
| GET | `/v1/kyber/workforce/invitations` | `kyber.workforce.manage` |
| POST | `/v1/kyber/workforce/invitations/{invitation_id}/revoke` | `kyber.workforce.manage` |
| POST | `/v1/kyber/workforce/invitations/accept` | none (token + verified Google identity) |
| GET | `/v1/kyber/workforce/principals` | `kyber.workforce.manage` |
| GET | `/v1/kyber/workforce/principals/{operator_id}` | `kyber.workforce.manage` |
| POST | `/v1/kyber/workforce/principals/{operator_id}/suspend` | `kyber.workforce.manage` |
| POST | `/v1/kyber/workforce/principals/{operator_id}/offboard` | `kyber.workforce.manage` |
| POST | `/v1/kyber/workforce/principals/{operator_id}/roles` | `kyber.role.manage` |
| DELETE | `/v1/kyber/workforce/roles/{binding_id}` | `kyber.role.manage` |
| POST | `/v1/kyber/auth/bootstrap` | none (gated by §5) |

The three unauthenticated routes are unauthenticated by necessity, not by
oversight: `login` and `callback` *are* the authentication, `accept` is
authenticated by the invitation token plus a completed Google login, and
`bootstrap` runs when there is no principal to authenticate as. Every other
route is gated by `require_kyber_access`. When that dependency is not mounted,
the fallback **denies** — an unmounted authorization layer must never read as
an open one.

---

## 9. Configuration

| Variable | Type | Default | Purpose |
|---|---|---|---|
| `KYBER_GOOGLE_CLIENT_ID` | str | `""` | OAuth client id; also the accepted `aud` |
| `KYBER_GOOGLE_CLIENT_SECRET` | str | `""` | OAuth client secret (backend only) |
| `KYBER_GOOGLE_REDIRECT_URI` | str | `""` | Callback URI; derived from the request when unset |
| `KYBER_GOOGLE_HOSTED_DOMAIN` | str | `""` | When set, the `hd` claim must equal it |
| `KYBER_GOOGLE_DISCOVERY_URL` | str | Google's well-known URL | Discovery document override |
| `KYBER_OIDC_PROVIDER` | str | `google` | `mock` selects `MockOidcProvider` (non-production only) |
| `KYBER_BOOTSTRAP_ENABLED` | bool | `false` | Master gate for the one-time founder bootstrap |
| `KYBER_BOOTSTRAP_FOUNDER_EMAIL` | str | `""` | The only email permitted to bootstrap |
| `KYBER_BOOTSTRAP_FOUNDER_GOOGLE_SUBJECT` | str | `""` | Optional subject pinning; email alone then insufficient |
| `KYBER_DIRECTORY_SYNC_ENABLED` | bool | `false` | Enables Admin SDK reconciliation |
| `KYBER_GOOGLE_ADMIN_ACCESS_TOKEN` | str | `""` | Admin SDK bearer token; required for §6 to do anything |
| `KYBER_DIRECTORY_SYNC_REQUIRED` | bool | `false` | Deny privileged access when the directory cannot be verified |
| `KYBER_DIRECTORY_MAX_AGE_HOURS` | int | `24` | Freshness window before a privileged principal is stale |
| `KYBER_DIRECTORY_SYNC_INTERVAL_SECONDS` | int | `3600` | Reconciliation sweep interval |

---

## 10. Tables

| Table | Contents |
|---|---|
| `olympus_workforce_principals` | One row per Olympus employee. `google_subject` is the identity key |
| `olympus_workforce_invitations` | Single-use invitations; `token_hash` only |
| `olympus_role_bindings` | Principal → role template, optionally environment-scoped and expiring |
| `olympus_capability_grants` | Per-principal `allow`/`deny` overrides; a live `deny` wins |
| `kyber_authentication_events` | Every authentication transition, including the bootstrap marker |

Created by `alembic/versions/20260809_kyber_workforce_identity.py`. No secret is
stored in any of them.
