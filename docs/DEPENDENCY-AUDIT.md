---
title: Dependency Audit
slug: security/dependency-audit
section: security
visibility: I
audience: [security, dev-senior, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 2
---

# Dependency Audit

## Commands

```bash
npm run security:deps        # npm audit --omit=dev + optional pip-audit
npm run security:sbom        # CycloneDX SBOM → sbom.json (if tool available)
npm run security:licenses    # license summary (if license-checker available)
```

- **JS**: `npm audit` over workspaces. Address high/critical; pin or upgrade.
- **Python**: `pip-audit` (optional install) against the installed environment.
- **SBOM / licenses**: generated via `npx` tools where present; the scripts log
  a notice and exit cleanly if the tool is unavailable (so they never break CI).

## Cadence

Run in CI (advisory) and before releases. Track findings to closure in
[Vulnerability Management](VULNERABILITY-MANAGEMENT.md). License review feeds the
[Compliance Evidence Inventory](COMPLIANCE-EVIDENCE-INVENTORY.md).
