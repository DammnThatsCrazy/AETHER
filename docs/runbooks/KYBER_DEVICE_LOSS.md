---
title: Runbook — Kyber Device Loss
slug: runbooks/kyber-device-loss
section: operations
visibility: I
audience: [ops, security]
status: beta
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 2
source_files:
  - Backend Architecture/aether-backend/services/kyber/devices/approvals.py
  - Backend Architecture/aether-backend/services/kyber/devices/device_proof.py
  - Backend Architecture/aether-backend/services/kyber/sessions/service.py
---

# Runbook — Kyber Device Loss

An operator's enrolled personal machine is lost, stolen, sold, wiped, or simply
replaced. Kyber access is bound to that specific device, so the device record —
not the person — is what gets revoked.

## Severity

| Situation | Severity | First action |
|---|---|---|
| Device stolen, operator holds command capabilities | P0 | Revoke device, then suspend the principal until a new device is approved |
| Device lost, read-only operator | P1 | Revoke device |
| Device replaced or wiped deliberately | P3 | Revoke device, enroll the replacement |

## Why revoking the device is sufficient

Three independent factors gate a Kyber session: a WebAuthn platform credential,
a **browser-profile-bound device-proof key**, and a server-side device grant.
Revoking the device record destroys the grant, so neither a synced passkey on
another machine nor a copied cookie can re-establish authority. The proof key
cannot be exported from the lost machine's browser profile — it was generated
non-extractable — but do not treat that as the control. **The grant revocation
is the control.**

## Procedure

1. **Revoke the device.** `POST /v1/kyber/devices/{device_id}/revoke` with a
   reason, or the Devices page under `/security/devices`. Requires
   `kyber.device.approve`.
   This cascades: every session bound to that device is revoked, and every open
   tenant access scope on those sessions is closed.

2. **Confirm the cascade.** Check `/security/sessions` for the operator — no
   session should remain. If any survives, revoke it directly
   (`POST /v1/kyber/auth/sessions/{session_id}/revoke`) and raise a defect,
   because the cascade is supposed to be automatic.

3. **Assess exposure.** Query `kyber_access_decisions` and the security audit
   ledger for that `device_id` over the window since last known-good possession.
   You are looking for: tenant scopes opened, raw-evidence (D5) disclosures, and
   any command-class action. Record what was reachable, not just what was
   reached.

4. **For a stolen device with command capabilities**, suspend the principal too
   (`POST /v1/kyber/workforce/principals/{operator_id}/suspend`). This is
   reversible and costs the operator an hour; leaving authority live while an
   attacker holds an unlocked machine does not have a reversible failure mode.

5. **Enroll the replacement.** The operator authenticates through Google on the
   new machine, enrolls a WebAuthn credential and a fresh device-proof key, and
   waits for founder approval. There is no shortcut — a second machine always
   requires its own approval, which is the property that made revocation
   sufficient in the first place.

6. **Reactivate** the principal if it was suspended, once the new device is
   approved.

## What not to do

- Do not "transfer" a device record to new hardware. The record binds a public
  key that no longer exists; reusing it would defeat the model.
- Do not raise the operator's role to compensate for the friction of
  re-enrollment.
- Do not skip step 3. The exposure assessment is the part that ends up in the
  incident record.

## Verification

- The device shows `approval_state=revoked` with a `revoked_by` and a reason.
- No `kyber_workforce_sessions` row for the operator has `status=active`.
- No `kyber_access_scopes` row for those sessions has `status=active`.
- `audit_ledger.verify_chain()` still reports `chain_intact: true`.

## Related

- `docs/runbooks/KYBER_ACCOUNT_RECOVERY.md`
- `docs/runbooks/KYBER_WORKFORCE_OFFBOARDING.md`
- `docs/source-of-truth/KYBER_DEVICE_TRUST.md`
