# Aether Privacy, Policy, and Hardening Control Plane

## Architecture Overview

The Aether Privacy, Policy, and Hardening Control Plane is implemented as `shared/privacy/` — a modular library consumed by all Aether services. It enforces data classification, access control, retention, deletion, and ML training policy at every layer of the stack.

The control plane comprises three core modules:

| Module | Path | Responsibility |
|--------|------|----------------|
| **Classification** | `shared/privacy/classification.py` | 7-tier data classification, field registry, policy metadata model |
| **Access Control** | `shared/privacy/access_control.py` | RBAC + ABAC + purpose-based access, field-level masking, graph traversal policy, log redaction, training eligibility |
| **Retention** | `shared/privacy/retention.py` | Retention policies, pseudonymization engine, deletion cascading (DeletionPlan), DSAR workflow (DSARRequest) |

All three modules are stateless libraries. They are imported by API handlers, graph query engines, ETL pipelines, ML feature stores, and logging middleware. No service bypasses them; every data path flows through the control plane before reads, writes, exports, or deletions occur.

---

## Data Classification Model

### 7-Tier Hierarchy

Aether classifies every data field into one of seven sensitivity tiers, ordered from least to most restrictive:

| Tier | Ordinal | Description |
|------|---------|-------------|
| `PUBLIC` | 0 | Freely available data with no access restrictions |
| `INTERNAL` | 1 | Operational data visible to all authenticated internal roles |
| `CONFIDENTIAL` | 2 | Business-sensitive data requiring role-based access |
| `SENSITIVE_PII` | 3 | Personally identifiable information subject to privacy regulation |
| `FINANCIAL` | 4 | Financial records, transactions, and account data |
| `REGULATED` | 5 | Data subject to specific regulatory frameworks (KYC, AML, beneficial ownership) |
| `HIGHLY_SENSITIVE` | 6 | Maximum restriction — API secrets, cross-domain identity links, beneficial ownership inferences |

### Tier Property Matrix

Each tier defines a complete set of policy properties:

| Property | PUBLIC | INTERNAL | CONFIDENTIAL | SENSITIVE_PII | FINANCIAL | REGULATED | HIGHLY_SENSITIVE |
|----------|--------|----------|--------------|---------------|-----------|-----------|------------------|
| `encryption_at_rest` | No | No | Yes | Yes | Yes | Yes | Yes |
| `encryption_in_transit` | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| `field_level_encryption` | No | No | No | Yes | Yes | Yes | Yes |
| `requires_consent` | No | No | No | Yes | Yes | Yes | Yes |
| `default_lawful_basis` | legitimate_interest | legitimate_interest | legitimate_interest | consent | contract | legal_obligation | legal_obligation |
| `retention` | permanent | standard (365d) | standard (365d) | extended (1095d) | compliance (2555d) | compliance (2555d) | compliance (2555d) |
| `deletion_behavior` | hard_delete | hard_delete | hard_delete | pseudonymize | pseudonymize | tombstone | hash_irreversible |
| `exportable` | Yes | Yes | Yes | Yes (with approval) | Yes (with approval) | No | No |
| `export_requires_approval` | No | No | No | Yes | Yes | N/A | N/A |
| `training_eligibility` | eligible | eligible | eligible | consent_required | anonymized_only | excluded | excluded |
| `externally_visible` | Yes | No | No | No | No | No | No |
| `log_redaction_required` | No | No | No | Yes | Yes | Yes | Yes |
| `min_access_role` | viewer | viewer | editor | compliance | compliance | compliance | admin |
| `graph_traversal_allowed` | Yes | Yes | Yes | Yes (masked) | No | No | No |
| `cross_domain_linking_allowed` | Yes | Yes | No | No | No | No | No |

### Field Registry

`classification.py` maintains a global `FIELD_REGISTRY` that maps every known field name to its classification tier. Examples:

```
user_id          -> SENSITIVE_PII
email_hash       -> SENSITIVE_PII
wallet_address   -> CONFIDENTIAL
device_fp        -> CONFIDENTIAL
session_events   -> INTERNAL
kyc_document_id  -> REGULATED
api_key_hash     -> HIGHLY_SENSITIVE
chain_registry   -> PUBLIC
```

Any field not present in the registry defaults to `CONFIDENTIAL` and triggers an alert for the data engineering team to classify it explicitly.

---

## Identity and Graph Policy Model

### Edge Classification by Observation Type

The Aether Knowledge Graph distinguishes between directly observed edges and inferred edges. Inferred edges carry higher restriction levels:

| Edge Property | Observed Edges | Inferred Edges |
|---------------|---------------|----------------|
| Base classification | CONFIDENTIAL | REGULATED |
| Export eligibility | Yes (with approval) | Never |
| Training eligibility | eligible | excluded |
| Graph traversal | Allowed for editor+ | Restricted by confidence |
| Cross-domain linking | No | No |

### Confidence-Based Access for Inferred Edges

Inferred edges carry a confidence score that further gates access:

| Confidence Range | Required Role | Traversal Allowed | Notes |
|------------------|---------------|-------------------|-------|
| Low (< 0.5) | compliance | No | Speculative links; visible only for investigation |
| Medium (0.5 - 0.8) | editor | Yes (masked metadata) | Operational use permitted with masking |
| High (> 0.8) | editor | Yes | Treated similarly to observed edges for traversal |

### Regulated Edge Types

Certain edge types are always regulated regardless of confidence:

- `BENEFICIAL_OF` — Beneficial ownership relationship
- `OVERLAPS_WITH` — Cross-entity identity overlap
- `CONTROLS` — Control relationship between entities
- `FUNDS` — Funding flow relationship
- `NOMINEE_FOR` — Nominee/proxy relationship

These edge types always require the `compliance` role for any access.

### PolicyMetadata Attachment

`PolicyMetadata` is a data structure that can be attached to any graph object (node or edge):

```
PolicyMetadata:
    classification: ClassificationTier
    lawful_basis: LawfulBasis
    retention_class: RetentionClass
    residency_constraint: Optional[str]       # e.g., "eu_only", "us_only"
    consent_id: Optional[str]                 # Link to consent record
    purpose_limitation: List[Purpose]
    export_blocked: bool
    training_blocked: bool
    immutable: bool
    created_at: datetime
    updated_at: datetime
```

PolicyMetadata enables per-object overrides. A field classified as CONFIDENTIAL at the schema level can be elevated to REGULATED on a specific record if regulatory context demands it.

---

## Access Model

The access model is layered: RBAC provides base role assignment, ABAC adds classification-driven constraints, and purpose-based controls enforce usage restrictions.

### Layer 1: Role-Based Access Control (RBAC)

7 roles ordered by privilege:

| Role | Ordinal | Description |
|------|---------|-------------|
| `viewer` | 0 | Read-only access to PUBLIC and INTERNAL data |
| `editor` | 1 | Read/write access to CONFIDENTIAL and below |
| `support` | 2 | Access to customer-facing PII for support operations |
| `compliance` | 3 | Access to regulated data for compliance and investigation |
| `data_science` | 4 | Access to anonymized/aggregated data for analytics and ML |
| `admin` | 5 | Full system access including HIGHLY_SENSITIVE data |
| `auditor` | 6 | Read-only access to all data including audit logs; cannot modify |

### Layer 2: Attribute-Based Access Control (ABAC)

Classification tiers define minimum role requirements (see `min_access_role` in the tier property matrix above). The ABAC layer enforces that a user's role ordinal meets or exceeds the minimum required by the data's classification.

Access decision logic:

```
allow = (user.role.ordinal >= tier.min_access_role.ordinal)
        AND (purpose in tier.allowed_purposes)
        AND (not tier.requires_consent OR consent_verified)
```

### Layer 3: Purpose-Based Access Control

7 access purposes:

| Purpose | Description | Allowed Tiers |
|---------|-------------|---------------|
| `operational` | Normal business operations | PUBLIC through CONFIDENTIAL |
| `analytics` | Aggregated reporting and dashboards | PUBLIC through CONFIDENTIAL (anonymized) |
| `support` | Customer support case handling | PUBLIC through SENSITIVE_PII |
| `compliance` | Regulatory compliance and reporting | All tiers |
| `investigation` | Fraud/AML investigation | All tiers (with compliance role) |
| `training` | ML model training | PUBLIC through CONFIDENTIAL (eligible only) |
| `export` | Data export / DSAR fulfillment | PUBLIC through FINANCIAL (with approval) |

### Field-Level Access Controls

6 access levels applied at the field level:

| Access Level | Behavior |
|--------------|----------|
| `FULL` | Complete field value returned |
| `MASKED` | Partial value returned (e.g., `j***@e***.com`) |
| `METADATA_ONLY` | Only field presence and type returned, no value |
| `DENIED` | Field stripped from response entirely |
| `PURPOSE_BOUND` | Full access only when request purpose matches field's allowed purposes |
| `INTERNAL_ONLY` | Full access for internal services; denied for external API responses |

Field-level access is resolved by combining the user's role, the request purpose, and the field's classification tier. The most restrictive applicable rule wins.

---

## Lawful Basis Model

### GDPR Article 6 Bases

6 lawful bases supported:

| Lawful Basis | Code | Description |
|-------------|------|-------------|
| Consent | `consent` | Data subject has given explicit consent for the specific purpose |
| Contract | `contract` | Processing is necessary for performance of a contract |
| Legal Obligation | `legal_obligation` | Processing is necessary for compliance with a legal obligation |
| Vital Interest | `vital_interest` | Processing is necessary to protect vital interests |
| Public Task | `public_task` | Processing is necessary for a task carried out in the public interest |
| Legitimate Interest | `legitimate_interest` | Processing is necessary for legitimate interests pursued by the controller |

### PolicyMetadata Enforcement

When `PolicyMetadata` is attached to an object with a specific `lawful_basis`:

- **Joins**: Queries joining across objects with different lawful bases are blocked unless the requesting purpose is compatible with both bases
- **Exports**: Objects with `legal_obligation` basis can only be exported under `compliance` or `investigation` purpose
- **Training**: Objects with `consent` basis can only be used for training if the consent record explicitly covers ML training
- **Cross-domain linking**: Objects with `consent` basis cannot be linked to objects under a different basis without fresh consent

---

## DSAR and Deletion Model

### DSAR Request Types

6 Data Subject Access Request types with SLA enforcement:

| DSAR Type | SLA (Days) | Description |
|-----------|------------|-------------|
| `access` | 30 | Provide all data held about the subject |
| `rectification` | 30 | Correct inaccurate data |
| `erasure` | 30 | Delete all non-exempt data (right to be forgotten) |
| `portability` | 30 | Export data in machine-readable format |
| `restriction` | 7 | Restrict processing while dispute is resolved |
| `objection` | 7 | Stop processing based on legitimate interest |

### DSARRequest Lifecycle

```
SUBMITTED -> VALIDATED -> IN_PROGRESS -> PENDING_REVIEW -> COMPLETED
                |                              |
                +-> REJECTED                   +-> PARTIALLY_COMPLETED
```

- `VALIDATED`: Identity of requester confirmed
- `IN_PROGRESS`: DeletionPlan or export being generated
- `PENDING_REVIEW`: Compliance officer review required (for partial completions or exemptions)
- `PARTIALLY_COMPLETED`: Some records exempt from deletion (immutable audit logs, legal holds)

### DeletionPlan and Cascading

The `DeletionPlan` orchestrates deletion across all storage backends:

| Store | Deletion Method | Notes |
|-------|----------------|-------|
| PostgreSQL | Row deletion or pseudonymization | Cascading foreign keys handled |
| Neptune (Graph) | Edge severance + node pseudonymization | Inferred edges deleted; observed edges severed |
| Redis | Key deletion | Session and cache data purged immediately |
| S3 | Object deletion or key destruction | Encrypted objects can be rendered unreadable via key destruction |
| Lake (Bronze) | Tombstone markers | Immutable append-only; tombstones prevent downstream reads |
| Lake (Silver) | Re-processing with exclusion | Next ETL run excludes tombstoned records |
| Lake (Gold) | Aggregate retention only | Individual records already aggregated; no action needed |

### Deletion Behaviors

8 deletion behaviors available:

| Behavior | Description | Used For |
|----------|-------------|----------|
| `hard_delete` | Permanent removal from all stores | PUBLIC, INTERNAL data |
| `pseudonymize` | Replace identifying values with irreversible tokens | SENSITIVE_PII, FINANCIAL |
| `tombstone` | Mark as deleted; prevent reads; retain for compliance window | REGULATED data in append-only stores |
| `hash_irreversible` | Replace value with one-way hash | HIGHLY_SENSITIVE data |
| `key_destroy` | Destroy encryption key rendering ciphertext unreadable | S3 encrypted objects |
| `edge_sever` | Remove edges from graph while retaining anonymized node | Graph relationships |
| `retain_aggregate` | Keep only aggregate/statistical data; remove individual records | Analytics and reporting data |
| `immutable` | Record is NEVER deleted | Audit logs, consent history, compliance actions |

### Immutable Record Types

The following record types are exempt from all deletion requests:

- Audit logs (admin actions, data access logs)
- Consent history (consent grants, revocations, and modifications)
- Compliance actions (KYC decisions, AML alerts, sanctions checks)
- DSAR request records themselves

These records may be pseudonymized (replacing the subject identifier with an irreversible token) but are never removed.

---

## Retention and Residency Model

### Retention Classes

7 retention classes:

| Class | Duration (Days) | Description |
|-------|-----------------|-------------|
| `ephemeral` | 0 | Deleted immediately after use (session tokens, OTPs) |
| `short` | 30 | Temporary operational data (cache entries, temp files) |
| `standard` | 365 | Default retention for most business data |
| `extended` | 1,095 | PII and financial data retained for regulatory minimums |
| `compliance` | 2,555 | Regulated data retained for full compliance window (~7 years) |
| `permanent` | -1 (indefinite) | Public reference data, chain registries |
| `legal_hold` | -1 (indefinite) | Data under active legal hold; retention overrides all other policies |

### Retention Enforcement

- Retention is enforced by a nightly batch job that scans all stores for records past their retention deadline
- Records approaching expiry (within 30 days) are flagged for review
- Legal holds override all retention classes and prevent deletion until the hold is released
- Retention class is determined by the highest applicable classification tier on the record

### Residency Model

The architecture supports future data residency constraints via `PolicyMetadata.residency_constraint`:

| Constraint | Behavior |
|------------|----------|
| `us_only` | Data must be stored and processed exclusively in US regions |
| `eu_only` | Data must be stored and processed exclusively in EU regions |
| `none` | No residency constraint (default) |

Residency constraints are not yet enforced at the infrastructure level but are tracked in metadata for forward compatibility. When multi-region deployment is activated, the control plane will enforce residency at write time and block cross-region replication for constrained records.

---

## ML and Training Policy Model

### Training Eligibility States

5 training eligibility states:

| State | Description |
|-------|-------------|
| `eligible` | Data can be freely used for model training |
| `excluded` | Data must never be used for training under any circumstances |
| `consent_required` | Data can only be used if explicit ML training consent exists |
| `anonymized_only` | Data can be used only after full anonymization (k-anonymity, differential privacy) |
| `aggregate_only` | Only aggregate statistics derived from this data can be used |

### Classification-Based Defaults

| Classification Tier | Default Training Eligibility |
|---------------------|------------------------------|
| PUBLIC | eligible |
| INTERNAL | eligible |
| CONFIDENTIAL | eligible |
| SENSITIVE_PII | consent_required |
| FINANCIAL | anonymized_only |
| REGULATED | excluded |
| HIGHLY_SENSITIVE | excluded |

### Enforcement: `can_use_for_training()`

The `can_use_for_training()` function is called at query time by ML pipelines and feature stores. It evaluates:

1. The field's classification tier and its default training eligibility
2. Any `PolicyMetadata` override on the specific record
3. Whether `training_blocked` is set on the PolicyMetadata
4. For `consent_required` fields: whether a valid, unexpired consent record exists covering ML training
5. For `anonymized_only` fields: whether the data has been processed through the anonymization pipeline

If any check fails, the field is excluded from the training query result set. Partial records (some fields eligible, others not) are returned with ineligible fields stripped.

### Inferred Edge Training Policy

Inferred graph edges are always `excluded` from training regardless of confidence score. This prevents feedback loops where model outputs are used to train subsequent models without human validation.

---

## Logging and Observability Hygiene

### `redact_for_logging()`

The `redact_for_logging()` function is applied to all log payloads before they are written to any logging backend (stdout, structured log aggregators, distributed tracing spans).

**Tier-based redaction**: All fields classified as SENSITIVE_PII, FINANCIAL, REGULATED, or HIGHLY_SENSITIVE are replaced with `[REDACTED:<tier>]` in log output.

**Pattern-based redaction**: Even for fields not in the registry, string values are scanned for sensitive patterns:

| Pattern | Regex | Replacement |
|---------|-------|-------------|
| Email addresses | `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` | `[REDACTED:email]` |
| Phone numbers | `\+?[0-9]{1,4}[-.\s]?[0-9]{6,14}` | `[REDACTED:phone]` |
| Wallet addresses | `0x[a-fA-F0-9]{40}` | `[REDACTED:wallet]` |
| API keys | `[a-zA-Z0-9]{32,}` (in key-like contexts) | `[REDACTED:api_key]` |
| SSN patterns | `[0-9]{3}-[0-9]{2}-[0-9]{4}` | `[REDACTED:ssn]` |

### Logging Hygiene Rules

- Log messages must never contain raw PII, financial data, or credentials
- Structured log fields are individually redacted; the overall log structure is preserved
- Trace IDs, request IDs, and correlation IDs are always preserved (they are operational, not sensitive)
- Error stack traces are scanned for embedded sensitive values before logging
- Metrics and counters derived from sensitive data use only aggregate values

---

## Integration Points

### Service Integration Pattern

Every Aether service integrates with the control plane through a standard pattern:

```
1. Import: from shared.privacy import classification, access_control, retention
2. Classify: tier = classification.get_tier(field_name)
3. Authorize: access_control.check_access(user_role, purpose, tier)
4. Mask: result = access_control.apply_field_masking(data, user_role, purpose)
5. Redact logs: log_payload = access_control.redact_for_logging(payload)
6. Enforce retention: retention.check_retention(record)
7. Handle DSAR: plan = retention.create_deletion_plan(subject_id)
```

### Pre-Query Enforcement

Access checks happen before query execution, not after. The query planner receives the user's role and purpose, and the control plane restricts which tables, columns, and graph paths the query can touch. This prevents sensitive data from ever being loaded into memory for unauthorized requests.

### Audit Trail

Every access decision (allow or deny) is logged to the immutable audit trail with:

- Timestamp
- User/service identity
- Requested resource and fields
- Purpose declared
- Decision (allow/deny)
- Reason (role insufficient, consent missing, purpose mismatch, etc.)
- Classification tier of the requested data

This audit trail is itself classified as INTERNAL with `immutable` deletion behavior and `permanent` retention.
