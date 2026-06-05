---
title: Tenant Data Contamination
slug: data/tenant-data-contamination
section: security
visibility: I
audience: [security, architect, ops, ai]
status: beta
since_version: "8.9.0"
flags:
  - AETHER_DATA_QUALITY_ENABLED
  - KYBER_INTELLIGENCE_QUALITY_ENABLED
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# Tenant Data Contamination

Tenant isolation is a non-negotiable invariant. The contamination detector
watches for records missing `tenant_id`, `tenant_id` mismatches, cross-tenant
identifiers, cross-tenant graph edges, shared integration-config leakage, audit
export scope mismatches, and billing scope mismatches.

## Escalation into Security & Governance

Contamination is not merely a data-quality signal — high/critical contamination
escalates into the Security & Governance audit ledger
(`services/security/audit_ledger.py`) as a
`data_quality_contamination_detected` event, with the `escalated_audit_event_id`
recorded on the originating [Drift Event](DRIFT-DETECTION.md). Low-severity,
auto-corrected signals do not escalate.

Audit metadata is secret-sanitized before persistence — no raw secrets are ever
written to the ledger, logs, exports, or UI.

## Views

Operator contamination summary + escalated events:
`GET /v1/admin/kyber/intelligence-quality/contamination` (aggregate-only,
operator-gated). There is no tenant-facing route that exposes other tenants'
contamination.

See [Tenant Isolation Verification](TENANT-ISOLATION-VERIFICATION.md),
[Security & Governance Controls](SECURITY-GOVERNANCE-CONTROLS.md), and
[Data Quality](DATA-QUALITY.md).
