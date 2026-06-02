---
title: Break-Glass Operator Access
slug: enterprise/break-glass-access
section: enterprise
visibility: I
audience: [ops, security]
status: stable
since_version: "13.0.0"
---

# Break-Glass Operator Access

`BreakGlassService` (`services/security/break_glass.py`) provides time-boxed,
audited, approval-gated emergency access for Olympus operators into a specific
tenant.

## Implemented controls

- **Request** requires a `reason` and a `requested_scope` (`BreakGlassRequest`).
- **Approve / deny** are explicit operator actions; approval sets `starts_at` and
  a time-boxed `expires_at`. Approval is **second-actor only** — the requester
  cannot approve their own request (`approved_by == requested_by` is rejected and
  audited), so break-glass is genuinely approval-gated end to end.
- **Revoke** ends an active grant early; grants **auto-expire** on read once
  past `expires_at` (status → `expired`).
- Every transition (`requested`/`approved`/`denied`/`revoked`/`expired`) and every
  access used under an active grant is written to the audit ledger.
- `AccessControlService` consults active break-glass grants when evaluating
  operator access to a specific tenant — without a grant (or an assigned role),
  operator access to a single tenant's private records is denied.

## Routes

| Method | Path |
|---|---|
| POST | `/v1/admin/kyber/security/break-glass/request` |
| POST | `/v1/admin/kyber/security/break-glass/{request_id}/approve` |
| POST | `/v1/admin/kyber/security/break-glass/{request_id}/deny` |
| POST | `/v1/admin/kyber/security/break-glass/{request_id}/revoke` |
| GET | `/v1/admin/kyber/security/break-glass` |

## Operator access model

Operators default to **aggregate-only** Kyber visibility. Access to a single
tenant's private records requires either an explicit assigned role or an
approved, unexpired break-glass grant. The approve step is human-in-the-loop and
distinct from the requester.

## Planned controls

- Automatic notification to the tenant when break-glass access is exercised.
- Multi-approver (N-of-M) approval for the highest-risk scopes.

## Known gaps / not certified

- Approver separation is enforced at the service level; organizational
  segregation of duties is a deployment policy. No certification is claimed.
