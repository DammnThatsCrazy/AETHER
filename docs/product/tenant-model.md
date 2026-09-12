---
title: Tenant Model
slug: product-tenant-model
section: concepts
visibility: P
audience: [dev-senior, architect, security]
status: experimental
since_version: "0.1.0"
---

# Tenant Model

Aether is a multi-tenant platform. Every data path, query, and
projection is scoped to a single tenant. Cross-tenant data
access is architecturally prevented, not policy-gated.

## Isolation Guarantees

- Row-level tenant scoping on all data stores
- Tenant context propagated through every service call
- No shared-state leakage between tenants
- Audit logging per tenant boundary crossing attempt

## Tenant Lifecycle

```
provisioned → active → suspended → deactivated → purged
```

## See Also

- `docs/security/tenant-isolation.md` — Tenant isolation details
- `docs/developer/tenant-setup.md` — Tenant configuration guide
- `docs/product/graph-model.md` — Graph model
