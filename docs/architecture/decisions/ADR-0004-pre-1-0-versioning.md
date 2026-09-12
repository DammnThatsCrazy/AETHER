---
title: "ADR-0004: Pre-1.0 Versioning"
slug: architecture/decisions/adr-0004-pre-1-0-versioning
section: architecture
visibility: P
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
---

# ADR-0004: Pre-1.0 Versioning

## Status

Accepted

## Context

Aether has not reached public production. Version numbers should reflect actual product maturity.

## Decision

All versions before public production use SemVer pre-release identifiers (alpha, beta, rc). The first canonical baseline is `0.1.0-alpha.0`.

## Consequences

- No version may claim production, GA, stable, or enterprise-ready status
- Historical work is documented as retrospective milestones
- Version bumps require updating VERSION, CHANGELOG.md, and release docs

## Enforcement

- `scripts/bump_version.py --check` validates version alignment
- Release policy documented in `docs/releases/release-policy.md`
