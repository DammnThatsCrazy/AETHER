---
title: Preview Environments
slug: operations/preview-environments
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: experimental
since_version: "0.1.0"
estimated_read_minutes: 5
canonical_owner: platform@aether
source_files:
  - .github/workflows/frontend-preview.yml
  - config/staging_frontend_preview_iam_policy.yaml
  - deploy/aws/terraform/main.tf
  - services/backend/shared/security/cors.py
---

# Preview environments

Work moves **local → pull-request preview → staging → production**:

| Stage | What it is | Lifetime | Data |
|---|---|---|---|
| Local | A developer's machine | Always | Local fixtures |
| PR preview | The Aether app built from one pull request | Created on push, deleted when the PR closes or merges | Staging's (shared) |
| Staging (`main`) | The integrated product for Olympus staff and advisors | Persistent; sleeps outside its awake lease | Persistent staging database |
| Production | Customers | Persistent | Production |

A preview answers "does this branch look and behave right?" before merge.
Staging answers "does everything merged work together, with real accounts and
accumulated data?" Staging deploys `main`, and production receives the same
immutable release by explicit promotion, so the persistent environments cannot
drift from what was merged.

## Per-PR frontend previews

`.github/workflows/frontend-preview.yml` keeps the repository's pull-request
cadence (`config/verification_policy.yaml`): pull requests trigger hosted work
only when marked ready for review.

1. When a same-repository pull request is marked ready for review, the
   workflow builds the Aether app with the staging app's public `VITE_*`
   settings. It points the Auth0 redirect and logout URIs at the preview.
2. It deploys the build to branch `pr-<N>` of the staging preview Amplify app
   (`AETHER-staging-aether-app-preview`, not connected to the repository) and
   comments `https://pr-<N>.<preview domain>` on the pull request.
3. To refresh a preview after later pushes, or to preview a draft, a team
   member runs the workflow from `main` with the pull request number.
4. Every push to `main` (each merge) and an hourly sweep delete the preview of
   every pull request that is closed or merged.

A preview is only the frontend. It calls the staging API and signs in through
staging Auth0, so staging must be awake for a preview to do more than render.
The staging API allows exactly `https://pr-<N>.<preview domain>` origins
(`CORS_PREVIEW_ORIGIN_SUFFIX`, built into an anchored pattern by
`services/backend/shared/security/cors.py` and refused in production). The
staging Auth0 application accepts `https://*.<preview domain>` callbacks and
origins. Sign-in uses the bearer session token, so previews work on the
Amplify default domain, which is cross-site to the API.

### Security

The repository is public, so preview deployment never runs fork code with AWS
credentials. The workflow never uses `pull_request_target`. A fork's
`ready_for_review` run receives no OIDC token, and every deploy path also
requires the pull request's head repository to be this one; dispatch requires
write access. The OIDC role (`AetherStagingFrontendPreview`,
`config/staging_frontend_preview_iam_policy.yaml`) trusts only this
repository's `pull_request` runs and its runs on `main`. It can list, create,
deploy and delete `pr-*` branches of the preview app, and read the staging
app's public build settings; nothing else.

### Enabling it

1. Terraform creates the preview app when `enable_frontend_previews = true`
   (set in `profiles/staging.tfvars`) on the next staging apply. Read its id
   and domain from the `frontend_preview_app_id` and
   `frontend_preview_default_domain` outputs. The same apply sets the staging
   API's `CORS_PREVIEW_ORIGIN_SUFFIX` and the Auth0 preview URLs.
2. Create the IAM role from the manifest, substituting the account id and both
   app ids.
3. Set the repository variable `FRONTEND_PREVIEW_ROLE_ARN` to the role's ARN.
   The workflow finds both Amplify apps by their Terraform names
   (`FRONTEND_PREVIEW_APP_ID` and `STAGING_AETHER_APP_ID` override that when
   set).

Until step 3 is done, the workflow skips with a notice and deploys nothing.

## Databases

- **Staging keeps one persistent database.** Invitations, accounts and
  accumulated data are what staging vetting depends on, and migrations must be
  exercised against existing data, not only against a fresh seed. It costs
  little idle: Aurora Serverless v2 scales to zero after five idle minutes.
- **Frontend previews have no database.** They use staging's.
- **Full-stack previews (phase 2)** should each get a copy-on-write Aurora clone
  of staging, which is quick and cheap to create and delete, instead of a
  freshly seeded database. A seed never tests migrations against real-shaped
  data. The demo seeder remains for brand-new demo environments.

## Phase 2: full-stack previews

The `preview` deployment profile (`profiles/preview.tfvars`,
`scripts/release/ephemeral_env.py`, `ephemeral-ttl-guard.yml`) already
describes a cost-capped, TTL-leased environment with no NAT. It is one shared
environment today. Making it per pull request needs:

- a per-PR name, so each PR's backend service, database clone and secrets are
  separate;
- an Aurora clone of staging on open, deleted on close;
- per-PR Auth0 callback URLs (the wildcard already covers the preview domain);
- the existing TTL guard, so a preview that is never closed still expires.

That is worth doing when backend changes need isolated testing before merge.
Until then, backend changes are vetted on staging after merge.
