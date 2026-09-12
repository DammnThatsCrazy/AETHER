---
title: SDK Version Compatibility
slug: version-compatibility
section: sdks
visibility: P
audience: [dev-senior]
status: experimental
since_version: "0.1.0"
---

# SDK Version Compatibility

## Overview

SDK version compatibility defines which SDK versions are supported,
deprecated, or read-compatible with the current platform version.

## Compatibility Tiers

| Tier | Meaning | Support Level |
|---|---|---|
| Supported | Current and recent versions | Full support, bug fixes |
| Deprecated | Older versions still functional | Security fixes only |
| Read-compatible | Very old versions, read path works | No fixes, upgrade required |

## Version Bands

SDK version bands are enforced by the platform. Fail-closed date
enforcement is staged behind default-OFF flags.

## Upgrade Policy

- SDKs should track the latest supported band.
- Deprecated SDKs will receive security patches only.
- Read-compatible SDKs may lose functionality in future platform
  versions.

## Validation

Version compatibility tiers are validated by the CI contract suite
(Gate H: supported/deprecated/read-compatible bands preserved).
