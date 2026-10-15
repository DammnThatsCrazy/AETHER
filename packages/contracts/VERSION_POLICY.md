---
title: Contract Version Policy
slug: contracts/version-policy
section: reference
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# Contract Version Policy

## Schema versioning

Each contract schema carries a `schema_version` integer field. The version
increments on any breaking change to required fields, field types, or
validation constraints.

### Compatibility rules

| Change type | Version impact | Migration required |
|---|---|---|
| Add optional field | No increment | No |
| Add required field | Increment | Yes |
| Remove field | Increment | Yes |
| Change field type | Increment | Yes |
| Tighten validation | Increment | Yes |
| Relax validation | No increment | No |

## Registry versioning

Platform registries (`packages/shared/contracts/*.json`) use content-addressed
validation — the registry structure and cross-references are validated at CI
time by `scripts/validate_contracts.py` and domain-specific validators. There
is no separate version number; the CI gate is the compatibility check.

## Pre-1.0 policy

During the `0.x` series, breaking changes are permitted between minor versions.
Consumers must pin to a specific minor version and test upgrades explicitly.
The `supported` SDK compatibility band (>= 0.1.0) tracks the minimum contract
version that SDKs must handle.

## Validation

```bash
python scripts/validate_contracts.py
make repo-doctor
```
