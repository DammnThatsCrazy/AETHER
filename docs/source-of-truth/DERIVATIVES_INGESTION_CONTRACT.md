---
title: Derivatives Ingestion Contract
slug: source-of-truth/derivatives-ingestion-contract
section: source-of-truth
visibility: I
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/services/derivatives/runtime_routes.py
  - Backend Architecture/aether-backend/services/derivatives/adapters/base.py
  - Backend Architecture/aether-backend/services/derivatives/streams.py
canonical_owner: platform@aether
last_synced_commit: "03ab3a6"
---
# Derivatives Ingestion Contract

The ingestion contract is source to Bronze to Silver to canonical state to graph or Gold product surfaces. Bronze stores immutable native observations. Silver stores normalized facts. Canonical state stores tenant-scoped mutable projections. Gold surfaces aggregate behavior, risk, execution quality, campaign outcomes, and profile dimensions.

Every ingested record requires a deterministic idempotency key such as provider plus deployment plus account plus source record ID, provider plus market plus trade ID, chain ID plus transaction hash plus log index, or tenant plus source table plus fact ID.

Financial quantities use fixed precision decimal representations and database `NUMERIC(38, 18)` columns, never binary floating point.
