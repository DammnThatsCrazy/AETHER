---
title: CI V2 Branch Migration Runbook
slug: engineering/ci-v2-migration-runbook
section: operations
visibility: I
audience: [ops]
status: beta
since_version: 0.1.0
---

# Branch migration runbook: `Development` to `development`

Goal: three permanent branches, `development`, `staging`, `main`, without
losing history, closing open pull requests, or breaking a deploy role. Steps
marked **admin** need repository admin; the AWS steps need IAM write access.
See Status below for what has been done.

## Inventory (measured 2026-10-15)

**Remote branches:** `Development`, `staging`, `main`, plus feature branches.
`production-olympus` no longer exists on origin.

**Divergence from `origin/Development`:** `main` is 5 behind and 133 ahead
(Development ahead); `staging` is 2 behind and 102 ahead. `staging` is 33
ahead of `main`. Reconcile before treating `staging` as a promotion source.

**GitHub-OIDC roles in the AWS account** (read-only `ListRoles`, 22 roles):

| Role | Trusted subjects |
|---|---|
| `AetherStagingFrontendPreview` | `pull_request`, `refs/heads/main`, **`refs/heads/Development`** |
| `AetherStagingDeploy`, `AetherStagingPlan`, `AetherStagingSecretPreflight` | `refs/heads/main`, `refs/heads/staging`, environments `staging` / `staging-terraform` |
| `AetherStagingLifecycle`, `AetherStagingPlanReconcile` | `refs/heads/main` and/or environments only |

Only `AetherStagingFrontendPreview` pins the capitalized branch. The role is
created by hand from `config/staging_frontend_preview_iam_policy.yaml` (see
`docs/operations/PREVIEW-ENVIRONMENTS.md`), not by Terraform, so its live trust
policy must be edited by an operator and the manifest updated to match.

**Repository references to `Development`:**

- Workflow `branches:` filters in `infrastructure`, `functionality-proof`,
  `aether-test`, `kyber-e2e`, `repo-consistency`, `access-kit-container`,
  `development-web`, and `production-equivalent-ci`.
- `development-web.yml` deploy guard `github.ref == 'refs/heads/Development'`.
- `config/staging_frontend_preview_iam_policy.yaml` trust subject.
- `tests/unit/test_development_web_contract.py` and
  `tests/unit/test_frontend_preview_contract.py` assert the exact strings.
- Open pull requests that target `Development` (a delete-and-recreate would
  close them; use GitHub's branch rename, which retargets them).

GitHub Actions branch filters are case-sensitive, so a rename that is not
mirrored in these filters silently stops the workflows.

## Sequence

1. **Repo, additive:** allow both spellings in every `branches:` filter, in the
   `development-web.yml` guard, in the manifest trust list and in the two
   contract tests. Safe before the rename; merge first.
2. **AWS, additive (operator):** add
   `repo:DammnThatsCrazy/AETHER:ref:refs/heads/development` to the trust
   policy of `AetherStagingFrontendPreview`. Keep the old subject.
3. **Rename (admin):** Settings > Branches > rename `Development` to
   `development` (or `PATCH /repos/{owner}/{repo}/branches/Development/rename`
   with `new_name`). History and open PR targets are preserved. Update the
   default branch setting if it follows the rename.
4. **Rulesets (admin):** retarget branch rules to `development`, `staging`,
   `main`; require `ci / verdict` on `development` only after the cutover PR.
5. **Repo, cleanup:** remove the capitalized spelling from filters, the guard,
   the manifest and the tests.
6. **AWS, cleanup (operator):** remove the `refs/heads/Development` subject.
7. **Amplify:** confirm the `development` app branch builds from the renamed
   Git branch.

## Status (2026-10-15)

| Step | State |
|---|---|
| 1. Repo accepts both spellings | **Done.** Merged in #793 (green on `verification / disposition` and `ci / verdict`) |
| 2. AWS trust: add `refs/heads/development` | **Done.** `AetherStagingFrontendPreview` trusted both `Development` and `development` at this step; verified by re-reading the policy |
| 3. Rename `Development` to `development` | **Done.** `origin` has only `development`; `Development` no longer exists |
| 4. Retarget rulesets | **Done** (confirmed by the repo owner) |
| 5. Repo cleanup (drop capitalized spelling) | **Done** in #795: workflow filters, the `development-web` guard, the trust manifest and its tests name only `development` |
| 6. AWS cleanup (remove `refs/heads/Development`) | **Done.** The live `AetherStagingFrontendPreview` trust policy now lists `pull_request`, `refs/heads/main` and `refs/heads/development`; verified by re-reading it |
| 7. Amplify `development` app branch | **Done** (confirmed by the repo owner; the development web deploy ran on `development`) |

**Ordering:** the rename (step 3) landed before step 1, so push-triggered runs and
the `development` web deploy were not firing for `development` between the
rename and the merge of #793. #793 has merged and the cleanup is complete, so
only the lowercase spelling remains.

## Required-status cutover (admin)

The `verdict` job is named `ci / verdict`; GitHub requires status checks by job
name, so that is the exact context to require.

1. Settings > Rules > the `development` ruleset (and the `staging` and `main`
   rulesets): add the required status check `ci / verdict`.
2. Remove the required check `verification / disposition`. The workflow that
   produced it is deleted, so while it stays required no PR is mergeable.
3. If a merge queue is enabled, the `ci` workflow already runs on `merge_group`.
4. A `workflow_dispatch` replay publishes `ci / verdict (manual replay)`, which
   never satisfies the requirement.

Do steps 1 and 2 before merging the deletion PR. The PR that deletes the legacy
workflows cannot satisfy `verification / disposition` itself.

## Rollback

Before step 5, both spellings work in the repo and in AWS, so renaming back is
safe. After step 6, restore the old subject in AWS and the old filters in the
repo before renaming back. A Git revert alone does not restore IAM or Amplify.
