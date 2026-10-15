---
title: "Release Policy"
slug: releases/release-policy
section: changelog
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# Release Policy

Aether uses SemVer.

## Pre-Production

Before public production, all versions must include one of:

- `alpha`
- `beta`
- `rc`

## Version Classes

| Version | Meaning |
|---|---|
| `0.x.x-alpha.x` | Internal/private alpha |
| `0.x.x-beta.x` | Stabilization candidate |
| `1.0.0-rc.x` | Public release candidate |
| `1.0.0` | First public production release |

## Required Release Files

Each version requires:

- `VERSION`
- `CHANGELOG.md`
- `docs/releases/vX.Y.Z.md`
- Updated package metadata
- Updated generated docs, if applicable
