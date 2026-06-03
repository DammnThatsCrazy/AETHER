---
title: Access Control Review
slug: security/access-control-review
section: security
visibility: I
audience: [security, architect, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Access Control Review

Periodic review process for roles, permissions, and operator access. Builds on
the implemented access-control plane (see [Access Control](ACCESS-CONTROL.md)).

## What to review

- **Tenant roles**: tenant_owner/admin/operator/analyst/viewer/billing_admin/
  security_admin grants vs. least privilege.
- **Olympus roles**: olympus_operator/support/admin/security/revops + auditor —
  who holds the `kyber:operator` grant and operator tenant-id allowlist.
- **Break-glass**: every grant time-boxed, reason-required, approved by a
  different operator, and audited (see [Break-Glass Access](BREAK-GLASS-ACCESS.md)).
- **Cross-tenant**: aggregate-only Kyber views; no `all_tenants_aggregate` grant
  resolves a single tenant's private records.

## Cadence + evidence

Quarterly review (or on role change). Evidence: the audit ledger records access
checks and sensitive allowed/denied decisions; export via the governed audit
export. Feeds [Compliance Evidence Inventory](COMPLIANCE-EVIDENCE-INVENTORY.md).
