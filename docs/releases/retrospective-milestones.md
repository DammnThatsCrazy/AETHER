---
title: "Retrospective Milestones"
slug: releases/retrospective-milestones
section: changelog
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# Retrospective Milestones

These milestones document internal architecture and productization work completed before Aether's first public release.

They are not public production releases.

## 2026-09 — Repository Truth Reset

Status: In progress
Release type: internal consolidation
Public version: none
Canonical version after reset: `0.1.0-alpha.0`

### Added

- Canonical repo structure.
- Source-of-truth documentation model.
- SDK parity documentation.
- Connector lifecycle documentation.
- Release and version policy.

### Changed

- Reorganized root architecture folders under `docs/`.
- Moved legacy docs into `docs/archive/`.
- Normalized SDK endpoint language to `/v1/batch`.
- Normalized product language around Signals, Syndicates, Value, Profiles, Agents, Journeys, Communications, Risk, and Lenses.

### Removed

- Stale root-level architecture folders.
- Deprecated SDK endpoint references.
- Misleading release/version claims.

### Known Gaps

- Full SDK parity enforcement pending.
- Connector capability matrix pending.
- Generated docs inventory pending.
- Full route inventory pending.
