---
title: Runbook — Kyber Workforce Offboarding
slug: runbooks/kyber-workforce-offboarding
section: operations
visibility: I
audience: [ops, security, compliance]
status: beta
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 2
source_files:
  - Backend Architecture/aether-backend/services/kyber/identity/lifecycle.py
  - Backend Architecture/aether-backend/services/kyber/identity/principals.py
  - Backend Architecture/aether-backend/services/kyber/identity/directory_sync.py
---

# Runbook — Kyber Workforce Offboarding

An Olympus Labs operator leaves, changes role, or must lose access immediately.

## The honest picture of automation

Kyber reconciles against Google Workspace when the Admin SDK is configured
(`KYBER_DIRECTORY_SYNC_ENABLED`). When it is, suspending the Google account
propagates to Kyber on the next reconciliation pass and on the operator's next
login attempt.

**When the Admin SDK is not configured, nothing propagates.** Kyber has no way
to learn that a Google account was suspended, and the operator's existing
session and device grant keep working until they expire on their own. In that
configuration, the manual suspension in step 2 below is not a belt-and-braces
extra — it is the control. Treat it as mandatory.

Either way, do not rely on Google suspension alone for an urgent offboard. Kyber
suspension is immediate and does not depend on an external system being
reachable.

## Severity

| Situation | Severity | Order of operations |
|---|---|---|
| For-cause termination, operator holds command capabilities | P0 | Kyber suspend first, Google second |
| Planned departure | P2 | Either order, same day |
| Role change (reduced scope) | P3 | Revoke the role binding; do not offboard |

For a for-cause departure, suspend in Kyber **before** suspending Google.
Suspending Google first can leave a live Kyber session running against a
directory Kyber can no longer query.

## Procedure

1. **Decide: suspend or offboard.**
   `suspended` is reversible and keeps the principal for audit continuity.
   `offboarded` is terminal. Use `suspended` for anything that might be undone
   within the week, including investigations.

2. **Suspend in Kyber.**
   `POST /v1/kyber/workforce/principals/{operator_id}/suspend` with a reason, or
   `/security/workforce`. Requires `kyber.workforce.manage`.
   This runs the single offboarding funnel, which:
   - revokes every Kyber session for the principal,
   - revokes every device grant and WebAuthn credential,
   - closes every open tenant access scope,
   - cancels pending step-up grants,
   - disables role bindings and capability grants,
   - writes an audit record for each of the above.

   The response carries a structured report of exactly what was revoked. Read
   it — do not assume.

3. **Suspend the Google Workspace account.** This removes the identity itself,
   so even a restored Kyber principal could not authenticate.

4. **Confirm.** Re-read the principal: `employment_status` is `suspended` or
   `offboarded`, `kyber_enabled` is false. Confirm zero active sessions, zero
   active scopes, zero approved devices.

5. **Reassign anything owned.** Open incidents, pending approvals, and scheduled
   commands attributed to the operator need a new owner. Kyber does not
   reassign these automatically; leaving them attributed to a suspended
   principal blocks approvals that require a live second actor.

6. **Offboard when the retention window allows.**
   `POST /v1/kyber/workforce/principals/{operator_id}/offboard`. The principal
   record and every audit, decision and authentication event it produced are
   **retained** — offboarding removes authority, not evidence.

## Reduced scope, not departure

Do not offboard for a role change. Revoke the specific role binding
(`DELETE /v1/kyber/workforce/roles/{binding_id}`) and bind the new template.
Capability changes rotate the operator's session so the reduced authority takes
effect on the next request rather than at the next login.

## Verification

- `GET /v1/kyber/workforce/principals/{operator_id}` → `employment_status` as
  intended, `kyber_enabled: false`.
- No active row in `kyber_workforce_sessions`, `kyber_access_scopes`,
  `kyber_step_up_grants` for the operator.
- Every `kyber_trusted_devices` row for the operator is `revoked`.
- The security audit ledger carries the full transition set and
  `verify_chain()` reports `chain_intact: true`.
- A login attempt with the operator's Google identity is denied with
  `principal_inactive`.

## Related

- `docs/runbooks/KYBER_DEVICE_LOSS.md`
- `docs/runbooks/KYBER_ACCOUNT_RECOVERY.md`
- `docs/source-of-truth/KYBER_WORKFORCE_IDENTITY.md`
