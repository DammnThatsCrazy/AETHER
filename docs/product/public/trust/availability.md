---
title: Aether Availability and Readiness
slug: security/availability
section: security
visibility: P
audience: [buyer, security, compliance, architect, ops]
status: beta
since_version: "8.12.0"
estimated_read_minutes: 4
toc_depth: 3
canonical_owner: platform@aether
---
# Aether Availability and Readiness
Provider availability, feature flags, credentials, deployment mode, and tenant
configuration determine what is live for a deployment. Documentation or
registry presence alone is not proof that a capability is enabled.
## Public readiness states
- **Available:** the surface is enabled and has current deployment evidence.
- **Gated:** the surface exists but requires configuration, credentials, or a
  plan entitlement.
- **Pilot:** the surface is being validated with a bounded deployment.
- **Unavailable:** the required evidence or dependency is not present.
- **Planned:** the direction is documented but not a current capability.
The public status surface should report service availability separately from
feature and provider readiness. A healthy service does not mean every
connector, lens, or agent capability is live for every tenant.
