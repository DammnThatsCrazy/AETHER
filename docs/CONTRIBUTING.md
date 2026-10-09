---
title: Contributing
slug: contributing
section: reference
visibility: I
audience: [dev-senior, ops]
status: stable
since_version: "0.1.0"
source_files:
  - AGENTS.md
  - Makefile
  - scripts/repo_doctor.py
  - docs/source-of-truth/REPO_CONSISTENCY_OWNERSHIP.md
canonical_owner: platform@aether
estimated_read_minutes: 3
toc_depth: 3
source_hashes:
  "AGENTS.md": "sha256:f2b594293edb54f1ecd03b5294b1bc0aec3665445fdca0a250afda2e212aca9c"
  "Makefile": "sha256:1ac92aff2d1bfe44eb4cd2c8a00a63241e20d3fa6af80020c8c55b3443f773c5"
  "docs/source-of-truth/REPO_CONSISTENCY_OWNERSHIP.md": "sha256:6e64f14b86dafb2b0b63ef06b763a8580a3c2cce7b76ef1e58eadcbc0734f245"
  "scripts/repo_doctor.py": "sha256:9fd5c10aef7856af605745c2b49b63951d911b2c570562e017d11b190e3277b0"
---

# Contributing

AETHER PRs are not merge-ready until the repository consistency contract passes locally or in the cloud-agent workspace. Keep implementation and blueprint work in a draft PR while changes accumulate. Local edits, diagnosis, and focused validation may use narrower checks; report those as local evidence rather than as PR completion.

## Required preflight

When preparing or updating a PR:

1. During implementation, keep the PR draft and use focused checks only; do not
   run aggregate gates or dispatch hosted PR CI for each intermediate push.
2. Integrate the blueprint, complete clarification/review and gap remediation,
   and update the ownership-required and authored documentation surfaces.
3. If docs, generator inputs, or contract inputs changed, run `make docs-generate`.
4. Review source-linked docs, then run `make docs-generate-changed
   DOCS_CHANGED="docs/a.md docs/b.md"` for only the reviewed pages whose
   declared source bytes changed. The allowlist rejects untracked or unlinked
   paths; omitting it retains the all-stale-pages behavior.
5. For routing-only or workflow work, use `make bootstrap-ci-control` and
   `make verification-execution-plan BASE=<ref> OUTPUT=<plan.json>` to inspect
   the dependency-aware plan without installing the application runtime.
6. Run `make validate-ci-execution-contracts` and `make validate-ci-performance-policy` when changing the adaptive CI plan, suite registry, evidence schemas, or latency policy.
7. If strict docs drift reports source-linked pages, review each listed page against its declared `source_files` and update authored content where behavior changed.
8. If backend routes, schemas, contracts, SDK public types, Profile 360, or Kyber surfaces changed, update the required ownership-map surfaces.
9. For deployment-profile changes, run `make resolved-feature-flags` so staging and production-lean each have an explicit, reviewed flag resolution.
10. Mark the completed PR ready for review; this starts the single hosted `verification / disposition` authority. Run `make verification-disposition BASE=<ref> EXECUTE=1` once for the final lane tip.
11. Run `make ci-check` only for broad local, trusted-main, nightly, release, or explicitly requested evidence; it is not a second blocking PR authority.
12. Commit generated and synced outputs when preparing the PR or when a commit was requested.
13. Do not hand-edit generated docs or bypass TypeScript/package export failures.
14. Do not call a PR merge-ready until the final disposition passes; report broad-gate results separately.

The hosted normal-PR merge check is the stable `verification / disposition`
status, and it starts on the `ready_for_review` finalization event. The broad
gate remains required local/trusted-main/nightly evidence and is not a second
blocking PR authority. Specialized workflows may provide supplementary
finalization evidence but do not independently block normal PR merges.

`make docs-check` is intentionally documentation-scoped. Its adaptive worker
provisions the backend/dev import surface required by source-backed generators,
without running the full application, ML, or security toolchain preflight.

Repository-doctor Python subprocesses inherit the interpreter running
`scripts/repo_doctor.py` (normally `.venv/bin/python` through the Makefile), so
the canonical gate does not depend on a separate bare `python` executable.

`make test-terraform-profiles` uses a dedicated `TF_DATA_DIR` with
`terraform init -backend=false`; cached remote-backend metadata from another
Terraform command therefore cannot make provider-mocked profile tests depend
on AWS credentials or remote state.

The canonical CI gate also validates the impact-aware verification router, the
environment capability requirement registry, the GitHub-only deployment
operator boundary, the delivery workflow authority map, the technical-debt
retirement ledger (`config/debt_retirement_ledger.yaml`: named paths must exist,
deadlines must be current, and a duplicate is deleted only with parity and usage
evidence), the capability overlay registry (`config/capability_overlays.yaml`:
a capability is an `enable-*` flag, never a deployment profile), the backend
service classification (`config/service_classification.yaml`: every service
directory has one lifecycle class), and frontend reachability
(`config/frontend_reachability.yaml`: every Kyber source file is reachable from
the app entry points or listed against a ledger row). These checks
validate repository policy; they do not claim that AWS credentials, runtime
validation, or production promotion occurred. The authority map records which
GitHub workflow currently owns each delivery authority while the workflow
estate is being converged; it does not make Kyber a deployment surface.
The gate also enforces parity among the canonical rights vocabulary and its
Python/TypeScript bindings and rejects parallel rights registries.
For a resumable staging attempt, `make deploy-staging` accepts
`STATE=<checkpoint.json>` and optionally `ENVIRONMENT_RESOLUTION=<json>`; each
resume is bound to the same release-candidate identity and pre-mutation
resolution decision.

## Generated docs

- `docs/_generated/` is generated by `python scripts/docs_extract/run_all.py`.
- `docs/REPO-INDEX.md` and `docs/AUTOMATION.md` are generated by `python scripts/sync_docs.py`.
- Do not add source-link metadata to sync-managed docs.
- Source-linked authored docs record `source_hashes` for each declared `source_files` path.
- Run `make docs-generate-changed DOCS_CHANGED="docs/a.md docs/b.md"` only after
  reviewing each listed doc against its sources. The path list scopes the hash
  update to that reviewed set.
- Do not globally restamp docs after a squash merge; unchanged source bytes keep the same hashes.

## Ownership map

When a source surface changes, update every required derived surface listed in `docs/source-of-truth/REPO_CONSISTENCY_OWNERSHIP.md`. The machine-enforced map is `docs/source-of-truth/repo_consistency_ownership.json`.
