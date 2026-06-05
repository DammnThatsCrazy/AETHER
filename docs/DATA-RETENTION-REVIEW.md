---
title: Data Retention Review
slug: compliance/data-retention-review
section: compliance
visibility: I
audience: [security, compliance, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Data Retention Review

Periodic review of retention policies and deletion behavior. Builds on the
implemented retention layer (`services/security/retention.py`, see
[Data Retention](DATA-RETENTION.md)).

## Review checklist

- [ ] Per-resource retention windows are appropriate (events, profiles,
      recommendations, decisions, actions, dispatches, outcomes, audit_exports,
      billing_records, audit_log).
- [ ] **Audit logs and billing records are never hard-deleted** when retention
      requires preservation (`preserve_audit_stub`).
- [ ] Deletion uses the right behavior (hard_delete / soft_delete / anonymize /
      preserve_audit_stub) per resource + legal-hold metadata respected.
- [ ] DSR erasure requests reconcile with retention + legal holds.
- [ ] Backups inherit retention/erasure semantics (document in
      [Backup & Restore](BACKUP-RESTORE.md) when available).

## Evidence

Default policies are seeded and listable; data requests are audited. Export via
the governed audit export. Not legal advice — confirm windows with counsel
(see [GDPR Readiness](GDPR-READINESS.md), [Privacy Review](PRIVACY-REVIEW.md)).
