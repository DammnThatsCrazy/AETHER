---
title: Developer Security and Privacy
slug: developers/security-and-privacy
section: developer
visibility: P
audience: [dev-senior, architect, security, compliance]
status: stable
since_version: "8.12.0"
estimated_read_minutes: 5
toc_depth: 3
canonical_owner: security@aether
---
# Developer Security and Privacy
Build integrations so that evidence can be connected without widening tenant
scope or hiding the conditions under which a perspective was created.
## Integration requirements
- authenticate requests with the deployment's approved mechanism;
- sign and verify webhooks;
- never place secrets in browser-visible code or event payloads;
- keep tenant identifiers and source identifiers explicit;
- redact or minimize personal data when the contract permits it;
- preserve consent, provenance, and retention context; and
- handle unavailable, denied, stale, and quarantined states explicitly.
Review the [Aether Security and Trust](/doc/product/security-and-trust) page for
the product boundary and the API references for the exact request contracts.
Formal certification, residency, and procurement commitments are deployment-
specific and must be confirmed through the trust and procurement process.
