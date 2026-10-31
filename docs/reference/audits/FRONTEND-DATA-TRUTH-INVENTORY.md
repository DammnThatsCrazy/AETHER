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
  - commit: "453f71f9a"
    reason: "Reviewed the Access Kit webhook delivery-history type correction. It uses the API response type directly; tenant-owned webhook state, delivery history, and one-time secret behavior are unchanged."
source_hashes:
  "apps/aether-web/": "sha256:fb950cc837861d460891261fc0390265dc2475231cafd86af4accd79db4a1d89"
  "apps/demo/": "sha256:68e3f82d5ac29330519e833dc50bca0023c83e9d6e5b448f09129917617d1b7c"
  "apps/kyber-web/": "sha256:e7e4bf28d26fd793757e3d85e5bb1f2e6ac0d9d8d34c340fda1f977a46c30a49"
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

The Kyber Journey Explorer's Web3 verification action calls the tenant-scoped
backend RPC verifier and renders its returned status. It does not infer chain
execution from local UI state or infer payment settlement from an execution
receipt.

The Aether Journey Explorer's economic-operation panel calls the tenant-scoped
Journey evidence endpoint. It displays only explicit source-linked operation
references and reports an empty state when the journey contains no shared
commerce reference; it does not synthesize a match or copy operation value.

The customer webhook settings surface reads tenant-owned endpoint state and
bounded delivery history from the backend. Creation and secret rotation reveal
the generated signing secret once; active state follows a successful signed
test. The Usage & Plan view reads usage from the billing authority and labels
Access Kit interactions as non-billable rather than synthesizing a local count.

Agent 360's external-agent panels read tenant deployment/run evidence and a
separately source-labelled public marketplace catalog from backend routes. The
deployment view exposes explicit identity-binding status. Run evidence presents
economic matches, canonical delegation resolution, event-time grant evaluation,
and occurrence as separate states; source assertions are labelled, and an
external action remains unverified without a server-owned receipt. The catalog
display does not treat public listings as tenant graph nodes, and run coverage
is withheld when the evidence source is unavailable.

The Agent 360 behavior panel reads the backend-owned behavior read model and
renders its per-section `available` / `partial` / `unavailable` state; it does
not derive rates, preferences or decisions in the client.

The pages rebuilt from the Claude Design handoff (Home, onboarding, Profiles,
Profile 360, Graph, Campaigns, Campaign 360, Geography, Value, Agents,
Settings, Signals, Risk, Syndicates, Relationships, Communications, Journeys
and Episodes) ship none of the design's illustrative people, counts or live
counters. Every figure comes from an existing tenant read, and a design element
with no backing read is omitted or shown as not reported. The only static data
they add is base geography for the Graph globe and the Geography dot map
(continent outlines, a land bitmask, country centroids); it places tenant
locations and carries no tenant or operational values.

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
