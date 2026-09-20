---
title: Frontend Data Truth Inventory
slug: audits/frontend-data-truth-inventory
section: architecture
visibility: I
audience: [dev-senior, architect, ops]
status: stable
since_version: "0.1.0"
source_files:
  - frontend/aether/
  - frontend/kyber/
  - frontend/demo/
  - scripts/validate_frontend_data_truth.py
  - scripts/docs_extract/extract_frontend_data_truth_inventory.py
reviewed_source_commits:
  - commit: "95e6c54f"
    reason: "Reviewed the Aether frontend route/history context fixes, explicit shared ESM imports, and Data Exchange E2E graph-scope fixture. Runtime data-truth counts and the test-only fixture classification remain unchanged, so no body update was required."
source_hashes:
  "frontend/aether/": "sha256:321e7b9b42460dd822aaf205c9ee9b24dbc093015b151f12e4cbf186c49d4de1"
  "frontend/demo/": "sha256:3221e3fe4bac2b31ec70ad8d3d4ba11e7a4dd24912ff18f6af560b71cb12a621"
  "frontend/kyber/": "sha256:02f1923794aade37dd45fcaaa765fef4df2ca9e730fe6c67f04e6a2c5253b242"
  "scripts/docs_extract/extract_frontend_data_truth_inventory.py": "sha256:d32fbf2cfaccccb7420cf6ba0ef4e25030a27dc43fc03d50a04e168db8c0cc92"
  "scripts/validate_frontend_data_truth.py": "sha256:2447697a49724cf7ddd297f95f2cf6554761993cebe07b30c721c7af9c22ec7a"
---

# Frontend Data Truth Inventory

This audit records every original search finding across Aether, Kyber, and the
Demo App. The complete line-level inventory and terminal disposition is the
generated
`docs/_generated/frontend-data-truth-inventory.json` artifact; this document
states the classification and release interpretation.

## Final disposition

- Historical findings classified in PR1: 715.
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
