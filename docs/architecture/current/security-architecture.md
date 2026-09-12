---
title: Security Architecture
slug: security-architecture
section: architecture
visibility: I
audience: [architect, security]
status: experimental
since_version: "0.1.0"
---

# Security Architecture

## Overview

Aether's security architecture covers authentication, authorization,
tenant isolation, data protection, and compliance controls across the
platform runtime.

## Key Areas

### Authentication and Authorization

- Tenant API authentication via signed tokens.
- Role-based access control within tenant scope.
- Service-to-service authentication for internal runtime.

### Tenant Isolation

- All graph state is tenant-scoped.
- Cross-tenant data access is architecturally prevented at the query layer.
- Tenant context is propagated through the full request lifecycle.

### Data Protection

- PII handling follows consent-purpose reconciliation.
- Blocked-PII rejection with audit trail.
- Region-policy enforcement (EU/UK/APAC restrictions).
- Encryption at rest and in transit.

### Compliance

- Consent-purpose reconciliation between compliance enum and the
  12-purpose registry.
- Model governance with consent-scoped training and inference gates.
- Audit logging for all state-changing operations.

## Current State

See `SECURITY.md` for the security overview and `docs/security/` for
detailed security documentation.
