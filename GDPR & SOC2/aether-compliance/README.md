# Aether Compliance Framework v8.8.0

**GDPR Compliance & SOC 2 Type II Readiness Framework**

A comprehensive, code-driven compliance framework that implements GDPR data protection controls, data subject rights, consent management, breach notification procedures, and SOC 2 Type II trust criteria assessment for the Aether platform. Aether operates as a **Data Processor** (GDPR Art. 28) on behalf of customers who act as **Data Controllers**, responsible for obtaining end-user consent and providing privacy notices.

---

## Table of Contents

- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Framework Overview](#framework-overview)
  - [GDPR Compliance](#gdpr-compliance)
  - [SOC 2 Type II Readiness](#soc-2-type-ii-readiness)
  - [Audit Infrastructure](#audit-infrastructure)
  - [Policy Documents](#policy-documents)
  - [Testing](#testing)
- [Module Reference](#module-reference)
- [Configuration Reference](#configuration-reference)
- [License](#license)

---

## Architecture

```
+----------------------------------------------------------------------+
|                      Aether Compliance Framework                     |
+----------------------------------------------------------------------+
|                                                                      |
|  +-----------------------------+   +------------------------------+  |
|  |         GDPR (Art. 25)      |   |     SOC 2 Type II            |  |
|  |  +-----------------------+  |   |  +------------------------+  |  |
|  |  | Data Protection (x7)  |  |   |  | Trust Criteria (x5)    |  |  |
|  |  | DSR Engine (Art.15-21)|  |   |  | Gap Analyzer (x2 rem.) |  |  |
|  |  | Consent Manager       |  |   |  | Compliance Monitor(x18)|  |  |
|  |  | Breach Handler (72h)  |  |   |  +------------------------+  |  |
|  |  | ROPA Engine (Art. 30) |  |   +------------------------------+  |
|  |  | Cross-Border (Ch. V)  |  |                                     |
|  |  +-----------------------+  |   +------------------------------+  |
|  +-----------------------------+   |     Audit Infrastructure     |  |
|                                    |  +------------------------+  |  |
|  +-----------------------------+   |  | 5 Trail Types          |  |  |
|  |      Policy Generator       |   |  | Quarterly IAM Reviews  |  |  |
|  |  6 compliance documents     |   |  | Auto-Remediation       |  |  |
|  +-----------------------------+   |  +------------------------+  |  |
|                                    +------------------------------+  |
|  +----------------------------------------------------------------+  |
|  |                   Central Configuration                        |  |
|  |  Roles | Rights | Controls | Consent | Data Stores | Criteria  |  |
|  |  Audit Trails | Breach Config | ROPA | Cross-Border Transfers  |  |
|  +----------------------------------------------------------------+  |
|                                                                      |
|  +----------------------------------------------------------------+  |
|  |              Test Suite  (22 checks / 6 groups)                |  |
|  +----------------------------------------------------------------+  |
+----------------------------------------------------------------------+
         |                    |                      |
   Neptune / Timescale   DynamoDB / S3       SageMaker / OpenSearch
   ElastiCache (Redis)   CloudTrail          AWS KMS
```

---

## Tech Stack

| Component | Requirement |
|-----------|-------------|
| Python    | >= 3.9      |
| Build     | setuptools >= 68.0, wheel |
| Optional  | `boto3 >= 1.28` (AWS integration) |
| Dev       | `pytest >= 7.0`, `pytest-cov` |

---

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd aether-compliance

# Install in development mode
pip install -e ".[dev]"

# Or install with AWS integration
pip install -e ".[aws,dev]"
```

No external dependencies are required for the core framework. All compliance logic runs with the Python standard library alone.

---

## Quick Start

```bash
python3 main.py
```

This executes the full compliance framework demo, exercising all modules in sequence:

1. GDPR Data Protection by Design (Art. 25)
2. Data Subject Rights processing (Art. 15-21)
3. Consent management lifecycle
4. Breach notification simulation (Art. 33/34)
5. Record of Processing Activities + Cross-border transfers (Art. 30 / Ch. V)
6. SOC 2 Trust Criteria assessment (5 criteria, 34 controls, **97.1% readiness**)
7. SOC 2 Controls Remediation — evidence artifacts for all 9 closed gaps
8. Gap analysis — 2 remaining partial gaps (CC-3.2, A-3.2)
9. Continuous compliance monitoring (18 automated checks)
10. Audit trail logging and evidence generation
11. Quarterly IAM access review with auto-remediation
12. Policy document generation (6 documents)
13. Compliance test suite (22 checks across 6 groups)

---

## Project Structure

```
aether-compliance/
|-- main.py                              # Demo runner — exercises the full framework
|-- pyproject.toml                       # Build config, dependencies, package discovery
|-- README.md
|
|-- config/
|   |-- __init__.py
|   |-- compliance_config.py             # Central configuration for all modules
|
|-- gdpr/
|   |-- __init__.py
|   |-- data_protection/
|   |   |-- __init__.py
|   |   |-- data_protection.py           # 7 Art. 25 controls (IP anon, pseudonymization, etc.)
|   |-- data_subject_rights/
|   |   |-- __init__.py
|   |   |-- dsr_engine.py                # DSR executor for Art. 15-21 rights
|   |-- consent/
|   |   |-- __init__.py
|   |   |-- consent_manager.py           # Purpose-based consent with immutable audit trail
|   |-- breach_notification/
|   |   |-- __init__.py
|   |   |-- breach_handler.py            # Art. 33/34 breach response pipeline
|   |-- ropa/
|       |-- __init__.py
|       |-- ropa_engine.py               # Art. 30 Record of Processing Activities
|
|-- soc2/
|   |-- __init__.py
|   |-- trust_criteria/
|   |   |-- __init__.py
|   |   |-- trust_criteria_engine.py     # 34 controls, 97.1% readiness (32 impl, 2 partial)
|   |-- gap_analysis/
|   |   |-- __init__.py
|   |   |-- gap_analyzer.py              # 2 remaining partial gaps (CC-3.2, A-3.2)
|   |-- continuous/
|   |   |-- __init__.py
|   |   |-- compliance_monitor.py        # 18 automated continuous checks
|   |-- controls/                        # Evidence artifacts for the 9 remediated gaps
|       |-- __init__.py
|       |-- security_policy.py           # [CC-3.1] ISP v2.1 with annual review lifecycle
|       |-- pentest_tracker.py           # [CC-3.2] Pen test scope, vendor criteria, tracker
|       |-- sla_document.py              # [A-3.1]  99.9% SLA with credit schedule
|       |-- tabletop_exercises.py        # [A-3.2]  4 quarterly DR exercise scenarios
|       |-- pi_controls.py              # [PI-2.1] 5 processing integrity controls
|       |-- classification_policy.py    # [C-2.1]  7-tier data classification policy
|       |-- access_review_process.py    # [C-2.2]  21-item quarterly access review process
|       |-- pia_process.py              # [P-2.1]  PIA triggers, SDLC gates, risk matrix
|       |-- annual_privacy_review.py    # [P-2.2]  Annual review: 9 areas, 53 checks
|
|-- audit/
|   |-- __init__.py
|   |-- trails/
|   |   |-- __init__.py
|   |   |-- audit_engine.py              # 5 trail types with immutable logging
|   |-- reviews/
|       |-- __init__.py
|       |-- access_review.py             # Quarterly IAM reviews + auto-remediation
|
|-- policies/
|   |-- __init__.py
|   |-- policy_generator.py              # Generates 6 required policy documents
|
|-- shared/
|   |-- __init__.py
|   |-- logger.py                        # Tagged logging utility (DPD, DSR, CST, BRC, etc.)
|
|-- tests/
    |-- __init__.py
    |-- compliance_tests.py              # 22 compliance checks across 6 groups
```

---

## Framework Overview

### GDPR Compliance

#### Data Protection by Design (Art. 25) -- 7 Controls

Technical controls enforced at the infrastructure level before any data reaches storage:

| # | Control | Implementation |
|---|---------|----------------|
| 1 | **IP Anonymization** | Last octet zeroed (IPv4), last 80 bits zeroed (IPv6) |
| 2 | **Data Vectorization** | SDK transmits ML-computed vectors instead of raw behavioral data |
| 3 | **Pseudonymization** | SHA-256 with per-tenant salt; only Identity Service holds mapping |
| 4 | **Data Minimization** | Only explicitly enabled data categories collected; no shadow collection |
| 5 | **Encryption in Transit** | TLS 1.3 enforced on all endpoints |
| 6 | **Encryption at Rest** | AES-256 via AWS KMS for all data stores |
| 7 | **Access Controls** | RBAC with least privilege, JWT + API key auth, permission-based authorization |

#### Data Subject Rights (Art. 15-21) -- 6 Rights with SLAs

| Article | Right | SLA | API Endpoint |
|---------|-------|-----|-------------|
| Art. 15 | **Right to Access** | Within 30 days | `POST /v1/consent/dsr {type: 'access'}` |
| Art. 16 | **Right to Rectification** | Within 5 business days | `POST /v1/consent/dsr {type: 'rectification'}` |
| Art. 17 | **Right to Erasure** | Within 30 days (backups 90 days) | `POST /v1/consent/dsr {type: 'erasure'}` |
| Art. 18 | **Right to Restriction** | Immediate | `POST /v1/consent/dsr {type: 'restriction'}` |
| Art. 20 | **Right to Portability** | Within 30 days | `POST /v1/consent/dsr {type: 'portability'}` |
| Art. 21 | **Right to Object** | Immediate | `POST /v1/consent/dsr {type: 'objection'}` |

#### Consent Management (Art. 7)

- **5 consent purposes:** `analytics`, `marketing`, `web3`, `agent` (Intelligence Graph behavioral tracking), `commerce` (payment processing)
- **Immutable audit trail:** DynamoDB append-only log recording user_id, tenant_id, purpose, granted status, timestamp, IP address hash, user agent hash, policy version, and source
- **Do Not Track (DNT) support:** SDK respects DNT headers before collection
- **Consent sources:** cookie banner, privacy settings, API, DNT signal
- **Withdrawal effect:** Immediate cessation of data collection for that user
- **SDK enforcement:** All SDK methods check consent status before collecting or transmitting data
- **Fail-closed enforcement:** `consent_enforcement.py` — `require_consent()` raises `ConsentDeniedError`; `analytics` uses legitimate interest, all other purposes require explicit opt-in

#### Breach Notification (Art. 33/34)

**72-hour notification deadline** to the lead supervisory authority. High-risk breaches trigger data subject notification.

**8-Step Incident Response Pipeline:**

1. **Detection** -- GuardDuty, application alerts, or manual report
2. **Assessment** -- Severity classification, scope, data categories affected
3. **Containment** -- Isolate, revoke credentials, block access
4. **Internal Escalation** -- 30-minute escalation window
5. **Evidence Collection** -- Automated forensic gathering
6. **DPA Notification** -- Within 72 hours to supervisory authority
7. **Data Subject Notification** -- If high risk to rights and freedoms
8. **Remediation + Post-Mortem** -- Root cause analysis and corrective actions

**Severity levels:** LOW, MEDIUM, HIGH, CRITICAL with automatic escalation.

**Notification channels:** PagerDuty (immediate), Slack #security-incidents, Email (security@aether.network), DPA authority notification, affected data subjects (if high risk).

#### Record of Processing Activities -- ROPA (Art. 30)

9 processing activities registered with full Art. 30 metadata:

| Activity | Legal Basis | Data Categories | Recipients |
|----------|-------------|-----------------|------------|
| Behavioral Analytics | Art. 6(1)(a) Consent / Art. 6(1)(f) Legitimate Interest | Page views, clicks, scroll depth, custom events, device info | Aether (processor), AWS (sub-processor) |
| Identity Resolution | Art. 6(1)(a) Consent | User ID, email hash, device fingerprint, session data, wallet address | Aether, AWS |
| ML Predictions | Art. 6(1)(a) Consent / Art. 6(1)(f) Legitimate Interest | Behavioral features, identity features, prediction scores | Aether, AWS SageMaker |
| Campaign Orchestration | Art. 6(1)(a) Consent (marketing) | Segment membership, prediction scores, campaign interactions | Aether, Customer email/SMS providers |
| Consent Record Keeping | Art. 6(1)(c) Legal Obligation | Consent records, timestamps, IP hash, user agent hash, policy version | Aether |
| Web3 Wallet Analytics | Art. 6(1)(a) Consent (web3) | Wallet address, chain ID, connection events, transaction hashes | Aether, Blockchain RPCs (public) |
| Agent Behavioral Tracking | Art. 6(1)(f) Legitimate Interest | Agent ID, task data, decision records, state snapshots, confidence delta | Aether, AWS |
| Commerce Payment Processing | Art. 6(1)(b) Contract | Payment amounts, transaction hashes, fee computations, payer/payee IDs | Aether, Blockchain networks |
| On-Chain Action Intelligence | Art. 6(1)(f) Legitimate Interest | Contract addresses, bytecode hashes, action intents, risk scores | Aether, QuickNode, Blockchain RPCs |

**DPIA required** for ML Predictions and Identity Resolution (automated profiling). Both DPIAs are pending completion.

#### Cross-Border Transfers (Ch. V, Art. 44-49)

3 transfers documented with Standard Contractual Clauses (SCCs) and completed Transfer Impact Assessments (TIA):

| Destination | Sub-Processor | Transfer Mechanism | TIA |
|-------------|---------------|--------------------|-----|
| US (us-east-1, us-west-2) | AWS | EU SCCs Module 3 (Processor to Sub-Processor) + supplementary measures | Completed |
| US (us-east-1) | AWS SageMaker | EU SCCs Module 3 + encryption in transit and at rest | Completed |
| Global (CDN edge) | AWS CloudFront | EU SCCs + data minimization (SDK code only, no personal data at edge) | Completed |

#### GDPR Data Stores -- 7 Stores Mapped

| Data Store | Data Types | Deletion Method | Retention |
|------------|-----------|-----------------|-----------|
| Neptune (Graph DB) | Identity nodes, session edges, device links, company associations | DELETE vertex + all connected edges by user_id | Until erasure request |
| TimescaleDB (Events) | Behavioral events, page views, custom events | DELETE FROM events WHERE user_id = ? | Per tenant retention policy |
| ElastiCache (Redis) | Session cache, profile cache, prediction cache | DEL key pattern user:{user_id}:* | TTL-based auto-expiry |
| S3 (Data Lake) | Raw events (Parquet), processed events, export files | S3 object deletion by prefix + lifecycle policy | Per tenant, max 7 years |
| OpenSearch (Vectors) | Embedding vectors, search indices | DELETE by user_id query | Aligned with source data |
| DynamoDB (Config) | Consent records, API keys, tenant config | DeleteItem by key | Consent: indefinite audit trail |
| SageMaker (Features) | ML features, predictions, model inputs | Delete feature records + retrain models | Until erasure request |

---

### SOC 2 Type II Readiness

#### 5 Trust Criteria -- 34 Controls Total

| Criteria | Code | Implemented | Partial | Not Implemented | Total | Coverage |
|----------|------|-------------|---------|-----------------|-------|---------|
| **Security** | CC | 9 | 1 | 0 | 10 | 95.0% |
| **Availability** | A | 6 | 1 | 0 | 7 | 92.9% |
| **Processing Integrity** | PI | 5 | 0 | 0 | 5 | 100.0% |
| **Confidentiality** | C | 6 | 0 | 0 | 6 | 100.0% |
| **Privacy** | P | 6 | 0 | 0 | 6 | 100.0% |
| **Total** | | **32** | **2** | **0** | **34** | **97.1%** |

**Overall readiness: 97.1%** (32 implemented + 2 partial out of 34 controls — above 90% certification threshold)

#### Remaining Partial Gaps

Both require real-world execution by an external party or the engineering/security team:

| ID | Gap | Status | What Remains |
|----|-----|--------|--------------|
| CC-3.2 | Penetration Testing | PARTIAL | Framework defined (`pentest_tracker.py`). Annual engagement with a CREST/OSCP-certified vendor required for full evidence. |
| A-3.2 | Tabletop Exercises | PARTIAL | 4 quarterly scenarios defined (`tabletop_exercises.py`). Conducted exercises with recorded outcomes needed. |

#### Remediated Controls (9 gaps closed)

All previously NOT_IMPLEMENTED controls now have implemented evidence artifacts in `soc2/controls/`:

| ID | Control | Module | Status |
|----|---------|--------|--------|
| CC-3.1 | Security Policy Documentation | `security_policy.py` — ISP v2.1 (annual review lifecycle, overdue-review detection) | ✅ IMPLEMENTED |
| A-3.1 | Formal SLA Documentation | `sla_document.py` — 99.9% SLA, measurement methodology, 4-tier credit schedule | ✅ IMPLEMENTED |
| PI-2.1 | Processing Integrity Controls | `pi_controls.py` — 5 controls with criterion mapping and test procedures | ✅ IMPLEMENTED |
| C-2.1 | Data Classification Policy | `classification_policy.py` — 7-tier formal policy + handling matrix | ✅ IMPLEMENTED |
| C-2.2 | Access Review Process | `access_review_process.py` — 21-item quarterly checklist + remediation SLAs | ✅ IMPLEMENTED |
| P-2.1 | Privacy Impact Assessment | `pia_process.py` — 8 triggers, 4 SDLC gates, DPO sign-off workflow | ✅ IMPLEMENTED |
| P-2.2 | Annual Privacy Review | `annual_privacy_review.py` — 9 areas, 53 checklist items | ✅ IMPLEMENTED |
| CC-5.1 | Incident Response Plan | `policies/policy_generator.py` + `breach_handler.py` (upgraded from PARTIAL) | ✅ IMPLEMENTED |
| C-1.3 | DPA Template | `policies/policy_generator.py` — 11-section Art. 28 DPA (upgraded from PARTIAL) | ✅ IMPLEMENTED |
| C-1.4 | Sub-Processor Register | `config/compliance_config.py::CROSS_BORDER_TRANSFERS` (upgraded from PARTIAL) | ✅ IMPLEMENTED |

#### Continuous Compliance Monitor -- 18 Automated Checks

Automated checks run across 6 categories with evidence collection:

| Category | Checks | Examples |
|----------|--------|---------|
| **Encryption** (4) | ENC-001 to ENC-004 | TLS 1.3 on ALB, RDS/S3/DynamoDB encryption at rest |
| **Access Control** (4) | AC-001 to AC-004 | MFA enforcement, no wildcard IAM policies, key rotation, least privilege |
| **Data Protection** (3) | DP-001 to DP-003 | IP anonymization, pseudonymization, data minimization |
| **Audit** (3) | AT-001 to AT-003 | CloudTrail enabled, app audit logs flowing, consent trail immutable |
| **Consent** (2) | CC-001 to CC-002 | DNT header respected, consent checked before processing |
| **Retention** (2) | RET-001 to RET-002 | S3 lifecycle policies active, log retention within policy |

---

### Audit Infrastructure

#### 5 Audit Trail Types

| Trail | Description | Storage | Retention |
|-------|-------------|---------|-----------|
| **CloudTrail** | All AWS API calls | S3 in security account | 1 year (365 days) |
| **Application Audit** | All data access, modification, deletion with context | TimescaleDB + S3 | 1 year (365 days) |
| **Consent Audit** | All consent grants, revocations, DSRs (immutable) | DynamoDB | 7 years (2,555 days) |
| **Agent Audit** | Every AI agent action with provenance and I/O | TimescaleDB + S3 | 1 year (365 days) |
| **Access Reviews** | Quarterly IAM permission reviews | S3 reports | 3 years (1,095 days) |

**Supported audit actions:** read, create, update, delete, export, consent_grant, consent_revoke, dsr_request, dsr_complete, agent_inference, agent_action, access_review, login, permission_change.

#### Quarterly IAM Access Reviews

Automated access review with findings across severity levels (critical, high, medium, low, info):

- Unused credentials detection
- MFA compliance verification
- Overly broad role identification
- Service account hygiene checks
- **Auto-remediation** for policy-defined violations
- Documented review outcomes with action tracking

---

### Policy Documents

6 compliance documents generated by the policy engine:

| # | Document | Purpose |
|---|----------|---------|
| 1 | **Information Security Policy** | Covers all AICPA trust criteria, access management, change management, acceptable use |
| 2 | **Data Classification Policy** | Classification levels (Public, Internal, Confidential, Restricted), handling requirements |
| 3 | **Incident Response Plan** | Roles, escalation matrix, severity classification, communication templates |
| 4 | **Data Processing Agreement (DPA) Template** | Art. 28 processor obligations, SCCs, sub-processor notification |
| 5 | **Privacy Impact Assessment (PIA) Template** | Art. 35 aligned, risk assessment matrix, triggers for new processing |
| 6 | **Data Retention Policy** | Per-store retention periods, deletion methods, lifecycle policies |

All documents are generated as structured objects with title, version, status (DRAFT), owner, section count, and review dates.

---

### Testing

**22 compliance checks** across **6 test groups**, all passing:

| Group | Description |
|-------|-------------|
| GDPR Data Protection | Verifies all 7 Art. 25 controls (IP anonymization, pseudonymization, data minimization, encryption, access controls) |
| GDPR DSR | Validates data subject rights engine processes all 6 right types |
| GDPR Consent | Tests consent grant/revoke lifecycle, DNT handling, audit trail immutability |
| GDPR Breach | Verifies breach detection, severity escalation, 72-hour notification pipeline |
| SOC 2 | Validates trust criteria engine loads 34 controls across 5 criteria |
| Audit | Tests audit trail logging, querying, and retention verification |

Run the test suite:

```bash
python3 main.py
# Tests run as part of the full demo — look for the "COMPLIANCE TEST SUITE" section
```

---

## Module Reference

| Module | Class / Function | Description |
|--------|-----------------|-------------|
| `config.compliance_config` | `DataRole`, `DataSubjectRight`, `DataProtectionControl`, `ConsentConfig`, `GDPRDataStore`, `TrustCriteria`, `AuditTrailConfig`, `BreachNotificationConfig`, `ProcessingActivity`, `CrossBorderTransfer` | Central configuration dataclasses and enums for the entire framework |
| `gdpr.data_protection.data_protection` | `IPAnonymizer`, `DataVectorizer`, `Pseudonymizer`, `DataMinimizer`, `DataProtectionPipeline` | Art. 25 technical controls: IP anonymization, vectorization, pseudonymization, data minimization |
| `gdpr.data_subject_rights.dsr_engine` | `DSRExecutor`, `DSRRequest`, `DSRType` | Processes all 6 data subject rights with SLA tracking |
| `gdpr.consent.consent_manager` | `ConsentManager`, `ConsentSource`, `ConsentAction` | Purpose-based consent lifecycle with immutable DynamoDB audit trail |
| `gdpr.breach_notification.breach_handler` | `BreachHandler`, `BreachSeverity`, `BreachStatus`, `BreachIncident` | 8-step incident response pipeline with 72-hour notification enforcement |
| `gdpr.ropa.ropa_engine` | `ROPAEngine`, `ROPAEntry` | Art. 30 register of all processing activities |
| `soc2.trust_criteria.trust_criteria_engine` | `TrustCriteriaEngine`, `SOC2Control`, `ControlStatus`, `CriteriaAssessment` | 34 controls across 5 trust criteria with readiness scoring |
| `soc2.gap_analysis.gap_analyzer` | `GapAnalyzer`, `GapItem`, `Priority`, `EffortLevel` | 2 remaining partial gaps (CC-3.2, A-3.2); 9 gaps remediated via `soc2/controls/` modules |
| `soc2.controls.security_policy` | `SecurityPolicyManager`, `SecurityPolicyVersion`, `OverdueReviewError` | CC-3.1: Information Security Policy v2.1 lifecycle with overdue-review detection |
| `soc2.controls.pentest_tracker` | `PentestTracker`, `PentestEngagement`, `Finding` | CC-3.2: Annual penetration test scheduling, finding triage, remediation SLA tracking |
| `soc2.controls.sla_document` | `SLADocumentManager`, `SLACommitment` | A-3.1: Availability SLA commitments (99.9% uptime) with evidence generation |
| `soc2.controls.tabletop_exercises` | `TabletopExerciseTracker`, `TabletopExercise` | A-3.2: Quarterly DR/IR tabletop exercise scheduling and completion tracking |
| `soc2.controls.pi_controls` | `ProcessingIntegrityManager`, `IntegrityCheck` | PI-2.1: Input validation, idempotency keys, reconciliation, and error-rate monitoring |
| `soc2.controls.classification_policy` | `ClassificationPolicyManager`, `DataClassification` | C-2.1: Four-tier data classification policy (Public → Restricted) with handling rules |
| `soc2.controls.access_review_process` | `AccessReviewProcessManager`, `AccessReviewCycle` | C-2.2: Quarterly IAM access review cadence with least-privilege enforcement evidence |
| `soc2.controls.pia_process` | `PIAProcessManager`, `PIARecord` | P-2.1: Privacy Impact Assessment process for new features with risk scoring |
| `soc2.controls.annual_privacy_review` | `AnnualPrivacyReviewManager`, `PrivacyReviewRecord` | P-2.2: Annual privacy program review with GDPR/SOC 2 alignment checkpoints |
| `soc2.continuous.compliance_monitor` | `ContinuousComplianceMonitor`, `ComplianceCheck`, `CheckStatus` | 18 automated checks across 6 categories with drift tracking |
| `audit.trails.audit_engine` | `AuditEngine`, `AuditAction` | 5 trail types with immutable logging, querying, and retention verification |
| `audit.reviews.access_review` | `AccessReviewer`, `AccessReviewFinding`, `AccessReviewReport` | Quarterly IAM reviews with severity-based findings and auto-remediation |
| `policies.policy_generator` | `PolicyGenerator`, `PolicyDocument` | Generates 6 structured policy documents |
| `tests.compliance_tests` | `ComplianceTestRunner`, `TestResult` | 22 compliance checks across 6 groups |
| `shared.logger` | `log`, `timed`, `dpd_log`, `dsr_log`, `cst_log`, `brc_log`, `soc2_log`, `gap_log`, `aud_log`, `iam_log`, `pol_log`, `ropa_log` | Tagged logging utility shared across all modules |

---

## Configuration Reference

All framework configuration lives in `config/compliance_config.py`:

| Config Object | Type | Description |
|---------------|------|-------------|
| `DataRole` | Enum | Processor (Aether), Controller (Customer), Sub-Processor (AWS, third-party APIs) |
| `GDPR_RIGHTS` | List[DataSubjectRight] | 6 data subject rights with articles, SLAs, and API endpoints |
| `DATA_PROTECTION_CONTROLS` | List[DataProtectionControl] | 7 Art. 25 controls with technical implementation details |
| `CONSENT_CONFIG` | ConsentConfig | 5 purposes, DynamoDB storage, 9 audit fields, DNT support, withdrawal effect |
| `ConsentPurpose` | Enum | analytics, marketing, web3, agent, commerce |
| `GDPR_DATA_STORES` | List[GDPRDataStore] | 7 data stores with data types, deletion methods, and retention defaults |
| `SOC2_TRUST_CRITERIA` | List[TrustCriteria] | 5 criteria with current implementations and certification gaps |
| `AUDIT_TRAILS` | List[AuditTrailConfig] | 5 trail types with storage backends and retention periods |
| `BREACH_CONFIG` | BreachNotificationConfig | 72-hour window, 30-minute internal escalation, 5 notification channels |
| `PROCESSING_ACTIVITIES` | List[ProcessingActivity] | 9 ROPA entries with legal basis, data categories, recipients, safeguards |
| `CROSS_BORDER_TRANSFERS` | List[CrossBorderTransfer] | 3 transfers with SCCs, data categories, and TIA status |

---

## License

Proprietary. All rights reserved. Unauthorized copying, modification, distribution, or use of this software is strictly prohibited without prior written consent from Aether.
