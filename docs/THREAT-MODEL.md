---
title: Threat Model
slug: security/threat-model
section: security
visibility: I
audience: [security, architect, dev-senior]
status: beta
since_version: "8.9.0"
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

## Open items

SSRF coverage on outbound dispatch (allowlist), connector credential rotation
cadence, and a formal external review — see
[Penetration-Test Readiness](PENETRATION-TEST-READINESS.md).
