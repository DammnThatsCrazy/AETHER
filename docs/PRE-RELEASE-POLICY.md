---
title: Pre-release Version and History Policy
slug: reference/pre-release-policy
section: reference
visibility: I
audience: [exec, dev-senior, ops]
status: stable
since_version: "0.1.0"
canonical_owner: release@aether
estimated_read_minutes: 4
toc_depth: 3
---
# Pre-release version and history policy

## Current status

Aether has not made a production release. The repository therefore uses
`0.1.0` as its shared development baseline. This number describes repository
state; it is not a production-readiness or certification claim.

## Historical entries

Existing numbered changelog sections and version references before this reset
are internal development milestones. They must not be represented as public
releases unless matching immutable release evidence exists.

Do not manufacture or backdate Git tags. If historical evidence is incomplete,
preserve the work chronologically in the changelog and label it as internal.

## Future releases

A release requires all of the following:

1. a version change made through `scripts/bump_version.py`;
2. a reviewed changelog entry and synchronized package/native surfaces;
3. passing canonical repository and release gates;
4. immutable build provenance and release artifacts;
5. a tag created from the exact approved commit after the evidence exists.

Until the first supported public release, use `0.x.y` semantic versions:

- patch: compatible fixes and documentation corrections;
- minor: new or materially changed pre-release capabilities;
- major: reserved for the first explicitly approved stable contract line.

Readiness reports describe evidence and controls. They do not imply production
deployment, formal certification, or a public release.
