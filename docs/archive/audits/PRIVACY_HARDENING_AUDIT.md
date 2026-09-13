---
title: Privacy Hardening Audit
slug: archive/audits/privacy_hardening_audit
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Privacy Hardening Audit

**Repository:** Aether
**Date:** 2026-03-25
**Scope:** Full-stack privacy, data protection, and tenant isolation controls

---

## 1. Existing Controls Already Present

These controls are production-quality and should be reused as-is or extended.

| # | Control | Location |
|---|---------|----------|
| 1 | API key SHA-256 hashing + Redis async lookup | `shared/auth/auth.py` |
| 2 | JWT with TenantContext extraction | `shared/auth/auth.py` |
| 3 | RBAC with ADMIN/EDITOR/VIEWER/SERVICE roles + permission lists | `shared/auth/auth.py` |
| 4 | Rate limiting via Redis INCR+EXPIRE token bucket | `shared/rate_limit/limiter.py` |
| 5 | BYOK Fernet AES encryption for provider keys | `shared/providers/key_vault.py` |
| 6 | Structured JSON logging with correlation IDs | `shared/logger/logger.py` |
| 7 | Prometheus metrics (http_requests_total, rate_limit_exceeded, etc.) | Various |
| 8 | 6-component extraction defense (rate limit, canary, pattern, noise, watermark, risk score) | Extraction defense module |
| 9 | Consent model with 5 purposes (analytics, marketing, web3, agent, commerce) + immutable audit | Consent module |
| 10 | DSR framework with 6 GDPR rights and SLA tracking | DSR module |
| 11 | PII hashing (SHA-256) for email/phone in identity resolution | Identity resolution module |
| 12 | GDPR/SOC2 compliance module with ROPA, cross-border transfers, audit trail types | Compliance module |

---

## 2. Fragmented Controls

These controls exist in the codebase but are not fully wired, enforced, or integrated.

| # | Finding | Impact |
|---|---------|--------|
| 1 | Consent framework exists but NOT enforced in middleware/service code | Data may be processed without valid consent check at request time |
| 2 | DSR engine documented but cascading deletion is pseudocode only | Subject erasure requests cannot be fully fulfilled |
| 3 | Compliance module is standalone Python, not wired to FastAPI routes | Compliance checks are not enforced at the API boundary |
| 4 | Extraction defense post-response watermarking exists but not called in routes | Extracted data leaves the system without forensic traceability |
| 5 | Tenant isolation works in most places but graph neighbor queries and ProfileResolver miss tenant_id | Cross-tenant data leakage possible through graph traversal and profile resolution |

---

## 3. Non-Production-Ready Areas

These areas have partial implementations that are not safe for production workloads.

| # | Finding | Risk |
|---|---------|------|
| 1 | Graph neighbor queries lack tenant_id filtering | **Critical** — cross-tenant data leakage risk |
| 2 | ProfileResolver.resolve() not tenant-aware | **Critical** — profiles from other tenants may be returned |
| 3 | DSR cascading deletion not implemented | **High** — GDPR Article 17 compliance gap |
| 4 | Consent withdrawal not enforced at processing time | **High** — processing may continue after consent is revoked |
| 5 | No data classification system | **High** — no way to differentiate handling by sensitivity |
| 6 | No field-level access control | **Medium** — all fields visible to all authorized roles |
| 7 | No log redaction for PII | **Medium** — PII may appear in plaintext in logs |
| 8 | JWT HS256 fallback not production-safe | **Medium** — symmetric signing key is a single point of compromise |
| 9 | No per-tenant PII salt | **Medium** — cross-tenant hash correlation possible |
| 10 | Pattern analysis in extraction defense stubbed | **Low** — extraction defense operates without behavioral pattern scoring |

---

## 4. Missing Controls

These controls do not exist in the codebase and must be built.

| # | Missing Control | Category |
|---|----------------|----------|
| 1 | Data classification taxonomy and enforcement | Data Governance |
| 2 | Policy metadata on graph objects/edges | Data Governance |
| 3 | Field-level access control (masking/denial per sensitivity) | Access Control |
| 4 | Training eligibility controls | ML Governance |
| 5 | Graph inference policy boundaries | Data Governance |
| 6 | Retention policies by class/tenant/source | Data Lifecycle |
| 7 | Cross-domain identity linking policy gates | Identity |
| 8 | Lawful basis metadata per data object | GDPR Compliance |
| 9 | Export encryption and approval workflows | Data Transfer |
| 10 | Break-glass access controls | Access Control |
| 11 | Privileged access monitoring | Security Operations |
| 12 | Automated secret rotation | Security Operations |

---

## 5. Ranked Implementation Order

### P0 — Immediate (blocks production readiness)

- Data classification taxonomy and policy metadata model
- Tenant isolation fix for graph neighbor queries and ProfileResolver
- Policy metadata on graph objects and edges

### P1 — High Priority (compliance and access control)

- Field-level access control (masking/denial per sensitivity tier)
- Consent enforcement in middleware and service processing paths
- Log redaction for PII fields

### P2 — Required (regulatory completeness)

- DSAR cascading deletion across all storage backends
- Retention policies by classification, tenant, and source
- Training eligibility controls based on data classification

### P3 — Hardening (defense in depth)

- Graph inference policy boundaries
- Export encryption and approval workflows
- Break-glass access controls
- Audit evidence collection and reporting

---

## 6. Left Untouched (Already Aligned)

The following controls were reviewed and found to be correctly implemented. No changes are needed.

- **API key management** — hashing, Redis lookup, tier-based access
- **Rate limiting implementation** — token bucket, distributed via Redis INCR+EXPIRE
- **BYOK Fernet encryption pattern** — provider key vault with per-tenant encryption
- **Prometheus metrics collection** — request counters, rate limit tracking, latency histograms
- **Consent immutable audit trail model** — append-only consent records with 5 purpose types
- **Middleware auth chain architecture** — JWT extraction, tenant context, RBAC enforcement pipeline
