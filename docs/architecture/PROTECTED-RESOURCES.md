---
title: Protected Resources — Registration Guide
slug: commerce/protected-resources
section: operations
visibility: I
audience: [dev-senior, architect, ops]
status: deprecated
since_version: 0.1.0
canonical_owner: backend@aether
estimated_read_minutes: 1
---

# Protected Resources (Retired)

**Status:** retired by [ADR-012](decisions/ADR-012-observation-only-everywhere.md).

Aether used to let a tenant register protected resources that its x402
challenge middleware would gate behind an HTTP 402 payment, with pricing,
approval and entitlement checks. Aether is now observation-only: it does not
gate access to anything. The resource registry, the challenge middleware, the
pricing engine and the `/v1/x402/resources` routes were removed.

A tenant that charges for its own resources with x402 runs that paywall
itself. Its server can report each exchange to `POST /v1/x402/capture`, and
Aether verifies the payment on-chain and records the result. See
[Commerce Control Plane (Retired)](COMMERCE-CONTROL-PLANE.md) for what remains.
