---
title: Compliance Evidence Inventory
slug: compliance/compliance-evidence-inventory
section: compliance
visibility: I
audience: [security, compliance]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Compliance Evidence Inventory

A generated inventory mapping controls → evidence pointers → readiness status,
for **assessment preparation**. Not a certification and not legal advice.

## Generate

```bash
npm run compliance:readiness      # Markdown report
npm run compliance:evidence       # JSON (scripts/compliance/readiness.py --json)
```

`scripts/compliance/readiness.py` enumerates controls (access control, audit
ledger, secrets, retention, reliability, data quality, vuln/secret tooling,
incident response, privacy, threat model, pen-test readiness), checks that each
evidence path exists in the repo, and emits a readiness summary. Every report
carries the disclaimer: *readiness only; not certified; not legal advice;
requires external audit / authorized assessment*.

## Use

- Attach the JSON output to an assessment data room.
- Pair with the audit ledger exports (who/what/when) for control evidence.
- Keep [SOC 2 Readiness](SOC2-READINESS.md) / [GDPR Readiness](GDPR-READINESS.md)
  mappings in sync with the generated inventory.

See [Security Readiness](SECURITY-READINESS.md).
