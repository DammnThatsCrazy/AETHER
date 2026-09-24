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
source_files:
  - services/backend/services/auth/routes.py
  - services/backend/repositories/repos.py
  - deploy/aws/terraform/modules/ecs/main.tf
  - .github/workflows/infrastructure.yml
  - .github/workflows/staging-lifecycle.yml
  - .github/workflows/terraform-promote.yml
  - scripts/release/bootstrap_staging_admin_key.py
  - scripts/release/check_staging_runtime_iam.py
source_hashes:
  ".github/workflows/infrastructure.yml": "sha256:3b2faac39d7159a6440fb3552df760bcb9aeebccf5d85c034f5c1fde04185348"
  ".github/workflows/staging-lifecycle.yml": "sha256:af994b96bd6c7a1997c1e516356be23e1782f7d8dbca01d9fcfd1b984a0575ec"
  ".github/workflows/terraform-promote.yml": "sha256:e26e2608beb6cac5287a3b521cc0e3b0eb441da41daa59627292b74f543d17a5"
  "deploy/aws/terraform/modules/ecs/main.tf": "sha256:ca2a52de871d72661439c932674799164c893d893be54a3fffaf40e377a855a1"
  "scripts/release/bootstrap_staging_admin_key.py": "sha256:096541627176be35c7699c30495602740fa0e44df25233c2d369258d1491f2e6"
  "scripts/release/check_staging_runtime_iam.py": "sha256:85aa09eb552d0d57d87a169c250d97bb2d9790b865530bcf3ab5b61760e97d60"
  "services/backend/repositories/repos.py": "sha256:8a3e6dfa6331ea90c484931ecf23c45458f20a412066ef7a2b2b726370aa07a5"
  "services/backend/services/auth/routes.py": "sha256:716020d7f01cd1309b397cb71acd3667f30b78bd7e2eebf39dd6cd90643425f5"
---

# AETHER first-admin bootstrap

The staging API key is not a value that can be invented in AWS, Auth0, or
Stripe. It is registered by the AETHER backend so the tenant, durable key
hash, permissions, and authentication cache all agree. Keep the two
credentials distinct: the AWS bootstrap token authorizes creation once; the
generated `ak_...` value is the durable GitHub Actions secret used by the
lifecycle.

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
5. The durable marker is unclaimed for a new bootstrap. If a prior request
   claimed it but stopped mid-write, only the exact same key and request may
   resume; any different or unverifiable candidate fails closed.

The endpoint creates the staging tenant, an admin user, and an API key with
the fixed `read`, `write`, `ingest`, `analytics`, `billing`, and `admin`
permissions. The operator generates the raw key and stores it as the GitHub
repository secret before calling the endpoint. The backend stores only its
hash. The durable marker binds the tenant and key hash to the request, making
an identical retry safe after a lost HTTP response while rejecting a different
key or request. A token-protected status read prevents overwriting an already
claimed credential.

## Automated lifecycle

Before a staging rehearsal dispatches a wake plan, the lifecycle workflow
validates the exact release run and manifest, requires its commit and lane to
match the selected main/profile inputs, verifies every packaged artifact
checksum, and checks the lane's explicit identity evidence. It also validates
the delivery and rehearsal credential contracts, confirms the configured
`AetherStagingDeploy` principal and ECR pull policy, and checks the live ECS
task-definition/secret-mount contract. It verifies the active staging
DynamoDB cache table and simulates the live application task-role permissions
against that exact table before planning a wake. The pilot lane additionally
proves that the GitHub credential can create and remove the disposable secret
used by the post-readiness admin bootstrap. Any failed gate stops before
Terraform wake planning; none of these checks reads secret values.

Before any staging apply, the canonical `terraform-promote.yml` workflow
preflights the AWS one-time bootstrap secret and GitHub repository-secret
writeability. The AWS preflight reads the pilot-required
`aether/first-admin-bootstrap-token` under the dedicated value-read-only
Secrets Manager role, which also proves the configured KMS decrypt path; it
checks that the raw token is at least 32 characters with no surrounding
whitespace, without printing values. For pilot apply, GitHub access
uses `WORKFLOW_DISPATCH_TOKEN` first and `TF_AMPLIFY_GITHUB_ACCESS_TOKEN`
second, never the underprivileged workflow `GITHUB_TOKEN`. The helper writes a
random disposable repository secret, deletes it, and confirms by listing
secret names that it is absent. Failure at any part of either preflight blocks
Terraform apply. Lifecycle-triggered and direct Terraform applies pass through
the same gate.

The pilot plan is also revalidated immediately before apply and fails closed if
the wake/sleep plan would replace an ECS service or scaling target, remove
workflow-managed Application Auto Scaling tags, delete an Aether Auth0 resource,
or mutate deferred Auth0 resources. This guard protects the bootstrap lifecycle
from partial infrastructure replacement; it does not change the one-time
key/marker contract below.

The reviewed Terraform plan has a lane-specific credential-shape contract. The
pilot plan accepts a missing or stale `STAGING_ADMIN_API_KEY`, because the
durable key is created only after the backend is awake and `/v1/ready`; the full
lane still requires a pre-existing `ak_...` key before planning. This exception
does not relax the post-readiness `/v1/me` verification or the one-time marker
rules below.

After the approved release is running, migrations complete, and `/v1/ready`
returns ready, the lifecycle workflow runs
`scripts/release/bootstrap_staging_admin_key.py`:

1. If the configured `STAGING_ADMIN_API_KEY` authenticates through `/v1/me`
   with admin scope, the workflow preserves it and passes it to later steps via
   a masked `GITHUB_ENV` entry.
2. If it is absent, malformed, or definitively rejected with HTTP 401/403, the
   pilot helper checks the token-protected marker. For a shape-valid stored
   candidate, the status endpoint reports only whether its hash matches the
   marker; it never returns the hash or key. A matching candidate resumes the
   identical idempotent request. A claimed marker bound to another candidate,
   network errors, non-authentication HTTP errors, malformed status responses,
   and an authenticated non-admin key fail closed without replacing the secret.
3. If the marker is unclaimed, the helper generates a fresh key, writes it to
   the GitHub repository secret through stdin, and confirms the secret name is
   present before the one-time POST. It does not promote a rejected saved key
   when there is no durable claim proving that key belongs to this bootstrap.
   If the marker is claimed and matches the saved candidate, it resumes the
   identical request without rewriting the GitHub secret. The bootstrap token
   comes from AWS Secrets Manager and is passed only to the helper process.
4. The helper verifies `/v1/me` admin scope, registers the key with the Actions
   runner's mask command, and writes it to `GITHUB_ENV`. Later rehearsal,
   capability, and cleanup steps use that job-scoped value; it is never
   uploaded as an artifact or printed as ordinary output.

The full lane does not enable the bootstrap route and still requires a
pre-existing durable admin key. The pilot route may remain configured after the
handoff: the durable database marker allows only an identical request retry
and rejects a different key or request. If an operator elects to close the
route afterward, do so through a reviewed Terraform change; never edit the
running task out of band.

The fixed `SMOKE_API_KEY` remains required for the standalone smoke action and
live redeploy action, but not for the full rehearsal because that path creates
isolated run-scoped data-plane keys. The canonical delivery the rehearsal
dispatches therefore runs with `rehearsal_smoke=true`, which defers only its
fixed-key golden-path smoke to the rehearsal's authenticated capability checks. Never put the raw admin key or AWS
bootstrap token in source, plans, logs, or artifacts.

If a retry is needed, reuse the same saved key and request from the helper. Do
not generate a second key after the marker is claimed, change the token, or
widen IAM permissions. A marker bound to a different key is a recovery stop,
not permission to overwrite the durable GitHub secret.
