---
title: Integration Security
slug: enterprise/integration-security
section: enterprise
visibility: I
audience: [ops, security]
status: stable
since_version: "13.0.0"
---

# Integration Security

`IntegrationSecurity` (`services/security/integration_security.py`) hardens the
integration / webhook dispatch surface. **Secrets are never returned by any method
here.**

## Implemented controls

- **Webhook signing** — HMAC signature + timestamp over the payload
  (`sign_payload` / `verify_signature`) with a replay tolerance window.
- **Secret rotation** — `generate_webhook_secret()` issues new secrets; old
  secrets are replaced, never echoed back.
- **Destination safety** — `validate_destination(...)` blocks unsafe targets
  (loopback, private ranges, cloud metadata endpoints) and enforces an optional
  per-tenant allowlist. Hostnames are **resolved** and rejected if any resolved
  address is private/reserved (and rejected fail-closed if they do not resolve),
  so internal-only or DNS-rebinding names cannot bypass the literal-IP guard.
  In async dispatch paths the (blocking) DNS lookup is offloaded to a bounded
  threadpool with a timeout so a slow/wedged resolver never blocks the event
  loop; a timeout is treated as unsafe (fail-closed).
- **Secret redaction** — `redact_config(...)` strips secret-bearing fields from
  any config returned via API/UI.
- **Dispatch safety** — retry-limit enforcement, idempotency-key enforcement, and
  repeated-failure detection.
- **Audit** — integration config changes and dispatch attempts emit
  `SecurityAuditEvent`s.

## Policy hooks

`PolicyEngine` enforces `integration.configure` and `webhook.dispatch_safety`
(including blocking dispatch when an integration is disabled) and `cross_tenant`
prevention.

## Tenant vs Kyber visibility

Tenants see their own integration security status (signing enabled, last rotation,
recent failures — no secrets) on the Aether Security & Governance page. Operators
see aggregate dispatch health in Kyber.

## Planned controls

- Automatic secret rotation on a schedule.
- Outbound egress proxy allowlisting at the network layer.

## Known gaps / not certified

- Destination safety is an application-layer check; production deployments should
  also enforce network egress controls. No certification is claimed.
