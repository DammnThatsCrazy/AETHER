---
title: Security Questionnaire Library
slug: security/security-questionnaire-library
section: security
visibility: I
audience: [security, exec, buyer]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# Security Questionnaire Library

Reusable answers for buyer/vendor security questionnaires. **State facts only;
never claim a certification the repo doesn't hold.** When asked "are you SOC 2 /
GDPR / FedRAMP X?", answer with readiness status + the relevant readiness page.

## Sample answers

- **Tenant isolation?** Yes — enforced platform-wide with an automated isolation
  verifier; Kyber operator views are aggregate-only.
- **Access control?** Role/permission model (tenant + Olympus roles), fail-closed
  operator gate, time-boxed break-glass with approval + audit.
- **Audit logging?** Tamper-evident, chained audit ledger; governed exports.
- **Encryption?** TLS in transit (deployment); secrets encrypted at rest via the
  BYOK vault; no secrets in logs/UI/exports.
- **Secret management?** Vault + sanitization + rotation + secret scanning.
- **SOC 2 / GDPR / FedRAMP?** **Not certified/authorized.** Readiness mapped —
  see [SOC 2 Readiness](SOC2-READINESS.md), [GDPR Readiness](GDPR-READINESS.md),
  [FedRAMP Planning](FEDRAMP-PLANNING.md). Certification requires external audit.
- **Pen test?** Readiness checklist maintained; results shared under NDA when a
  test has been performed.
- **Data deletion / DSR?** Supported + audited; retention policies per resource.

Keep answers current with [Compliance Evidence Inventory](COMPLIANCE-EVIDENCE-INVENTORY.md).
