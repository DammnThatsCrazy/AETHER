---
title: Readme
slug: archive/legacy-architecture/readme
section: reference
visibility: I
audience: [dev-senior, architect]
status: experimental
since_version: 0.1.0
---
# Archived Material

This folder contains legacy or superseded documentation.

Canonical current documentation lives under:

- `docs/source-of-truth/`
- `docs/architecture/current/`
- `docs/architecture/target/`

This material is retained for historical reference only.

## Legacy Root Folders

The following root-level folders contain legacy architecture that predates the current contract-governed, graph-first architecture:

- `Backend Architecture/` — See `docs/architecture/current/runtime-architecture.md`
- `Data Ingestion Layer/` — See `docs/architecture/current/ingestion-architecture.md`
- `Data Lake Architecture/` — See `docs/architecture/current/ingestion-architecture.md`
- `AWS Deployment/` — See `docs/operations/` (pending)
- `ML Models/` — Active subsystem, see `docs/ML-TRAINING-GUIDE.md`
- `Smart Contracts/` — See `docs/archive/legacy-architecture/`
- `GDPR & SOC2/` — See `docs/security/compliance-roadmap.md`
- `Agent Layer/` — Active subsystem, see `docs/AGENT-LAYER-PRODUCTION.md`

Note: Some of these folders (`Backend Architecture/`, `ML Models/`, `Agent Layer/`) contain active code and tests, not just documentation. They will be migrated to `services/` in a future restructuring.
