---
title: Data Classification Policy
slug: archive/audits/data_classification_policy
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Data Classification Policy

**Repository:** Aether
**Date:** 2026-03-25
**Scope:** All data objects, storage backends, graph edges, and ML pipelines

---

## 1. Classification Taxonomy

Aether uses a 7-tier data classification system. Every data object, field, graph edge, and derived artifact must be assigned exactly one classification tier. When an object qualifies for multiple tiers, the highest (most restrictive) tier applies.

| Tier | Label | Examples |
|------|-------|----------|
| 1 | **PUBLIC** | Marketing content, public docs, product descriptions |
| 2 | **INTERNAL** | Internal metrics, operational data, config settings |
| 3 | **CONFIDENTIAL** | Business logic, API contracts, model architectures |
| 4 | **SENSITIVE_PII** | Email, phone, name, address, date of birth |
| 5 | **FINANCIAL** | Account numbers, balances, positions, trades, KYC/KYB records |
| 6 | **REGULATED** | Beneficial ownership, AML/sanctions flags, compliance actions, wallet-to-identity links |
| 7 | **HIGHLY_SENSITIVE** | Raw passwords (never stored), encryption keys, master secrets, SSN/TIN |

---

## 2. Tier Definitions and Handling Rules

### Tier 1 — PUBLIC

| Dimension | Rule |
|-----------|------|
| **Collection rules** | No restrictions; may be collected from any public source |
| **Lawful basis** | Legitimate interest or public domain |
| **Storage rules** | Standard storage; no special requirements |
| **Encryption** | Encryption at rest recommended but not mandatory |
| **Access requirements** | No authentication required for read access |
| **Exportability** | Freely exportable; no approval required |
| **Retention** | Indefinite unless superseded |
| **Deletion behavior** | Standard deletion; no cascading requirements |
| **Training eligibility** | Eligible for all ML training without restriction |
| **External visibility** | Fully visible to external consumers and APIs |
| **Logging/redaction** | No redaction required; standard access logging |

---

### Tier 2 — INTERNAL

| Dimension | Rule |
|-----------|------|
| **Collection rules** | Collected from internal systems and instrumentation |
| **Lawful basis** | Legitimate interest (operational necessity) |
| **Storage rules** | Standard encrypted storage within tenant boundary |
| **Encryption** | AES-256 at rest required |
| **Access requirements** | Authenticated users with VIEWER role or above |
| **Exportability** | Exportable within organization; no external export without review |
| **Retention** | 2 years default; configurable per tenant |
| **Deletion behavior** | Soft delete with 30-day recovery window, then hard delete |
| **Training eligibility** | Eligible for internal model training; excluded from third-party training |
| **External visibility** | Not visible externally; internal dashboards and APIs only |
| **Logging/redaction** | No redaction required; access logged with correlation ID |

---

### Tier 3 — CONFIDENTIAL

| Dimension | Rule |
|-----------|------|
| **Collection rules** | Collected only through authorized internal processes |
| **Lawful basis** | Legitimate interest (business operations) |
| **Storage rules** | Encrypted storage with tenant isolation enforced |
| **Encryption** | AES-256 at rest; TLS 1.3 in transit required |
| **Access requirements** | Authenticated users with EDITOR role or above |
| **Exportability** | Export requires ADMIN approval; encrypted export bundles only |
| **Retention** | 1 year default; configurable per tenant and data type |
| **Deletion behavior** | Soft delete with 14-day recovery window, then hard delete |
| **Training eligibility** | Eligible for internal model training with data review; not eligible for third-party training |
| **External visibility** | Never exposed to external consumers; internal use only |
| **Logging/redaction** | Values redacted in logs; access logged with user ID and correlation ID |

---

### Tier 4 — SENSITIVE_PII

| Dimension | Rule |
|-----------|------|
| **Collection rules** | Collected only with explicit consent for a declared purpose; minimization required |
| **Lawful basis** | Consent (Article 6(1)(a)) or contract performance (Article 6(1)(b)) |
| **Storage rules** | Encrypted storage; pseudonymized where possible; SHA-256 hashing for identifiers used in resolution |
| **Encryption** | AES-256 at rest; TLS 1.3 in transit; field-level encryption for raw values |
| **Access requirements** | EDITOR role or above with active consent verification; field-level masking for VIEWER role |
| **Exportability** | Subject to DSAR export rights; encrypted export with approval workflow; cross-border transfer requires adequacy assessment |
| **Retention** | Duration of consent or contract + 30-day deletion window; configurable per tenant |
| **Deletion behavior** | Cascading deletion across all storage backends, graph edges, derived data, and caches; must complete within GDPR SLA |
| **Training eligibility** | Not eligible for ML training unless explicitly consented for purpose "agent" and anonymized |
| **External visibility** | Never exposed externally; masked in all external-facing responses |
| **Logging/redaction** | All PII values redacted in logs; only hashed identifiers logged; access logged with user ID, correlation ID, and purpose |

---

### Tier 5 — FINANCIAL

| Dimension | Rule |
|-----------|------|
| **Collection rules** | Collected only through verified integrations with financial data sources; explicit consent required |
| **Lawful basis** | Consent (Article 6(1)(a)) or legal obligation (Article 6(1)(c)) |
| **Storage rules** | Encrypted storage with tenant isolation; separate encryption keys per tenant (BYOK where available) |
| **Encryption** | AES-256 at rest with per-tenant keys; TLS 1.3 in transit; field-level encryption mandatory |
| **Access requirements** | ADMIN role only; multi-factor verification recommended; field-level access control enforced |
| **Exportability** | Export requires ADMIN approval + compliance review; encrypted export bundles only; cross-border transfer requires legal review |
| **Retention** | Regulatory minimum (typically 5-7 years for financial records); tenant-configurable within regulatory bounds |
| **Deletion behavior** | Cascading deletion subject to regulatory hold checks; deletion blocked if under legal hold or regulatory retention period |
| **Training eligibility** | Not eligible for ML training; aggregated and anonymized derivatives may be used with compliance approval |
| **External visibility** | Never exposed externally; masked in all responses except to ADMIN with explicit access grant |
| **Logging/redaction** | All financial values redacted in logs; access logged with user ID, correlation ID, purpose, and regulatory justification |

---

### Tier 6 — REGULATED

| Dimension | Rule |
|-----------|------|
| **Collection rules** | Collected only through regulated processes with documented lawful basis; chain of custody required |
| **Lawful basis** | Legal obligation (Article 6(1)(c)) or public interest (Article 6(1)(e)) |
| **Storage rules** | Encrypted storage with tenant isolation; immutable audit trail for all access and modifications; separate storage partition recommended |
| **Encryption** | AES-256 at rest with per-tenant keys; TLS 1.3 in transit; field-level encryption mandatory; key rotation every 90 days |
| **Access requirements** | ADMIN role with explicit regulatory access grant; access logged to immutable audit trail; break-glass procedure for emergency access |
| **Exportability** | Export requires compliance officer approval + legal review; encrypted and signed export bundles; cross-border transfer requires regulatory approval |
| **Retention** | Regulatory minimum as defined by applicable law (AML: 5 years minimum; varies by jurisdiction); not deletable during retention period |
| **Deletion behavior** | Deletion only after regulatory retention period expires; cascading deletion with compliance verification; deletion itself logged to immutable audit |
| **Training eligibility** | Not eligible for any ML training; no derivatives permitted without compliance approval |
| **External visibility** | Never exposed externally; available only to authorized regulatory and compliance roles |
| **Logging/redaction** | All values redacted in logs; access logged to immutable compliance audit trail with user ID, correlation ID, purpose, regulatory justification, and timestamp |

---

### Tier 7 — HIGHLY_SENSITIVE

| Dimension | Rule |
|-----------|------|
| **Collection rules** | Collected only when absolutely necessary; raw passwords must never be stored (hash-only); encryption keys managed through dedicated key management |
| **Lawful basis** | Legal obligation (Article 6(1)(c)) or vital interest; collection must be justified and documented |
| **Storage rules** | Never stored in plaintext; passwords stored as bcrypt/argon2 hashes only; keys stored in HSM or dedicated key vault; API keys stored as SHA-256 hashes only |
| **Encryption** | HSM-backed key management; AES-256 minimum; field-level encryption with dedicated keys; no shared encryption keys across tenants |
| **Access requirements** | SERVICE role only for programmatic access; no human access to raw values; break-glass procedure with multi-party approval for emergency access |
| **Exportability** | Never exportable; no export mechanism exists; break-glass export requires multi-party approval + compliance + security review |
| **Retention** | Minimum necessary duration; encryption keys rotated on schedule (90 days); API keys rotated on compromise or schedule |
| **Deletion behavior** | Cryptographic erasure (destroy encryption keys); immediate and irrecoverable; deletion logged to immutable audit |
| **Training eligibility** | Never eligible for any ML training or analysis; no derivatives permitted |
| **External visibility** | Never exposed in any form; never included in API responses; never logged |
| **Logging/redaction** | Never logged in any form; access events logged without values; all access logged to immutable security audit trail with multi-party notification |

---

## 3. Object-to-Classification Mapping

This table maps every known Aether data object to its classification tier.

| Data Object | Classification | Notes |
|-------------|---------------|-------|
| User profile core | **SENSITIVE_PII** | Name, demographic fields |
| Email/phone | **SENSITIVE_PII** | Stored as SHA-256 hash for identity resolution |
| Device fingerprint | **CONFIDENTIAL** | Browser/device identifiers |
| Wallet address | **CONFIDENTIAL** | Elevated to **REGULATED** when linked to a real identity |
| Session/behavioral events | **INTERNAL** | Clickstream, page views, feature usage |
| Graph edges (observed) | **CONFIDENTIAL** | Edges derived from direct user actions or declared relationships |
| Graph edges (inferred) | **REGULATED** | Edges derived from ML inference or graph algorithms |
| Financial account records | **FINANCIAL** | Account numbers, balances, positions |
| Trade/order/execution | **FINANCIAL** | Order books, execution records, settlement data |
| KYC/KYB records | **REGULATED** | Identity verification documents and results |
| Compliance actions | **REGULATED** | AML flags, sanctions screening results, enforcement actions |
| Beneficial ownership inference | **HIGHLY_SENSITIVE** | Inferred ownership structures linking entities to individuals |
| ML model outputs/scores | **CONFIDENTIAL** | Predictions, risk scores, recommendations |
| Training datasets | **CONFIDENTIAL** | Elevated to **REGULATED** if dataset contains PII features |
| Admin actions/audit logs | **INTERNAL** | Immutable; not deletable; append-only |
| API keys | **HIGHLY_SENSITIVE** | Stored as SHA-256 hash only; raw value never persisted |
| Encryption keys | **HIGHLY_SENSITIVE** | Managed through key vault or HSM; never exposed |
| Support/CRM content | **SENSITIVE_PII** | Customer communications and support tickets |
| Campaign/attribution data | **INTERNAL** | Marketing attribution, UTM parameters, campaign performance |

---

## 4. Classification Enforcement

### Assignment

- Every new data object, field, graph edge, or derived artifact MUST be assigned a classification tier before it enters any storage backend.
- Classification is assigned via policy metadata attached to the object at creation time.
- If no classification is explicitly assigned, the object defaults to **CONFIDENTIAL** and is flagged for review.

### Elevation

- When a data object qualifies for multiple tiers, the highest (most restrictive) tier applies.
- Elevation events (e.g., wallet address linked to identity) must be logged and the classification updated in real time.

### Validation

- All API routes that create, update, or return data objects must validate that the requesting user's role and active consent satisfy the classification tier's access requirements.
- Field-level access control must mask or deny fields that exceed the requester's clearance.

### Audit

- Classification assignments and changes are logged to the immutable audit trail.
- Quarterly reviews of the object-to-classification mapping are required to capture new data objects and reclassifications.
