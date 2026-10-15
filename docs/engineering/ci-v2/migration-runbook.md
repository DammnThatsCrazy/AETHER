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
| 1. Repo accepts both spellings | Prepared in the open PR #793, **not yet merged** |
| 2. AWS trust: add `refs/heads/development` | **Done.** `AetherStagingFrontendPreview` now trusts both `Development` and `development`; verified by re-reading the policy |
| 3. Rename `Development` to `development` | **Done.** `origin` has only `development`; `Development` no longer exists |
| 4. Retarget rulesets | Not verified from this session |
| 5. Repo cleanup (drop capitalized spelling) | Pending, after step 1 merges |
| 6. AWS cleanup (remove `refs/heads/Development`) | Pending, after step 5; nothing uses the old name once it merges |
| 7. Amplify `development` app branch | Not verified from this session |

**Out of order:** the rename (step 3) landed before step 1. Until #793 merges,
workflow `branches:` filters and the `development-web.yml` deploy guard still
name only `Development`, so push-triggered runs and the `development` web deploy
do not fire for `development`. Merge #793 first; it is green on both
`verification / disposition` and `ci / verdict`.

## Rollback

Before step 5, both spellings work in the repo and in AWS, so renaming back is
safe. After step 6, restore the old subject in AWS and the old filters in the
repo before renaming back. A Git revert alone does not restore IAM or Amplify.
