---
title: Privacy Review
slug: compliance/privacy-review
section: compliance
visibility: I
audience: [security, compliance, exec]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Privacy Review

Privacy posture review. Readiness and pre-positioning only; **not legal advice**
— a formal privacy program requires counsel/DPO sign-off.

## Capabilities

- **Consent**: per-purpose consent capture + gating in the SDK
  (`ConsentModule`: analytics/marketing/web3/agent/commerce) and a consent
  service.
- **Data subject requests**: access, rectification, erasure, portability,
  restriction, objection — handled + audited.
- **Minimization**: secrets sanitized out of metadata/logs/exports; tenant
  isolation prevents cross-tenant exposure.
- **Retention**: per-resource policies — see [Data Retention Review](DATA-RETENTION-REVIEW.md).

## Review checklist

- [ ] Data inventory + processing purposes documented (records of processing).
- [ ] Lawful basis per purpose; consent UX reviewed.
- [ ] Sub-processor list + DPAs (external).
- [ ] Cross-border transfer mechanism (external).
- [ ] Breach notification runbook (see [Incident Response Tabletop](INCIDENT-RESPONSE-TABLETOP.md)).

See [GDPR Readiness](GDPR-READINESS.md).
