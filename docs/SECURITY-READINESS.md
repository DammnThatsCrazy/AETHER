---
title: Security Readiness
slug: security/security-readiness
section: security
visibility: I
audience: [security, architect, ops, exec]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# Security Readiness

> Readiness and pre-positioning only. **Not certified; not legal advice.** Any
> certification requires an external audit / authorized assessment.

This is the index for Aether's security and compliance **readiness** posture —
implemented controls, evidence mapping, and the tooling/checklists used to
prepare for third-party assessment.

## Implemented controls

- **Tenant isolation** everywhere + an isolation verifier
  (`services/security/isolation_verifier.py`).
- **Access control** (roles/permissions) — see [Access Control Review](ACCESS-CONTROL-REVIEW.md).
- **Break-glass** time-boxed operator access — see [Break-Glass Access](BREAK-GLASS-ACCESS.md).
- **Tamper-evident audit ledger** + governed audit exports.
- **Secrets**: never in logs/UI/exports; vault + sanitization — see [Secrets Management](SECRETS-MANAGEMENT.md), [Secret Scanning](SECRET-SCANNING.md).
- **Webhook signing**, **rate limits**, **data retention**, **DSR handling**.

## Readiness tooling

| Command | Purpose |
| --- | --- |
| `npm run security:secrets` | Dependency-free secret scan (`scripts/security/secret_scan.py`) |
| `npm run security:deps` | `npm audit` + optional `pip-audit` |
| `npm run security:sbom` | SBOM (CycloneDX) where available |
| `npm run security:licenses` | License summary where available |
| `npm run security:audit` | secrets + deps |
| `npm run compliance:readiness` | Readiness inventory (`scripts/compliance/readiness.py`) |
| `npm run compliance:evidence` | Machine-readable evidence inventory (JSON) |

## Framework readiness pages

[SOC 2 Readiness](SOC2-READINESS.md) · [GDPR Readiness](GDPR-READINESS.md) ·
[FedRAMP Planning](FEDRAMP-PLANNING.md) · [Threat Model](THREAT-MODEL.md) ·
[Penetration-Test Readiness](PENETRATION-TEST-READINESS.md) ·
[Vulnerability Management](VULNERABILITY-MANAGEMENT.md) ·
[Logging Review](LOGGING-REVIEW.md) ·
[Incident Response Tabletop](INCIDENT-RESPONSE-TABLETOP.md) ·
[Data Retention Review](DATA-RETENTION-REVIEW.md) ·
[Privacy Review](PRIVACY-REVIEW.md) ·
[Security Questionnaire Library](SECURITY-QUESTIONNAIRE-LIBRARY.md) ·
[Compliance Evidence Inventory](COMPLIANCE-EVIDENCE-INVENTORY.md).
