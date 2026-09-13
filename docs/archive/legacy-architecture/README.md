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

## Archived root-era material

The root-era architecture folders from the Truth Reset are no longer present at
the repository root. Their retained historical material is physically grouped
here:

- `backend/` — orphaned modules, migrations, and superseded service shells
- `data-ingestion-layer/` — deprecated TypeScript ingestion duplicate
- `data-lake-architecture/` — deprecated TypeScript lake duplicate
- `aws-deployment/` — superseded root-level AWS runner and Terraform notes
- `gdpr-soc2/` — superseded compliance tree documentation

Active implementations live under `services/`, `deploy/aws/`, and
`contracts/smart-contracts/`. Do not add code to this archive; update the
canonical implementation and link the historical material only when it is
needed to explain a migration or compatibility decision.
