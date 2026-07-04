---
title: Agentic Provider Connector Framework
slug: connectors/provider-connector-framework
section: architecture
visibility: I
audience: [dev-senior, architect, ai]
status: experimental
since_version: "8.11.0"
source_files:
  - Backend Architecture/aether-backend/services/agentic_observability/provider_framework.py
---

# Agentic Provider Connector Framework

The agentic provider connector framework defines the provider-neutral boundary for
observing delegated external actions. It is observation-only: adapters normalize
accounts, grants, provider actions, external objects, webhooks, and read-only
provider snapshots. They must not execute provider writes, submit requests, sign
provider payloads, post content, trade, settle, revoke access, or custody raw
credentials.

## Core records

The framework models provider data as generic records:

| Record | Purpose |
| --- | --- |
| `ExternalAccountRecord` | Tenant-scoped external account identity. |
| `AuthorizationGrantRecord` | Grant, scopes, credential reference, approval/revocation metadata. |
| `ProviderActionRecord` | Externally observed provider action. |
| `ExternalObjectRecord` | Provider-neutral external object such as `provider=x`, `object_type=post`. |
| `ProviderVerificationRecord` | Provider confirmation, contradiction, or unverified state. |
| `PermissionFinding` | Evidence-backed permission risk recommendation. |

## Verification states

Supported states are:

```text
unverified
runtime_observed
gateway_observed
server_confirmed
provider_confirmed
contradicted
reconciled
verification_expired
```

The evidence precedence order is provider webhook, provider API read, MCP server
response, Aether gateway observation, agent runtime self-report, then derived
inference.

## X reference adapter

`XReferenceAdapter` is the first provider reference. It supports account,
authorization, action, object, webhook, health, and read-only verification
normalization for X-like provider payloads. Graph projection stays provider
neutral (`ExternalAccount`, `AuthorizationGrant`, `ProviderAction`,
`ProviderVerification`) rather than creating provider-specific node types.
