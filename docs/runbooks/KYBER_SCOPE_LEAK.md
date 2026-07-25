---
title: Runbook — Kyber Tenant Scope Leak
slug: runbooks/kyber-scope-leak
section: operations
visibility: I
audience: [ops, security, compliance]
status: beta
canonical_owner: platform@aether
estimated_read_minutes: 7
toc_depth: 2
source_files:
  - Backend Architecture/aether-backend/services/kyber/access/scopes.py
  - Backend Architecture/aether-backend/services/kyber/access/dependencies.py
  - Backend Architecture/aether-backend/services/security/policy_engine.py
---

# Runbook — Kyber Tenant Scope Leak

A suspected or confirmed cross-tenant disclosure through Kyber: an operator saw
one tenant's data while scoped to another, or saw tenant data with no scope at
all.

This is the highest-severity class of Kyber defect. Treat any credible report as
P0 until the evidence says otherwise.

## What "leak" means here

Kyber grants tenant visibility in exactly one way: an active
`kyber_access_scopes` row, bound to the session and device, naming exactly one
tenant, with a purpose and an expiry. Everything above disclosure level D1 must
resolve one. A request whose tenant parameter disagrees with the active scope is
denied with `scope_tenant_mismatch` — it is never silently rescoped.

So a leak is one of:

| Class | Meaning |
|---|---|
| **A — enforcement bypass** | A route returned tenant data without resolving a scope. A code defect. |
| **B — scope confusion** | A scope for tenant X returned data for tenant Y. A code defect. |
| **C — over-disclosure** | The scope was valid but the response exceeded the granted disclosure level (unmasked fields at D2, raw records at D3). A code defect. |
| **D — legitimate but inappropriate** | Enforcement worked; the operator opened a scope they should not have. A process problem, not a code problem. |

Classify before you remediate — the responses are different.

## Immediate actions (first 15 minutes)

1. **Contain.** Revoke the implicated scopes and sessions:
   `DELETE /v1/kyber/scopes/{scope_id}`, then
   `POST /v1/kyber/auth/sessions/{session_id}/revoke`.
   For a suspected class A or B defect affecting a route, set
   `KYBER_BACKEND_AUTHZ_ENFORCED=true` if it is somehow off, and disable the
   implicated feature flag if one exists. Do not deploy a code fix yet.

2. **Freeze the evidence.** `kyber_access_decisions`, `security_policy_decisions`
   and `security_audit_events` are append-only and retained independently of
   session lifetime, so they survive step 1 — but snapshot the relevant window
   now so the investigation is not racing a retention sweep.

3. **Open an incident** with the affected tenant ids listed explicitly. Do not
   generalise to "some tenants".

## Investigation

Every Kyber authorization decision writes a `kyber_access_decisions` row linked
to a `security_policy_decisions` row and an audit-ledger entry. That is the
primary source; the application logs are not.

Establish, in order:

1. **Which decisions were `allowed: true` with `tenant_id` set?** Join to the
   scope via `scope_id`. Any row where the decision's `tenant_id` differs from
   its scope's `tenant_id` is a class B confirmation.
2. **Which allowed decisions have `scope_id IS NULL` at
   `granted_disclosure >= 2`?** Each is a class A confirmation.
3. **Compare `granted_disclosure` against what the route actually returned.**
   A response containing unmasked identifiers under a D2 grant is class C.
4. **For class D**, read the scope `reason`, `purpose` and `ticket_reference`
   and match them against the operator's assigned work.

Verify the ledger itself before relying on it: `audit_ledger.verify_chain()`
must report `chain_intact: true`. Note that the chain head is process-local
module state, so a broken chain across a restart boundary is a known limitation
rather than proof of tampering — say so explicitly in the incident record
rather than escalating on it.

## Remediation by class

**A / B / C — code defect.**
Write a failing test first, in `tests/security/test_kyber_scopes.py`, that
reproduces the exact bypass. It must fail against the current code. Then fix.
The fix belongs in `access/dependencies.py` or the offending route — never in
the test, and never by loosening a validator. Confirm the whole Kyber scope
suite passes, then confirm the specific route denies.

**D — process.**
Revoke the scope, review the operator's role template against what their work
actually requires, and reduce it if the template was broader than the job. Do
not respond to a class D by adding a technical control that would not have
prevented it.

## Tenant notification

Class A, B or C with confirmed disclosure of tenant-identifying or personal data
triggers the tenant notification path in `docs/COMPLIANCE.md` and the data
rights ledger. Class D generally does not, but the compliance owner decides —
not the engineer investigating.

Do not notify from this runbook. Hand the confirmed tenant list and the decision
records to the compliance owner.

## Verification before closing

- A regression test exists that fails without the fix.
- Replaying the offending request now produces `allowed: false` with the right
  `denial_reason`.
- No remaining `kyber_access_decisions` row in the incident window is `allowed`
  with a mismatched or absent scope.
- The affected operator's sessions were revoked and re-established cleanly.
- The incident record names the class, the tenants, the window, and the
  disclosure level actually reached — not the level theoretically reachable.

## Related

- `docs/source-of-truth/KYBER_SESSIONS_AND_SCOPES.md`
- `docs/source-of-truth/KYBER_ACCESS_CONTROL.md`
- `docs/ACCESS-CONTROL.md`
