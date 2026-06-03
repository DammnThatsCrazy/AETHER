---
title: Secret Scanning
slug: security/secret-scanning
section: security
visibility: I
audience: [security, dev-senior, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 2
---

# Secret Scanning

`scripts/security/secret_scan.py` (`npm run security:secrets`) is a
dependency-free scanner over git-tracked text files. It flags high-confidence
patterns: private-key blocks, AWS access keys, Stripe live keys, Slack tokens,
Google API keys, and long literals assigned to secret-named variables.

```bash
npm run security:secrets              # exit 1 on findings
python scripts/security/secret_scan.py --advisory   # always exit 0
```

- Excludes `*.example`, tests, docs, generated artifacts, and lockfiles; skips
  obvious placeholders (`change-me`, `example`, `placeholder`).
- This is a hygiene aid, **not** a replacement for a dedicated scanner
  (gitleaks / detect-secrets) and platform secret-scanning in CI.

Complements the no-secret-in-logs/exports guarantees in
[Secrets Management](SECRETS-MANAGEMENT.md) and the `sanitize_metadata` /
`redact_config` helpers. See [Security Readiness](SECURITY-READINESS.md).
