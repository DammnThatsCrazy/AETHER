---
title: Policy Engine
slug: enterprise/policy-engine
section: enterprise
visibility: I
audience: [ops, security]
status: stable
since_version: "13.0.0"
---

# Policy Engine

`PolicyEngine` (`services/security/policy_engine.py`) evaluates governance
policies, returns `PolicyDecision` records, and writes `SecurityAuditEvent`
records for sensitive decisions. It is a guardrail layered on top of existing
OODA approval flows — it never bypasses them.

## Implemented policies

| Policy key | Behavior |
|---|---|
| `action.dispatch` | Block dispatch unless the decision is `approved`. |
| `action.elevated_dispatch` | Block elevated/critical dispatch when `approval_id` is missing. |
| `cross_tenant.access` | Block tenant access to another tenant's records. |
| `kyber.operator_access` | Block operator tenant access without assigned role or break-glass. |
| `audit_export.create` / `download` | Require export permission; block cross-tenant export; require approval for sensitive export types. |
| `webhook.dispatch_safety` | Block dispatch if integration disabled or destination unsafe (private/loopback/metadata/non-HTTPS). |
| `data.deletion_request` | Block audit-log deletion; require a manifest for cross-resource deletion. |
| `capability.invoke` | Block invocation of a capability that is not in the tenant's observed inventory, that is not attributed to an agent, or that has no active capability authorization. |

`PolicyDecision` carries `allowed`, `reason`, `severity` (`info`/`warning`/`block`),
and an optional `required_action`.

## Tenant vs Kyber visibility

Tenants see their own decisions via `GET /v1/security/policies`. Operators see all
decisions via `GET /v1/admin/kyber/security/policy-decisions`.

## Planned controls

- Externalized, declarative policy definitions (currently code-defined).

## Known gaps / not certified

- No certification is claimed. Policies are code-defined; a policy editor is future
  work.
