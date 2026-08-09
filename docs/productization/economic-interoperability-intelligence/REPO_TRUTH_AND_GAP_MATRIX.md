---
title: Repo Truth and Gap Matrix — Economic & Interoperability Intelligence
slug: productization/economic-interoperability-intelligence/repo-truth-and-gap-matrix
section: operations
visibility: I
audience: [architect, ops, exec]
status: stable
since_version: "8.12.0"
source_files:
  - reports/economic-interoperability-intelligence/current-state-audit.md
canonical_owner: platform@aether
last_synced_commit: "41c79d4"
---

# Repo Truth and Gap Matrix

Pre-implementation truth (verified by audit, 2026-07-08) and what 8.12.0 changed.

| Area | Before 8.12.0 | After 8.12.0 |
|---|---|---|
| Derivatives contracts | PR1 (#395): `derivatives.ts`, `financial_activity` purpose, raw-SQL DDL, 5 doc stubs — zero runtime code | Full runtime: registries, adapters+simulator+conformance, FSMs, streams, reconciliation, P&L |
| Derivatives migrations | Raw SQL outside Alembic (`Backend Architecture/migrations/2026_07_derivatives_foundation.sql`) | Alembic adoption revision (idempotent IF NOT EXISTS replay); Alembic owns the tables |
| Stablecoin | x402 verification + web3 registries only; no stablecoin domain | Full observation domain: registry, observations, valuation/depeg, support, finality/reorg, flows |
| Interop | Nothing (greenfield); graph had no interop types | Full domain — all 7 adapters CREDENTIAL_GATED (fixture-proven decode + correlation; LayerZero V2 was the reference; the other six were scaffolds before the build wave and are now CREDENTIAL_GATED with supervised scan + operational-state surfaces) |
| Consent enforcement | Hardcoded stale purpose set missing `financial_activity` (defect) | Registry-derived at import; regression test |
| Consent purposes | No `economic_observability` / `cross_chain_observability` | Both added, fail-closed, 7y retention, no training |
| Events | No stablecoin/derivatives/interop families | 110 events, registry-driven projector routing |
| Graph | `STABLECOIN_ASSET`, `ACCEPTS_ASSET`, `PRICES_IN` existed | +8 vertex types, +82 edges, TS↔Py A2H parity maintained |
| Frontends | No economic surfaces | Aether 6 pages; Kyber 3 ops pages (flag-gated) |

## Known pre-existing issues (NOT introduced or fixed by this release)

- `tests/unit/test_agent_web_crawler_wrapper.py::test_top_level_web_crawler_wraps_canonical_worker` failed on the baseline (before any 8.12.0 change); later root-caused to a missing sandbox dependency (`bs4`) — passes unchanged once beautifulsoup4 is installed. No code fix was needed or made.
- Backend-internal `Backend Architecture/aether-backend/tests/` suite (not the gated root `tests/`) has pre-existing failures.
- Multiple Alembic heads existed prior to this release; the new revisions form a linear chain from `20260703_agentic_obs`.
