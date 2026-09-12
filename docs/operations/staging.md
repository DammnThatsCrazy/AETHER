---
title: Staging Operations
slug: ops-staging
section: operations
visibility: I
audience: [ops, architect]
status: experimental
since_version: "0.1.0"
---

# Staging Operations

## Overview

The staging environment is a production-like environment used for
integration testing, design partner access, and release validation.

## Environment Details

Staging environment configuration is managed through deployment
profiles. See `config/deployment_profiles.yaml` for the current
staging profile.

## Deployment Process

Staging deployments follow the delivery orchestrator pipeline:

1. Release candidate created from verified commit.
2. Staging state machine validates prerequisites.
3. Deployment profile applied.
4. Post-deployment health checks executed.

## Access Control

- Staging uses the same authentication model as production.
- Design partner tenants are provisioned in staging.
- Test tenants are available for integration testing.

## Monitoring

- Health checks run continuously post-deployment.
- Staging metrics are separate from production.
- Alerts are routed to the development team.

## Current State

Staging environment is defined but deployment automation is in
progress. See `docs/architecture/target/staging-readiness.md` for
the readiness checklist.
