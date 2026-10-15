---
title: Threat Model
slug: security/threat-model
section: security
visibility: I
audience: [security, architect, dev-senior]
status: beta
since_version: "0.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# Threat Model

A STRIDE-style review of the platform's primary trust boundaries. Living
document; not legal advice.

## Assets

Tenant data + intelligence graph, audit ledger, secrets/keys, billing records,
operator (Kyber) control plane.

## Trust boundaries

Internet → API (auth middleware) · tenant ↔ tenant (isolation) · tenant ↔ Kyber
(operator gate) · platform ↔ external providers/connectors (BYOK vault, signed
webhooks).

## STRIDE highlights + mitigations

| Threat | Vector | Mitigation |
| --- | --- | --- |
| Spoofing | Forged webhook / token | HMAC verify; JWT/API-key auth |
| Tampering | Audit edit | Tamper-evident chained ledger |
| Repudiation | "I didn't do it" | Per-action audit events |
| Info disclosure | Secret/cross-tenant leak | Sanitization, tenant isolation, aggregate-only Kyber |
| DoS | Request floods | Per-plan rate limits + quota |
| Elevation | Tenant → operator | Fail-closed operator gate; break-glass + approval |
| SSRF | Tenant-configured outbound URL (webhook, ticketing/CRM base URL, RPC endpoint, store URL, crawl target) | Every resolved address must be globally routable (mapped/NAT64/6to4/Teredo unwrapped); connection pinned to a validated address (the next validated address is tried only when a connection cannot be established); redirects re-validated or refused, with credentials dropped on a host change or an `https`→`http` downgrade; a resolver failure is retryable, a non-public answer is final |

## Open items

Connector credential rotation cadence and a formal external review — see
[Penetration-Test Readiness](../operations/PENETRATION-TEST-READINESS.md).
