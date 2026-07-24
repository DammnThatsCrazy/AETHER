---
title: Repo Consistency Ownership
slug: source-of-truth/repo-consistency-ownership
section: source-of-truth
visibility: I
audience: [dev-senior, ops, architect]
status: stable
since_version: "8.9.0"
source_files:
  - docs/source-of-truth/repo_consistency_ownership.json
  - scripts/validate_consistency_ownership.py
  - scripts/repo_doctor.py
canonical_owner: platform@aether
estimated_read_minutes: 5
toc_depth: 3
---

# Repo Consistency Ownership

AETHER treats docs, generated docs, contracts, SDK exports, TypeScript declarations, and version metadata as release-contract surfaces. Source changes must move with their derived surfaces in the same PR.

The machine-readable owner map is `docs/source-of-truth/repo_consistency_ownership.json`. `scripts/validate_consistency_ownership.py` reads that map and is run by `scripts/repo_doctor.py`.

## Required source-to-derived ownership

| Source change | Required derived/check surfaces |
| --- | --- |
| `pyproject.toml` version | all package versions, docs version metadata, generated docs |
| backend route added/changed | generated API docs, route index, contract validation, frontend/client types if applicable |
| event schema changed | contract docs, SDK types, validation fixtures, generated docs |
| consent/tenant/auth behavior changed | source-linked docs, contract validation, tests |
| SDK public method changed | package exports, `src/index.ts`, declaration output, SDK release alignment |
| package public type changed | barrel exports, TypeScript build, declaration files |
| Profile 360 route/model changed | docs, frontend types, tests, Kyber/SHIKI surfaces if applicable |
| Kyber operator route/model changed | docs, frontend types, tests, operator docs |
| generated docs source changed | `docs/_generated/`, `docs/REPO-INDEX.md`, `docs/AUTOMATION.md` |
| docs source-linked content changed | frontmatter validation, drift validation, reviewed sync stamp |
| durable jobs platform changed | `JOBS_PLATFORM.md` review/restamp, generated docs, jobs tests |
| tenant import engine changed | imports contract twin, `IMPORT_FAILURES.md`, generated docs, import tests |
| measurement integrity plane changed | metric registry contract (TS/Py/doc mirrors), `MEASUREMENT_RESTATEMENT.md`, measurement tests |
| workflow/check command changed | Makefile, workflows, docs, repo_doctor tests |
| Aether/Kyber production data source changed | `scripts/validate_frontend_data_truth.py` source guardrail and explicit production-bundle scan |

## Single-owner generated docs rule

`docs/REPO-INDEX.md` and `docs/AUTOMATION.md` are owned only by `scripts/sync_docs.py`. They must not be stamped by source-linked drift tooling, and contributors must not hand-edit them. `docs/_generated/` is owned by `scripts/docs_extract/run_all.py` and the extractors under `scripts/docs_extract/`.

## Required local preflight

Before opening or updating a PR:

1. Run `make repo-doctor-fix`.
2. Run `make ci-check`.
3. Commit all generated docs and sync outputs.
4. Do not hand-edit generated docs.
5. Do not bypass TypeScript/package export failures.
6. If backend routes, schemas, contracts, SDK public types, Profile 360, or Kyber surfaces changed, update the required ownership-map surfaces.
7. PR is not complete until `make ci-check` exits 0.

The full repo-doctor path runs `python scripts/validate_frontend_data_truth.py`
before frontend builds, then runs the validator with `--build-bundles` to build
Aether and Kyber using explicit production configuration and inspect emitted
artifacts. The test-only allowlist is limited to dedicated test directories and
`*.test.*`, `*.spec.*`, and `*.stories.*` files; production `src/mocks` and
`src/fixtures` directories are always violations.
