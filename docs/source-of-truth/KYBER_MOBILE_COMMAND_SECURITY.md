---
title: Kyber Mobile — Command Security Model
slug: kyber/mobile-command-security
section: kyber
audience: [architect, security, mobile, operator]
status: stable
---

# Kyber Mobile — Command Security Model

Kyber Mobile is the **operator companion** — read-only by construction. It
surfaces what a governed action *exists for* and lets an operator elevate a
step-up, but it **never dispatches or verifies a command**. All mutations stay
on the desktop command plane. This document states the security model and the
invariants that keep it honest.

The canonical sources are `services/kyber/ops/*` (command lifecycle,
`_authorize_command`), `services/kyber/sessions/step_up.py` (`StepUpService`),
`services/kyber/devices/mobile_proof_routes.py` (mobile proof keys), and
`services/kyber/ops/mobile_actions.py` (the read-only digest). Related
references: `KYBER_ACCESS_CONTROL.md`, `KYBER_SESSIONS_AND_SCOPES.md`,
`KYBER_DEVICE_TRUST.md`.

## The governed command lifecycle (desktop, canonical)

Commands live at `/v1/kyber/ops/commands/*` and follow a fixed lifecycle:

```
request → dry-run → approve → execute → verify
```

Every transition re-authorizes. `_authorize_command` resolves the access
context against **the command's own capability, action class, and target
tenants** on *every* transition — a scope that lapsed or reopened on another
tenant between request and execute is re-checked, never trusted from the first
request. `tenant_ids` is sourced from the caller's body at request time but
from the **already-stored command row** on later transitions, so the tenant
match is made against the current truth, not the stale request.

Receipts carry a strict status vocabulary:

```
requested · awaiting_approval · approved · dry_run_complete
executing · executed_unverified · verified
failed · rolled_back · cancelled · expired
```

`executed_unverified` is the **honest uncertainty state**: the call returned
but the postconditions were not confirmed. It is *not* `verified`. The UI
renders it as "Not verified" (or "receipt: pending verification"), never
omits it, and never upgrades it.

## The mobile action adapter (read-only)

`GET /v1/kyber/mobile/actions` returns a `MobileActionDigest` — a
**bounded, redacted availability pointer**, composed from the owning services:

- exception queue → `services.kyber.ops.exceptions.exception_service.queue`
- open commands → `services.kyber.ops.commands.command_service.list_commands`
- session step-up → `services.kyber.sessions.step_up.step_up_service`

Each item carries `kind`, `id`, `title`, `severity`, `status`, `action_class`,
`available_action`, `capability_id`, `requires_step_up`, `priority_score`,
`signal_count`, `last_seen_at`.

Invariants:

- **No second command plane.** The digest is an availability pointer, not a
  trigger; there is no mobile dispatch or verify endpoint.
- **No generic mutation channel.** No endpoint names an arbitrary action.
- **`available_action` is presentational** — the next governed lifecycle step
  the item *would* take, never an invocation.
- **No new ranking engine.** Tier0–tier3 grouping reuses the owning services'
  own buckets/statuses; owning-service values pass through bounded and
  redacted only.
- **Read-only by construction.** The only POSTs on the Kyber Mobile surface
  are the governed step-up verify and the proof-key register.

## Step-up

`StepUpService` (`services/kyber/sessions/step_up.py`) issues a challenge,
verifies a **device-bound signature** over it, and grants a short-lived,
single-purpose grant:

- `issue_challenge` → (challenge_id, challenge)
- `_verify` → device-bound P-256 signature over the challenge
- `grant` / `grant_and_rotate` → `StepUpGrant` with a TTL (clamped
  `MIN_STEP_UP_MINUTES=1` … `MAX_STEP_UP_MINUTES=60`, default 5)
- `require_fresh` / `consume` → step-up checks freshness at authorization
  time; a grant is single-use and expires

`requires_step_up` on the digest reflects `action_class in STEP_UP_ACTION_CLASSES
and not step_up_fresh` — the operator sees *before* acting whether a governed
action would demand a fresh step-up.

## Mobile-bound proof keys

`/v1/kyber/mobile/proof-keys` (`POST/GET/DELETE`) lets a phone bind a key its
own Secure Enclave-style holder generates:

- **Same store, same verify path, same key validation** as the browser proof
  path — a key registered here is challenged/verified/risk-scored by the
  *unchanged* `verify_proof`, and every request reuses
  `load_p256_public_key` (base64url SPKI, ECDSA P-256 / ES256 only).
- **One live row per device** — register upserts/replaces in place via
  `find_active_by_device` (the exact lookup `verify_proof` performs); revoke
  is idempotent and sets `revoked_at`, keeping the row for forensics.
- **Redacted inventory** — list never echoes public-key material.
- **404, never 403** — absent *and* foreign `device_id` / `proof_key_id` both
  read as 404, so the surface never confirms another operator's device ids.

The mobile step-up flow uses `ensureProofKey()` / `elevate()` in the app to
register a key and verify a challenge, reusing the same backend challenge path.

## The honest-receipt rule

`verification: null` is rendered as **"Not verified"** — the honest answer,
never omitted. A command whose postconditions could not be confirmed is
`executed_unverified`; nothing on the mobile surface upgrades it.

## Security invariants (summarized)

1. Commands are authorized per capability + action class + tenant on **every**
   transition — never once at request time.
2. Mobile never dispatches, approves, or verifies; dispatch and verify remain
   on the desktop command plane.
3. No generic mutation channel and no endpoint naming arbitrary actions.
4. Step-up is short-lived, single-purpose, device-bound, and re-checked.
5. Proof keys reuse the browser store/verify path — a key bound on mobile is
   protected by the same validation and risk scoring, not a parallel path.
6. No offline mutation; the read-only offline cache has no mutation entry
   point.
7. Receipts are honest: uncertainty is surfaced, never hidden.

## Validators

- `tests/unit/test_kyber_mobile_actions.py` — 12 tests, injected
  collaborators; the route carries `Depends(require_kyber_access(SELF_CAPABILITY))`
  and has no POST/DELETE/PUT.
- `tests/unit/test_kyber_mobile_proof_keys.py` — 11 tests (same-store verify,
  replace-in-place, redacted list, 404-never-403, ES256-only, revoked-not-listed).
- `packages/mobile-core` vitest (46/46) — step-up / proof-key / actions /
  receipts typed methods + pure-TS P256 signer verified against RFC 6979 A.2.5
  and Node crypto.
- Grep-level read-only invariant in the mobile apps — step-up verify / proof-key
  register are the only POSTs on the Kyber Mobile surface.
