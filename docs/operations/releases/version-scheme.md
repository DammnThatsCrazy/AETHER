---
title: Version Scheme
slug: version-scheme
section: changelog
visibility: P
audience: [dev-senior, architect]
status: experimental
since_version: "0.1.0"
---

# Version Scheme

## Overview

Aether uses Semantic Versioning (SemVer) with pre-release identifiers
for all versions before the first public production release.

## Version Format

```
MAJOR.MINOR.PATCH[-PRERELEASE]
```

## Pre-Production Versions

Before public production, all versions must include a pre-release
identifier:

| Identifier | Meaning |
|---|---|
| `alpha` | Internal/private alpha |
| `beta` | Stabilization candidate |
| `rc` | Public release candidate |

## Version Classes

| Version Pattern | Meaning |
|---|---|
| `0.x.x-alpha.x` | Internal/private alpha milestone |
| `0.x.x-beta.x` | Stabilization/design-partner candidate |
| `1.0.0-rc.x` | Public release candidate |
| `1.0.0` | First public production release |

## Canonical Version Source

`pyproject.toml` owns the platform version. All other version
references (package.json, native SDKs, VERSION file) must match.

Check: `python scripts/bump_version.py --check`
Fix: `python scripts/bump_version.py <NEW_VERSION>`

## Current Version

See the `VERSION` file in the repository root.
