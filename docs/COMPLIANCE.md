---
title: Compliance Framework — GDPR & SOC 2
slug: compliance/overview
section: compliance
visibility: C
audience: [compliance, security, buyer, exec]
status: stable
since_version: "8.8.0"
source_files:
  - GDPR & SOC2/aether-compliance/README.md
  - GDPR & SOC2/aether-compliance/main.py
  - GDPR & SOC2/aether-compliance/gdpr/
  - GDPR & SOC2/aether-compliance/soc2/
  - GDPR & SOC2/aether-compliance/policies/
canonical_owner: compliance@aether
estimated_read_minutes: 12
toc_depth: 3
last_synced_commit: 828e055
---

# Compliance Framework — GDPR & SOC 2

This page describes Aether's compliance posture, data-protection controls, and
the automated framework (`GDPR & SOC2/aether-compliance/`) that operationalises
those obligations. It is intended for customers evaluating Aether and for
internal compliance and security teams.

## GDPR

### Privacy-by-design controls (Article 25)

Seven data-protection controls are applied at ingestion and storage:

| Control | Mechanism |
|---------|-----------|
| IP anonymisation | Last octet (IPv4) / last 80 bits (IPv6) zeroed before any persistence |
| Event vectorisation | High-cardinality identifiers replaced with opaque vectors for ML pipelines |
| Pseudonymisation | User IDs replaced with rotating pseudonyms in analytics exports |
| Data minimisation | Only fields listed in the active consent record are forwarded to sinks |
| Retention enforcement | Automated deletion jobs enforce per-purpose retention windows |
| Access logging | Every read of personal data generates an immutable audit record |
| Encryption at rest | All personal data encrypted with customer-managed KMS keys in production |

### Consent purposes

Aether recognises five consent purposes aligned with GDPR Article 6 and the
platform's event schema:

| Purpose key | Description | Default |
|-------------|-------------|---------|
| `analytics` | Behavioural analytics and product telemetry | opt-in |
| `marketing` | Marketing communications and retargeting | opt-in |
| `web3` | On-chain activity tracking and wallet analytics | opt-in |
| `agent` | AI agent interaction logging | opt-in |
| `commerce` | Transaction processing and payment telemetry | required for commerce features |

Consent state is stored per-user, per-purpose in DynamoDB with a full audit log
of changes. A consent withdrawal immediately suppresses the relevant event types
from all downstream sinks.

### Data subject rights (Articles 15–21)

| Right | Article | SLA |
|-------|---------|-----|
| Access | 15 | 30 days |
| Erasure ("right to be forgotten") | 17 | 30 days |
| Portability | 20 | 30 days |
| Restriction | 18 | Immediate |
| Objection | 21 | Immediate |
| Rectification | 16 | 30 days |

DSR requests are submitted through the customer portal. The compliance framework
automates discovery and deletion across all six data stores (Neptune, RDS,
ElastiCache, S3, OpenSearch, DynamoDB). Portability exports are generated as
NDJSON and made available for download within the SLA window.

### Data breach response

Aether's breach response pipeline follows an 8-step process with a 72-hour
supervisory authority notification target (GDPR Article 33):

1. Detection (automated alert or manual report)
2. Initial triage and severity classification
3. Containment — isolate affected systems
4. Evidence preservation — snapshot logs, disable rotation
5. Impact assessment — identify affected data subjects and categories
6. Notification decision — assess whether Article 33/34 thresholds are met
7. Supervisory authority notification (if required, within 72 hours of detection)
8. Data subject notification (if required, without undue delay)

The runbook is maintained in `GDPR & SOC2/aether-compliance/gdpr/breach_response.py`.

### Data Protection Impact Assessments

Two DPIAs are currently pending completion:

- **ML Predictions DPIA** — covers the profiling and automated decision-making
  involved in the ML inference pipeline
- **Identity Resolution DPIA** — covers the Neptune knowledge-graph process that
  links anonymous sessions to identified users

Neither ML inference nor identity resolution is blocked by these DPIAs; the
assessments are in progress and being tracked in the compliance backlog.

### Record of Processing Activities

Nine processing activities are documented in the ROPA:

| Activity | Legal basis | Retention |
|----------|-------------|-----------|
| Analytics event collection | Consent (Art. 6.1.a) | 13 months |
| Marketing communications | Consent (Art. 6.1.a) | Until withdrawal |
| Identity resolution | Legitimate interest (Art. 6.1.f) | 24 months |
| Commerce transactions | Contract (Art. 6.1.b) | 7 years |
| AI agent interactions | Consent (Art. 6.1.a) | 12 months |
| Web3 wallet activity | Consent (Art. 6.1.a) | 24 months |
| Security audit logs | Legal obligation (Art. 6.1.c) | 7 years |
| Support communications | Contract (Art. 6.1.b) | 3 years |
| Employee data | Contract / Legal obligation | Duration of employment + legal minimum |

### Generated policy documents

The compliance framework generates six policy documents from canonical source
data at `GDPR & SOC2/aether-compliance/policies/`:

- Privacy Policy
- Cookie Policy
- Data Processing Agreement (DPA) template
- Sub-processor list
- Retention Schedule
- Data Subject Rights procedure

These documents are regenerated whenever the underlying consent configuration
or ROPA changes.

## SOC 2

### Readiness status

As of the current implementation, Aether has achieved **97.1% SOC 2 readiness**
(32 of 34 controls fully implemented). Two controls are partially implemented:

| Control ID | Description | Status |
|------------|-------------|--------|
| CC-3.2 | Penetration testing — evidence of scheduled third-party pentest | Partial — pentest scheduled, report not yet received |
| A-3.2 | Business continuity tabletop exercise — documented results | Partial — exercise scheduled, documentation in progress |

A SOC 2 Type II report has not yet been issued. Customers requiring a Type II
report should contact `compliance@aether` for current status and timeline.

### Control categories

The 34 controls are distributed across the five Trust Service Criteria:

| Category | Controls | Implemented |
|----------|---------|-------------|
| Security (CC) | 18 | 17 |
| Availability (A) | 6 | 5 |
| Confidentiality (C) | 4 | 4 |
| Processing Integrity (PI) | 3 | 3 |
| Privacy (P) | 3 | 3 |

### Key security controls

- Logical access managed via SSO (Okta) with MFA required for all staff
- Production access requires a time-limited access request and generates an audit record
- Quarterly access reviews — unused accounts deprovisioned within 5 business days of review
- Security awareness training required annually for all staff
- Vulnerability management: critical CVEs remediated within 24 hours, high within 7 days
- Incident response retainer in place with a qualified IR firm

## Compliance automation

The compliance framework is implemented in Python at `GDPR & SOC2/aether-compliance/`.

| Module | Purpose |
|--------|---------|
| `gdpr/consent_manager.py` | Consent record read/write with audit log |
| `gdpr/dsr_processor.py` | Automated DSR discovery and deletion across all stores |
| `gdpr/breach_pipeline.py` | Breach detection integration and 8-step workflow |
| `gdpr/ropa.py` | ROPA record management and export |
| `soc2/evidence_collector.py` | Automated evidence collection for SOC 2 controls |
| `soc2/control_tester.py` | Continuous control testing with pass/fail verdicts |
| `policies/generator.py` | Policy document generation from canonical config |
| `audit/audit_logger.py` | Immutable audit log writer (append-only DynamoDB table) |

Control test results are written to a DynamoDB table and surfaced in the customer
portal compliance dashboard. Failed controls generate PagerDuty alerts to the
`compliance@aether` team.
