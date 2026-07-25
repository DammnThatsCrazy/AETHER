---
title: Kyber Device Trust
slug: kyber/device-trust
section: kyber
visibility: I
audience: [architect, security, ops]
status: beta
source_files:
  - Backend Architecture/aether-backend/services/kyber/devices/webauthn.py
  - Backend Architecture/aether-backend/services/kyber/devices/device_proof.py
  - Backend Architecture/aether-backend/services/kyber/devices/approvals.py
  - Backend Architecture/aether-backend/services/kyber/devices/risk.py
---

# Kyber Device Trust

Kyber is the Olympus Labs internal operating plane, and it runs on personal
machines. Nobody is issued a corporate laptop, there is no MDM agent, and there
is no device inventory to check a serial number against. That is a deliberate
starting point rather than a gap to apologise for: buying hardware does not make
a machine trustworthy, and organisations that believe it does tend to substitute
an asset register for actual verification.

What Kyber does instead is refuse to treat any device as trusted until **three
independent things** line up. Each is verified on the backend, each is recorded,
and each can be withdrawn.

| # | Factor | Proves | Module |
|---|---|---|---|
| 1 | WebAuthn platform credential, `userVerification: required` | **who** is authenticating | `devices/webauthn.py` |
| 2 | Browser-profile-bound device-proof key (non-extractable ECDSA P-256) | **where from** | `devices/device_proof.py` |
| 3 | Server-issued, second-actor-approved device grant | **permitted** | `devices/approvals.py` |

Missing any one of the three means the device is not usable. There is no
configuration in which two out of three is enough.

## Why the proof key exists: passkeys sync

This is the part that is easy to leave out and expensive to omit.

A platform passkey is not bound to a machine. It is bound to the operator's
**personal platform account**, and the platform replicates it. A credential
enrolled in Chrome on an operator's MacBook will be offered by their second
MacBook, their iPad, and any future device they sign into with the same Apple or
Google account. That replication is a *feature* of passkeys — it is what makes
them survivable when a phone is dropped in a river — and it is entirely outside
Kyber's control.

So a verified WebAuthn assertion answers "is this Alice?" It does **not** answer
"is this Alice's approved machine?" Treating it as if it did would mean that the
moment an operator signs into a new personal laptop, that laptop silently
inherits production access.

The device-proof key closes exactly that gap. The browser generates an ECDSA
P-256 keypair with `extractable: false`, inside one browser profile's storage.
The private half cannot be exported, cannot be read by page script, cannot be
copied to another machine, and does not sync — it can only be *used*, by that
profile, on that machine. Kyber receives the SPKI public half and nothing else.

Every proof is a fresh, server-issued, single-use challenge:

1. The server generates 32 CSPRNG bytes and hands back an opaque `challenge_id`.
2. The browser signs the raw challenge bytes with the non-extractable key.
3. The server consumes the challenge — **deleting it first, then validating** —
   and verifies the ECDSA-SHA256 signature.

Because consumption deletes, a replayed `(challenge_id, signature)` pair fails on
the second attempt whether or not the first succeeded. Challenges expire after
two minutes. Both the WebCrypto fixed-width `r‖s` form and DER signatures are
accepted; nothing else about verification is relaxed.

Consequence: when the synced passkey is presented from a second machine, the
assertion verifies and the operator still gets nothing. That machine is a new
device record — pending, with no proof key — and it stays that way until someone
else approves it.

## The grant, and who may issue one

The grant is the only factor the server can mint or void unilaterally, which
makes it the revocation lever. It is an opaque token delivered as a
`__Host-kyber_device` cookie (`Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`,
**no `Domain` attribute** — the `__Host-` prefix makes the browser enforce all of
that, so a compromised sibling subdomain cannot plant one).

Only `sha256(token)` is ever written to the database. The raw token exists for
the duration of one response and is never persisted, logged or repeatable. A
full dump of `kyber_trusted_devices` therefore cannot be replayed into device
trust.

Approval rules:

* The approver must hold a role template in `DEVICE_APPROVER_TEMPLATE_IDS`.
  Anything else is a `403` and an audit record.
* **Self-approval is refused and audited.** An operator who could approve their
  own device could enroll a machine of their choosing and reach production
  unaccompanied. This mirrors the second-actor rule in
  `services/security/break_glass.py`: the attempt is both blocked *and* written
  to the audit ledger, because a blocked self-approval is precisely the event an
  investigation wants to find.
* The single exception is an explicit bootstrap of the first founder device,
  when by definition no second approver exists. It must be requested explicitly
  and is audited as `kyber.device.self_approval_bootstrap`, never as an ordinary
  approval.
* Grant lifetime comes from the role template's `device_registration_days`,
  clamped by the platform to 1–90 days regardless of what any caller asks for.

Every transition — requested, approved, reapproved, suspended, revoked, renamed
— writes both a `DeviceApprovalEvent` row and an audit-ledger record. All
operations are idempotent.

## Revocation

`revoke_device` marks the device revoked, revokes its proof keys, and calls the
session plane to kill every session bound to that device. If the session plane
is unreachable, the device is revoked anyway and the failure is reported in the
returned record rather than swallowed — a stale session is a bounded problem an
operator can see; a device that quietly stayed trusted is not.

A revoked device's grant hash is deliberately retained, so a presented cookie
still resolves and is denied with a precise `device_revoked` rather than an
ambiguous "unknown device" that would hide an active attempt to use a cancelled
grant.

`is_usable()` returns coarse, caller-safe reasons only — `device_unapproved` or
`device_revoked`, both members of the shared `DenialReason` vocabulary. An
unknown device is reported identically to an unapproved one, so the answer never
confirms that a device id exists. The finer state (pending, suspended, expired,
risk-blocked) lives in the audit ledger and the metric labels, not in the
response. Grant expiry is evaluated lazily at the moment of use, so a lapsed
grant is denied even if no sweep has run.

## Risk signals

`devices/risk.py` is deterministic and explainable, and it does not fingerprint.
It reads four signals that the backend already produces as a by-product of
enforcing the model above, and stores which of them fired in the device's
`metadata`:

* **`counter_regression`** — a WebAuthn assertion reported a signature counter at
  or below the stored one. For an authenticator that maintains a counter this is
  the textbook cloning indicator. The device is marked `suspect`, the event is
  audited with both counter values, and the assertion is rejected.
* **`proof_failure_burst`** — five or more device-proof failures inside ten
  minutes. One failure is noise; a burst is someone trying keys.
* **`approval_state_withdrawn`** — the device is suspended or revoked.
* **`browser_family_changed`** — the coarse browser family (chrome / firefox /
  safari / edge — family only, no version, no platform build) no longer matches
  the family recorded at registration.

Risk only ever escalates. An evaluation never quietly lowers a device back to
`ok`; clearing risk is an operator decision, not something a well-timed request
can achieve by looking normal once. A `blocked` risk state denies the device even
while its approval record still reads `approved`.

## What is never stored

Kyber never receives, and therefore cannot lose:

* the **WebAuthn private key** — it stays in the platform authenticator;
* the **device-proof private key** — non-extractable, inside one browser profile;
* any **biometric template** — Face ID and Touch ID data never leaves the OS
  secure enclave, and the platform only ever tells the browser "verified";
* the **device PIN or passcode**;
* the operator's **Google or Apple account password**;
* the **raw device grant** — only its sha256.

What is stored is a public key, a signature counter, an approval record, a grant
hash, and an event history.

## What this does and does not guarantee

Stated plainly, because overclaiming here would be worse than useless:

**This does not guarantee that a personal device is secure.** No backend control
can. A machine with a keylogger, a malicious browser extension with the right
permissions, or an attacker sitting at an unlocked screen is a machine the
platform cannot save. Device trust reduces the blast radius of those events; it
does not prevent them.

**What is guaranteed:**

* **Cryptographic device binding.** Authority requires a signature from a key
  that cannot leave the enrolled browser profile. A synced credential, a stolen
  cookie, or a copied session on a different machine does not satisfy it.
* **Backend-enforced sessions and authority.** Every decision is made on the
  server. The frontend renders what the backend granted; it never derives
  authority, decodes a token, or maps roles itself.
* **Least privilege.** Role templates cap capability, disclosure level, action
  class and session lifetime independently. Device trust is a precondition for
  authority, not a substitute for it.
* **Immediate revocation.** One write revokes the grant, the proof keys and every
  bound session. Nothing has to expire on its own for access to stop.

## Configuration

| Variable | Purpose |
|---|---|
| `KYBER_WEBAUTHN_RP_ID` | WebAuthn relying-party id (the registrable domain) |
| `KYBER_WEBAUTHN_RP_NAME` | Display name shown by the authenticator |
| `KYBER_WEBAUTHN_ORIGIN` | Expected origin(s); comma-separated |

Outside `AETHER_ENV=local` these fail closed: an unset RP id or origin stops the
ceremony with a 503 rather than falling back to a permissive default. The
`webauthn` library import is likewise guarded — an unavailable library produces a
clear fail-closed error and never a bypass.

## HTTP surface

All routes live under `/v1/kyber/devices` and are guarded by the Kyber access
dependency. If that dependency cannot be imported, the fallback **denies**.

| Method | Path | Capability |
|---|---|---|
| `POST` | `/registration/options` | `kyber.workforce.self.read` |
| `POST` | `/registration/verify` | `kyber.workforce.self.read` |
| `POST` | `/proof/challenge` | `kyber.workforce.self.read` |
| `POST` | `/proof/verify` | `kyber.workforce.self.read` |
| `GET` | `` | `kyber.workforce.self.read` (approvers may target another operator) |
| `POST` | `/{device_id}/approve` | `kyber.device.approve` |
| `POST` | `/{device_id}/suspend` | `kyber.device.approve` |
| `POST` | `/{device_id}/revoke` | `kyber.device.approve` |
| `POST` | `/{device_id}/rename` | `kyber.workforce.self.read` (own device, or approver) |

The approval endpoint is called *from the device being approved* — an approver
authenticates on the operator's machine and approves it there — which is why the
grant lands as a cookie on that response rather than being returned as a token
for someone to forward onward.

## Tests

`tests/security/test_kyber_devices.py` exercises these paths with real
cryptography: genuine P-256 keypairs signing genuine challenges, and WebAuthn
structures verified by py_webauthn itself rather than by a stub. The headline
case has its own test —
`test_synced_passkey_alone_on_a_second_machine_is_denied` — alongside coverage
for challenge replay (both ceremonies), counter regression, self-approval
refusal, non-approver approval refusal, grant-hash-only storage, and idempotent
revocation.
