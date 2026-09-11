---
title: "ADR-0009: Release Tags and Internal Milestones"
slug: architecture/decisions/adr-0009-release-tags-and-internal-milestones
section: architecture
visibility: P
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
---

# ADR-0009: Release Tags and Internal Milestones

## Status

Accepted

## Context

Internal development work could be tagged as releases, creating false impressions of product maturity.

## Decision

Product release tags use `vX.Y.Z` with pre-release suffixes before production. Internal milestones use `milestone/<name>-YYYY-MM`. Historical work is documented as retrospective milestones, not fake releases.

## Consequences

- Git tags accurately reflect product maturity
- Internal work is documented but not presented as public releases
- Retrospective milestones preserve historical context

## Enforcement

- Tag policy documented in `docs/releases/tag-policy.md`
- Version validation prevents non-SemVer tags
