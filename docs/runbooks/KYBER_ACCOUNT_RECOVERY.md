---
title: Runbook — Kyber Account Recovery
slug: runbooks/kyber-account-recovery
section: operations
visibility: I
audience: [ops, security]
status: beta
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 2
source_files:
  - Backend Architecture/aether-backend/services/kyber/identity/bootstrap.py
  - Backend Architecture/aether-backend/services/kyber/identity/invitations.py
  - Backend Architecture/aether-backend/services/kyber/devices/approvals.py
---

# Runbook — Kyber Account Recovery

An operator cannot get into Kyber. Work down this list in order — most cases
resolve at step 1 or 2, and each step is cheaper and less privileged than the
next.

## Triage

Ask the operator what they actually see. The failure reason is returned to them
and is the fastest route to the right branch.

| Symptom / denial reason | Cause | Go to |
|---|---|---|
| Google sign-in itself fails | Google account problem, not Kyber | Google Workspace admin |
| `principal_unknown` | No invitation was ever accepted | §1 |
| `principal_inactive` | Suspended or offboarded | §2 |
| `device_unapproved` — session opens but is restricted | Device pending approval | §3 |
| `device_revoked` / `device_mismatch` | Device revoked, or new browser profile | §3, and `KYBER_DEVICE_LOSS.md` if hardware is gone |
| `device_proof_invalid` | Browser storage cleared, or a different browser profile | §4 |
| `step_up_required` on an action that used to work | Step-up grant expired | §5 |
| `capability_missing` | Role binding changed | §6 |
| `directory_stale` | Directory reconciliation is behind | §7 |
| Nobody can get in at all | See §8 |

## 1. Never onboarded

Issue an invitation (`POST /v1/kyber/workforce/invitations`, requires
`kyber.workforce.manage`). It is single-use, expires within 48 hours, and is
bound to the operator's email. The raw token is shown once — send it over a
channel the operator already controls, not the email the invitation is bound to
alone.

## 2. Suspended or offboarded

Confirm this was intentional before reversing it. A `suspended` principal can be
reactivated; an `offboarded` one cannot and needs a fresh invitation. Either
way the operator must re-enroll a device, because offboarding revoked them.

## 3. Device pending or revoked

The operator authenticates fine but holds a `restricted` session: they can see
Kyber and low-risk aggregates, and nothing else. This is working as designed.
A founder or identity administrator approves the device at `/security/devices`.

**Self-approval is refused**, including for the founder outside the one-time
bootstrap. If the founder's own device is the problem, go to §8.

## 4. Device-proof key missing

The WebAuthn credential still exists but the browser-local proof key is gone —
cleared site data, a new browser profile, a different browser, or a private
window. The credential may even have synced to the machine; that is not enough
by itself, deliberately.

Re-enroll: the operator generates a fresh proof key and the device returns to
`pending` for approval. This is the same path as a new machine, and it is
supposed to be, because from the server's point of view an unproven browser
profile is a new device.

## 5. Step-up expired

Not a fault. Step-up grants last 5–15 minutes by role. The operator re-asserts
with their platform authenticator. If a specific action demands step-up
repeatedly within its window, capture the route and raise a defect — a grant
should be reusable until it expires.

## 6. Capability missing

Check the operator's role bindings at `/security/roles`. A capability that
disappeared is usually a revoked binding, an expired binding, or an explicit
`deny` capability grant — a live `deny` always beats an allowing role template,
so look for one before assuming the template is wrong. Fix the binding rather
than granting a broader template.

## 7. Directory stale

Privileged roles fail closed when directory reconciliation is older than
`KYBER_DIRECTORY_MAX_STALE_HOURS`. Check whether the reconciliation worker is
running under the `maintenance` runtime role and whether the Admin SDK
credentials are valid. Do not raise the staleness threshold to clear the alarm —
that converts a working control into a decorative one.

## 8. Nobody can get in

The founder's device is lost and no other principal can approve a device.

1. **Prefer the emergency root identity.** It is a separate principal with
   separate recovery credentials, a 15-minute maximum session, mandatory
   step-up, and a critical alert on every use. Use it to approve the founder's
   new device, then let it expire. Do not use it for anything else while you
   are in there.
2. **If emergency root is also unavailable**, re-bootstrap. This requires
   operator access to the deployment environment and is deliberately
   heavyweight:
   - confirm the exposure — anyone who can do this can mint a founder,
   - set `KYBER_BOOTSTRAP_ENABLED=true` plus the founder identity variables,
   - understand that bootstrap **refuses to run while any workforce principal
     exists**, so this path requires deciding, explicitly and with a record,
     what happens to the existing principals,
   - complete bootstrap, then set `KYBER_BOOTSTRAP_ENABLED=false` and confirm
     the service refuses a second bootstrap.

Every step of §8 lands in the audit ledger. Write the incident record the same
day; a recovery nobody documented is indistinguishable from a compromise.

## Verification

- The operator reaches `/v1/kyber/me` with the expected `capabilities` and
  `authentication_strength: device_bound`.
- Their device is `approved` with a non-null `approved_by` that is **not**
  themselves.
- The audit ledger carries the recovery path taken.

## Related

- `docs/runbooks/KYBER_DEVICE_LOSS.md`
- `docs/runbooks/KYBER_WORKFORCE_OFFBOARDING.md`
- `docs/BREAK-GLASS-ACCESS.md`
