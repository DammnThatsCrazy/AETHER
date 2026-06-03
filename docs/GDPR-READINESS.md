---
title: GDPR Readiness
slug: compliance/gdpr-readiness
section: compliance
visibility: I
audience: [security, compliance, exec]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# GDPR Readiness

> **Not a statement of GDPR compliance and not legal advice.** This maps
> existing capabilities to GDPR principles for **readiness**; compliance
> requires legal review, a DPA program, and DPO/counsel sign-off.

## Principle → capability mapping

| GDPR area | Capability | Readiness |
| --- | --- | --- |
| Lawful basis / consent | Consent service + per-purpose gating (SDK `ConsentModule`) | implemented |
| Right of access / portability | Data requests (DSR) handling | implemented |
| Right to erasure | Retention + audit-preserving deletion (`services/security/retention.py`) | implemented |
| Storage limitation | Retention policies per resource type | implemented |
| Integrity / confidentiality | Tenant isolation, secrets vault, audit ledger | implemented |
| Records of processing | Audit ledger + evidence inventory | documented |
| Data minimization | Secret sanitization; no raw secrets in exports | implemented |

## External work required

DPA templates + sub-processor list, data-processing records, breach-notification
procedures, transfer mechanisms (SCCs), and a privacy review with counsel — see
[Privacy Review](PRIVACY-REVIEW.md), [Data Retention Review](DATA-RETENTION-REVIEW.md),
and [Security Readiness](SECURITY-READINESS.md).
