---
title: AETHER First-Admin Bootstrap
slug: operations/first-admin-bootstrap
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: experimental
since_version: "0.1.0"
estimated_read_minutes: 5
canonical_owner: platform@aether
---

# AETHER first-admin bootstrap

The staging API key is not a value that can be invented in AWS, Auth0, or
Stripe. It is created by the AETHER backend so the tenant, durable key hash,
permissions, and authentication cache all agree. Keep the two credentials
distinct: the AWS bootstrap token authorizes creation once; the returned
`ak_...` value is the durable GitHub Actions secret used by the lifecycle.

## Contract

`POST /v1/auth/bootstrap/first-admin` is a one-time, staging-only route. It
requires all of the following:

1. `FIRST_ADMIN_BOOTSTRAP_ENABLED=true` in the pilot staging task only. The
   Terraform pilot overlay supplies this flag and the full/production lanes
   explicitly set it to `false`.
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
2. Wake the pilot task through the reviewed lifecycle/promotion path. The
   task must expose the route only through the pilot overlay and must mount the
   token from Secrets Manager; do not enable it for production.
3. Call the route over the certificate-covered staging hostname with the
   token from Secrets Manager and a tenant name. Capture the returned `ak_...`
   key in the protected GitHub staging secret `STAGING_ADMIN_API_KEY` without
   printing it. Never put the AWS bootstrap token in that GitHub secret.
4. Run the full rehearsal. Its preflight rejects a non-`ak_...` value before
   wake, and its post-wake `/v1/me` probe verifies HTTP 200 plus admin scope
   before static publication, migrations, or tenant mutation.
5. The pilot route may remain configured after the handoff: the durable
   database marker makes it single-use and rejects every replay. If an
   operator elects to close the route afterward, do so through a reviewed
   Terraform change; never edit the running task out of band.
6. Use the stored `STAGING_ADMIN_API_KEY` for authenticated smoke and cleanup
   steps. Never put the raw key in source, logs, plans, or artifacts.

If the call fails after the durable marker is written, stop and review the
database record before attempting any recovery. Do not retry by changing the
token or widening IAM permissions.
