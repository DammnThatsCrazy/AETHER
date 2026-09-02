---
title: "Stablecoin Intelligence — Domain Decisions"
slug: productization/economic-interoperability-intelligence/adr-stablecoin-decisions
section: operations
visibility: I
audience: [architect, dev-senior, ops]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/stablecoin/service.py
  - Backend Architecture/aether-backend/services/stablecoin/valuation.py
  - Backend Architecture/aether-backend/services/stablecoin/finality.py
canonical_owner: platform@aether
last_synced_commit: "4e6fdad"
---

# Stablecoin Intelligence — Domain Decisions

| # | Decision | Rationale |
|---|---|---|
| S1 | Deterministic `observation_id = sha256(chain_id, tx_hash, log_index, kind)` | Replays and multi-source ingestion dedupe structurally, no coordination needed |
| S2 | Canonical asset vs per-chain deployment split | One issuer asset, many contracts; valuation keys on deployment, flows on asset |
| S3 | Registry seeded from x402 verified contracts | Reuse the platform's only on-chain-verified asset list instead of a new curated one |
| S4 | Unresolved observations persist with `canonical_asset_id="unresolved"` | Registry gaps must be visible to operators, never silently dropped |
| S5 | Peg thresholds 25 bps (minor) / 100 bps (depeg) as code constants | Simple, auditable classification; snapshot evidence carries raw deviation |
| S6 | Finality = per-chain confirmation horizon + checkpoint engine | Matches how chains actually finalize; provisional rows are first-class |
| S7 | Reorg demotes only non-finalized rows; corrections append | Finalized financial history is immutable by contract |
| S8 | Flow aggregates versioned by `metric_version` | Recomputation is additive; consumers pick the version, history survives |
| S9 | Valuation sources CREDENTIAL_GATED; operator-submitted snapshots allowed | Honest about missing Chainlink credentials while keeping the surface usable |
