---
title: Security Audit Event Ledger
slug: enterprise/audit-event-ledger
section: operations
visibility: I
audience: [ops, security]
status: stable
since_version: "0.1.0"
---

# Security Audit Event Ledger

`AuditLedger` (`services/api/governance/security/audit_ledger.py`) is a tamper-evident trail of
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
- When a ledger write runs inside an authenticated tenant request, it may also
  capture that request's `correlation_id`. The ledger accepts it only when the
  request's resolved tenant and context tenant both match the audit row's
  `tenant_id`, and the value is a printable, bounded string. A present
  correlation ID is part of the v2 integrity hash; absent values are omitted
  from both the stored legacy-compatible row shape and its canonical hash.
- The `/v1/batch` intake route records an `ingestion.batch` event with the
  durable batch ID, outcome counts, and available usage references, then
  returns the actual `auditEventId` when persistence succeeds. The audit write
  is best-effort after intake durability; an absent response ID is not
  synthesized into a receipt or authorization decision.

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
