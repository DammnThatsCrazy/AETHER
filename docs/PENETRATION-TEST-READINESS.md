---
title: Penetration-Test Readiness
slug: security/penetration-test-readiness
section: security
visibility: I
audience: [security, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Penetration-Test Readiness

Checklist to prepare for a third-party penetration test. Not a test result.

- [ ] Scope + rules of engagement agreed (targets, windows, data handling).
- [ ] Dedicated, isolated test tenant + non-production environment.
- [ ] Test accounts across roles (tenant_viewer … tenant_owner, operator).
- [ ] Auth flows documented (JWT/API key, Auth0/OIDC).
- [ ] Known surfaces enumerated: API (`/openapi.json`), webhooks, connectors,
      Kyber operator routes, file/exports.
- [ ] Rate limits + WAF posture documented so the tester isn't throttled.
- [ ] Logging/alerting confirmed so test traffic is observable.
- [ ] Remediation + retest process agreed; findings tracked to closure.

Focus areas: tenant isolation, operator-gate bypass, SSRF on outbound dispatch,
webhook signature bypass, secret exposure in responses/logs/exports. See
[Threat Model](THREAT-MODEL.md) and [Vulnerability Management](VULNERABILITY-MANAGEMENT.md).
