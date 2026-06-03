---
title: Logging Review
slug: security/logging-review
section: security
visibility: I
audience: [security, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Logging Review

Review of what is logged, what must never be logged, and audit coverage.

## Principles

- **No secrets in logs.** Structured logging + `sanitize_metadata` keep
  secret-named keys and secret-looking values out of logs, audit events, and
  exports.
- **No raw cross-tenant data** in aggregate/operator logs.
- **Security-relevant events** are recorded in the tamper-evident audit ledger
  (access checks, policy decisions, break-glass, retention/DSR, connector config
  changes, drift resolution, billing/provider changes).

## Review checklist

- [ ] Correlation IDs present on requests; PII minimized in app logs.
- [ ] Audit ledger covers the sensitive-action set; chain verifies.
- [ ] Log retention aligns with [Data Retention Review](DATA-RETENTION-REVIEW.md).
- [ ] Metrics endpoint (`/v1/metrics`) exposes no sensitive labels.
- [ ] Alerting on auth failures, rate-limit spikes, repeated integration failures.

See [Audit Event Ledger](AUDIT-EVENT-LEDGER.md) and [Security Readiness](SECURITY-READINESS.md).
