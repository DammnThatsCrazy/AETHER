---
title: Data Retention & Data Requests
slug: enterprise/data-retention
section: enterprise
visibility: I
audience: [ops, security, compliance]
status: stable
since_version: "13.0.0"
---

# Data Retention & Data Requests

`DataRetentionService` (`services/security/retention.py`) manages
`DataRetentionPolicy` records and processes `DataRequest`s (export / delete /
review) as structured, audited records.

## Implemented controls

- **Retention policies** per `resource_type` (`event`, `profile`,
  `recommendation`, `decision`, `action`, `dispatch`, `outcome`, `audit_export`,
  `billing_record`, `audit_log`) with `retention_days`, `legal_hold_supported`,
  `delete_behavior` (`hard_delete`/`soft_delete`/`anonymize`/
  `preserve_audit_stub`), and `enabled`.
- **Data requests** (`export`, `delete_entity`, `delete_tenant`,
  `retention_review`, `access_review`) tracked through
  `requested → in_progress → completed/denied/failed`.
- Guardrails enforced by the service:
  - audit logs are **never silently deleted**;
  - billing records are **preserved** when retention requires it;
  - cross-resource deletions require a **manifest**;
  - legal-hold notes are stored as **structured metadata**;
  - deletes preserve an **audit stub** where required.
- Every policy change and request transition emits a `SecurityAuditEvent`.

## Routes

- Tenant: `GET /v1/security/data-retention`, `POST /v1/security/data-requests`,
  `GET /v1/security/data-requests` (current tenant only).
- Kyber: `GET .../security/data-retention`,
  `POST .../security/data-retention/policies`,
  `PATCH .../security/data-retention/policies/{policy_id}`,
  `GET .../security/data-requests`,
  `PATCH .../security/data-requests/{data_request_id}`.

## Data retention model

Policies are declarative records evaluated when a data request is processed.
Processing is structured and audited rather than an immediate destructive purge —
a deliberate choice so deletions are reviewable and reversible until executed.

## Planned controls

- Scheduled enforcement workers that act on `retention_days` automatically.
- Per-field anonymization templates for the `anonymize` behavior.

## Known gaps / not certified

- Deletion currently records intent and preserves required stubs/manifests;
  full automated physical erasure across every downstream store is a planned
  control. No certification is claimed.
