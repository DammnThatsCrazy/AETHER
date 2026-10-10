---
title: Frontend Data Truth Inventory
slug: audits/frontend-data-truth-inventory
section: architecture
visibility: I
audience: [dev-senior, architect, ops]
status: stable
since_version: "0.1.0"
source_files:
  - apps/aether/
  - apps/kyber/
  - frontend/demo/
  - scripts/validate_frontend_data_truth.py
  - scripts/docs_extract/extract_frontend_data_truth_inventory.py
reviewed_source_commits:
  - commit: "95e6c54f"
    reason: "Reviewed the Aether frontend route/history context fixes, explicit shared ESM imports, and Data Exchange E2E graph-scope fixture. Runtime data-truth counts and the test-only fixture classification remain unchanged, so no body update was required."
source_hashes:
  "apps/aether/": "sha256:ac965cce5d0d77357541429b0fe69c186434311330b970dc25261b6ab8fee6da"
  "apps/kyber/": "sha256:3e59889b8e3577802ef423eae62bcb7141ab4c176de87a24d7c40cc5a2f04aca"
  "frontend/demo/": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  "scripts/docs_extract/extract_frontend_data_truth_inventory.py": "sha256:e51b21de00c3d6a4b38993c3aa40c3988477edf2c9987b5bf3b987d11b27dd47"
  "scripts/validate_frontend_data_truth.py": "sha256:b3db593b8648f2cdfa222b4812b447bf292bd9e5657ff57eea4058b6c7a0cd50"
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

The Kyber Journey Explorer's Web3 verification action calls the tenant-scoped
backend RPC verifier and renders its returned status. It does not infer chain
execution from local UI state or infer payment settlement from an execution
receipt.

The Aether Journey Explorer's economic-operation panel calls the tenant-scoped
Journey evidence endpoint. It displays only explicit source-linked operation
references and reports an empty state when the journey contains no shared
commerce reference; it does not synthesize a match or copy operation value.

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
