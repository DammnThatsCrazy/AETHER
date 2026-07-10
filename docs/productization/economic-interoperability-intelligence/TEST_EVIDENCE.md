---
title: Test Evidence
slug: productization/economic-interoperability-intelligence/test-evidence
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - tests/unit/stablecoin/
  - tests/unit/derivatives/
  - tests/unit/interop/
  - tests/unit/test_economic_noesis_ooda_wiring.py
canonical_owner: platform@aether
last_synced_commit: 1f19190
---

# Test Evidence

## Gated suites (all green at release commit)

- Root `pytest tests/` — 1876 passed; the single failure
  (`test_agent_web_crawler_wrapper`) is pre-existing on the baseline
  (recorded in the current-state audit before any 8.12.0 change).
- `npm test` (packages/shared + workspaces) — passing, including
  `stablecoin.test.ts`, `interoperability.test.ts`, and updated
  `events-registry.test.ts` / `consent-model.test.ts` counts.
- `frontend/aether`: typecheck + vitest (79 tests / 21 files).
- `frontend/kyber`: typecheck + vitest (179 tests / 26 files).

## Domain coverage highlights

- Derivatives: every legal Order/Position FSM transition + illegal
  rejections; out-of-order; corrections; simulator determinism; adapter
  conformance; stream gap detect/recover/bounded-buffer (a real recovery
  bug was found and fixed by these tests); reconciliation; Decimal
  38,18 round-trips + no-float model introspection; typed-repo
  idempotency; route perms/tenant isolation/flag-off 404.
- Stablecoin: observation dedupe/resolution; depeg classification;
  finality reorg rollback (finalized immutable, corrections append);
  projector routing; routes; graph mutation shapes.
- Interop: TS↔Python lifecycle parity (regex over
  `INTEROP_LEGAL_TRANSITIONS`); LayerZero fixture decode + GUID vectors
  (fixtures share encoders with the decoder so they cannot drift);
  out-of-order correlation; reorg rollback; scaffold honesty; routes.
- Cross-cutting: event-registry well-formedness (purposes exist,
  silverProjection tokens map to registered projectors),
  consent-enforcement registry sync, Noesis/OODA/alert wiring (15
  tests), graph parity/exhaustiveness (existing tests extended
  automatically).

## Explicitly deferred (documented, never faked)

Load/chaos tests, live-RPC integration, live venue WebSockets,
ClickHouse gold query execution, staging soak.
