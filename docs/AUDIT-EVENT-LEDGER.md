---
title: Security Audit Event Ledger
slug: enterprise/audit-event-ledger
section: enterprise
visibility: I
audience: [ops, security]
status: stable
since_version: "13.0.0"
---

# Security Audit Event Ledger

`AuditLedger` (`services/security/audit_ledger.py`) is a tamper-evident trail of
sensitive governance actions, persisted via `SecurityAuditEventRepository`.

## Implemented controls

- `record_event(...)` writes a `SecurityAuditEvent` after **sanitizing metadata**
  (no secrets — keys/values matching credential patterns are dropped or redacted).
- Each event is assigned an `integrity_hash` chained to the previous event for the
  same tenant (`compute_integrity_hash`), so deletion or reordering is detectable.
  The hash covers the persisted "what / from where" detail too — `metadata`
  (post-sanitization), `ip_address`, and `user_agent` — so editing those fields
  also breaks `verify_chain()`. A global verification tracks a **separate previous
  hash per tenant**, so independent per-tenant chains each verify correctly.
- **Backward compatibility:** events recorded before the detail fields were part
  of the canonical form (v1) are still verified. `verify_chain()` accepts either
  the v2 (detail-inclusive) or v1 (legacy) hash for each row, so untouched
  historical events do not show as broken after the canonical shape changed,
  while tampering with current (v2) events is still detected.
- Events capture `actor_id`, `actor_type` (`tenant_user`/`olympus_operator`/
  `system`/`agent`), `event_type`, `resource_type`/`resource_id`, `action`,
  `outcome` (`allowed`/`blocked`/`failed`), optional `policy_decision_id`,
  `ip_address`, `user_agent`, and `created_at`.

## What gets audited

Permission checks and policy decisions (via `PolicyEngine`/`AccessControlService`),
audit-export create/download, integration config changes and dispatch attempts,
break-glass request/approve/deny/revoke/expire and every access used under an
active grant, and data retention / data-request lifecycle transitions.

## Tenant vs Kyber visibility

- Tenants read only their own events: `GET /v1/security/audit-events`.
- Operators read across tenants in Kyber: `GET /v1/admin/kyber/security/audit-events`.

## Planned controls

- External WORM/append-only sink export for long-term retention.
- Per-event signing with a rotating service key (current hash chain is integrity,
  not non-repudiation).

## Known gaps / not certified

- The integrity hash detects tampering of stored events; it is not an externally
  notarized signature. No certification is claimed.
- Audit coverage is centered on governance-owned flows and the new security
  routes; non-governance services emit events where hooks are cheap, not
  universally.
