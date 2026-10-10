---
title: Audit Logging
slug: audit-logging
section: security
visibility: I
audience: [security, compliance, ops]
status: experimental
since_version: "0.1.0"
---

# Audit Logging

## Overview

Aether maintains tamper-evident audit logs for all state-changing
operations, security events, and compliance-relevant activities.

## Audit Trail Structure

Each audit entry contains:

- Timestamp (UTC)
- Actor (user, service, or agent)
- Action (verb describing the operation)
- Resource (entity affected)
- Tenant context
- Outcome (success/failure)
- Correlation ID

## Audited Operations

| Category | Events |
|---|---|
| Authentication | Login, logout, API key usage |
| Authorization | Permission checks, access denials |
| Data access | Entity lookups, graph queries, exports |
| Data mutation | Entity updates, graph projections |
| Consent | Consent changes, DSR requests |
| Agent | Agent actions, decision records |
| Admin | Configuration changes, key provisioning |

## Tamper Evidence

Audit entries are chained using SHA-256 hashing, producing a
tamper-evident log where any modification to a prior entry
invalidates the chain.

## Retention

Audit logs follow the retention policy defined in the consent
registry. Security-relevant logs are retained for the maximum
retention period.

## Access

Audit logs are accessible through Kyber diagnostics for authorized
operators. Bulk export is available for compliance reviews.
