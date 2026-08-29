---
title: AETHER First-Admin Bootstrap
slug: operations/first-admin-bootstrap
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: experimental
since_version: "8.12.0"
estimated_read_minutes: 5
canonical_owner: platform@aether
---

# AETHER first-admin bootstrap

The staging API key is not a value that can be invented in AWS, Auth0, or
Stripe. It is created by the AETHER backend so the tenant, durable key hash,
permissions, and authentication cache all agree.

## Contract

`POST /v1/auth/bootstrap/first-admin` is a one-time, staging-only route. It
requires all of the following:

1. `FIRST_ADMIN_BOOTSTRAP_ENABLED=true` in the staging task only.
2. `FIRST_ADMIN_BOOTSTRAP_TOKEN`, injected from
   `aether/first-admin-bootstrap-token` in Secrets Manager, in the request
   header `X-Aether-First-Admin-Bootstrap-Token`.
3. `FIRST_ADMIN_BOOTSTRAP_EMAIL` set to the approved operator address.
4. A backend running with the staging database and cache available.
5. No existing first-admin bootstrap marker.

The endpoint creates the staging tenant, an admin user, and an API key with
the fixed `read`, `write`, `ingest`, `analytics`, `billing`, and `admin`
permissions. The raw key is returned once over HTTPS; it is never logged or
written to Terraform state or a workflow artifact. The durable marker blocks
replay, including after a process restart.

## Operator sequence

1. Confirm the staging plan and apply have passed their policy and cost gates.
2. Temporarily enable the bootstrap flag and approved email in the staging
   task configuration; do not enable it for production.
3. Call the route over the certificate-covered staging hostname with the
   token from Secrets Manager and a tenant name. Capture the returned key in a
   secret manager or protected GitHub staging-environment secret without
   printing it.
4. Set `FIRST_ADMIN_BOOTSTRAP_ENABLED=false` and roll the staging task so the
   route is closed. The durable marker remains as a second line of defense.
5. Use the stored `STAGING_ADMIN_API_KEY` for the authenticated smoke and
   cleanup steps. Never put the raw key in source, logs, plans, or artifacts.

If the call fails after the durable marker is written, stop and review the
database record before attempting any recovery. Do not retry by changing the
token or widening IAM permissions.
