---
title: Frontend Data Truth Inventory
slug: audits/frontend-data-truth-inventory
section: architecture
visibility: I
audience: [dev-senior, architect, ops]
status: stable
since_version: "0.1.0"
source_files:
  - apps/aether-web/
  - apps/kyber-web/
  - apps/demo/
  - scripts/validate_frontend_data_truth.py
  - scripts/docs_extract/extract_frontend_data_truth_inventory.py
reviewed_source_commits:
  - commit: "95e6c54f"
    reason: "Reviewed the Aether frontend route/history context fixes, explicit shared ESM imports, and Data Exchange E2E graph-scope fixture. Runtime data-truth counts and the test-only fixture classification remain unchanged, so no body update was required."
source_hashes:
  "apps/aether-web/": "sha256:b6fcb2aabac08b5d8fa6e9f98f971b44d0375580904e19654490d3e8653f87c8"
  "apps/demo/": "sha256:68e3f82d5ac29330519e833dc50bca0023c83e9d6e5b448f09129917617d1b7c"
  "apps/kyber-web/": "sha256:7be4cd8aec74ca8f2bd44a9fb8994037e3295536d26f4d1d0a59a61e360fdcef"
  "scripts/docs_extract/extract_frontend_data_truth_inventory.py": "sha256:e51b21de00c3d6a4b38993c3aa40c3988477edf2c9987b5bf3b987d11b27dd47"
  "scripts/validate_frontend_data_truth.py": "sha256:25de73c82ac07cdc52b7a9be8d7f8ef69ff50ca7ba735c1e8d51652dcf92636c"
---

# Frontend Data Truth Inventory

This audit records every original search finding across Aether, Kyber, and the
Demo App. The complete line-level inventory and terminal disposition is the
generated
`docs/_generated/frontend-data-truth-inventory.json` artifact; this document
states the classification and release interpretation.

## Final disposition

- Historical findings classified in PR1: 714.
- Pending historical findings: 0.
- Runtime Aether mock or fixture imports: 0.
- Runtime Kyber mock or fixture imports: 0.
- Runtime Demo App mock or fixture imports: 0.
- Browser MSW startup paths and public workers: 0.
- Remaining fixtures are test-only and live under the validator's narrow test
  path allowlist.

The generated artifact distinguishes:

- remediated runtime behavior;
- reviewed non-operational UI copy or static product metadata; and
- retained test-only fixture support.

## Classification policy

- Runtime synthetic operational data is removed from production entrypoints or
  represented only by explicit backend seed records.
- Test fixtures remain isolated under `test`, `tests`, `test-support`,
  `__tests__`, or test/story filenames and cannot be transitively imported by a
  production entrypoint.
- Static product catalogs may remain only when they describe supported
  capabilities. Tenant-specific connection, health, usage, billing, evidence,
  and operational status always come from the backend.
- A failed request is unavailable, never a successful empty response.
- The Demo App is a real API client for backend seed status and provenance. It
  contains no canonical operational dataset.

## Enforcement

`python scripts/validate_frontend_data_truth.py` is the authoritative source
and bundle gate. The inventory generator preserves historical evidence; it
does not make runtime source clean. CI runs both the validator and the
production bundle scan.
