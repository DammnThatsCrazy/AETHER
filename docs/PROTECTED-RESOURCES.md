---
title: Protected Resources — Registration Guide
slug: commerce/protected-resources
section: kyber
visibility: I
audience: [dev-senior, architect, ops]
status: stable
since_version: "8.9.0"
canonical_owner: backend@aether
estimated_read_minutes: 8
---

# Protected Resources — Registration Guide

A **Protected Resource** is any API endpoint, agent tool, service plan, or priced
capability that requires an x402 payment or active entitlement for access. Resources
are registered per-tenant in the `ProtectedResourceRegistry` and are the entry point
for the entire commerce control plane.

## Resource Classes

| Class | Description | Typical TTL |
|---|---|---|
| `api` | REST endpoint charged per-call | 60–900 s |
| `agent_tool` | Agent-invocable tool/function | 300 s |
| `priced_endpoint` | Metered streaming/batch endpoint | 60 s |
| `service_plan` | Subscription plan (monthly/annual) | 30 days |
| `internal_capability` | Internal platform capability with cost accounting | varies |

## Registration

### Via API (programmatic)

```http
POST /v1/x402/resources
Authorization: Bearer <token>
x-tenant-id: <tenant>
Content-Type: application/json

{
  "name": "ML Inference API",
  "resource_class": "api",
  "path_pattern": "/v1/ml/predict",
  "owner_service": "ml",
  "description": "Per-call ML inference",
  "price_usd": 0.10,
  "accepted_assets": ["USDC"],
  "accepted_chains": ["eip155:8453", "solana:mainnet"],
  "approval_required": true,
  "entitlement_ttl_seconds": 900
}
```

Required scope: `resources:admin`.

### Via Kyber (UI)

Navigate to **Command → Resources** and click **Register Resource**. Fill in the
resource class, pricing, and accepted payment rails. Changes are audited.

### Via seed (development)

```http
POST /v1/x402/resources/seed
```

Seeds deterministic fixtures for local development. Not available in production.

## Path Pattern Matching

`path_pattern` is matched by `ChallengeMiddleware` and `ControlPlane.find_by_path()`.
Patterns support exact matches and suffix wildcards:

```
/v1/ml/predict          # exact
/v1/agent/tools/*       # suffix wildcard
/v1/data/stream?*       # query string ignored
```

Overlapping patterns are resolved by **specificity** (longer patterns win).
Ambiguous registrations are flagged by `ProtectedResourceRegistry.validate()`.

## Pricing & Assets

Each resource declares a `price_usd` (USD anchor price) and accepted stablecoin
assets + chains. The pricing service converts at settlement time using the
configured exchange rate. See [Stablecoin Rails](STABLECOIN-RAILS.md).

To update pricing without re-registering:

```http
PATCH /v1/x402/resources/{resource_id}
{ "price_usd": 0.05 }
```

## Approval Gate

Every resource has `approval_required: bool`. At GA (Day-1) **all resources have
mandatory approval** enforced by `MandatoryApprovalPolicy`. This cannot be
disabled tenant-side; only platform operators can override via the platform
policy tier.

When `approval_required: true`:
1. Challenge is issued (HTTP 402)
2. Policy engine routes to `require_approval` outcome
3. Approval queue receives the request
4. Human approver decides
5. Only after `approved` is authorization and settlement attempted

See [Approval Model](APPROVAL-MODEL.md) for the full decision flow.

## Entitlement TTL

`entitlement_ttl_seconds` controls how long a paid entitlement grants access before
the payment flow must repeat. Typical values:

| Use case | TTL |
|---|---|
| Single API call | 60 s |
| Agent session | 900 s |
| Daily access | 86400 s |
| Monthly plan | 2592000 s |

SIWX (Sign-In With X) users can reuse entitlements across requests within the TTL
without re-paying. See `IdempotencyStore` and `siwx_binding` field on `Entitlement`.

## Active / Inactive Resources

Resources can be deactivated without deletion:

```http
PATCH /v1/x402/resources/{resource_id}
{ "active": false }
```

Inactive resources return 404 at challenge time. Re-activate by setting `active: true`.

## Graph Writes

Each registered resource creates a `ProtectedResource` vertex in the graph.
Subsequent commerce events (challenges, approvals, settlements, entitlements) are
linked via `REQUIRES_PAYMENT`, `GRANTS_ACCESS_TO`, and `ACCEPTS_ASSET` edges.

Use `GET /v1/x402/resources/{id}/policy` to inspect the active policy chain for a
resource, and `GET /v1/intelligence/commerce/lifecycle/{challenge_id}` for full
lifecycle traces.

## Diagnostic Queries

| Endpoint | Purpose |
|---|---|
| `GET /v1/diagnostics/commerce/verification-failures` | Recent payment failures |
| `GET /v1/diagnostics/commerce/reconciliation-drift` | Intents with no settlement |
| `GET /v1/x402/resources/{id}/policy` | Active policy chain |
