---
title: "Tag Policy"
slug: releases/tag-policy
section: changelog
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# Tag Policy

## Product Tags

Product release tags use:

```txt
vX.Y.Z
```

Before production, product tags must include a pre-release suffix:

```txt
v0.1.0-alpha.0
v0.2.0-alpha.0
v0.5.0-beta.0
v1.0.0-rc.0
```

## Internal Milestone Tags

Internal milestones use:

```txt
milestone/<name>-YYYY-MM
```

Examples:

```txt
milestone/repo-truth-reset-2026-09
milestone/sdk-contract-spine-2026-09
```

## Legacy Tags

The remote carries 21 tags, `v1.0.0` through `v8.9.0`, created before the
repository truth reset. They follow the retired 1.x-8.x scheme, several have
GitHub releases attached, and none of them is a release of the current
`0.1.0-alpha.0` baseline.

They are kept as historical references and are not deleted or moved:
removing a tag would orphan its GitHub release page and break anyone who
pinned to it. Do not cite them as current releases, and do not create new
tags in the `v1.0.0`-`v8.x` range. `v8.8.0` and `v8.9.0` point at the same
commit.

## Baseline Tag

`v0.1.0-alpha.0` marks the repository truth reset baseline. Later pre-production
tags follow the version classes in the release policy.

## Rule

No PR may introduce a version bump without updating:

- `VERSION`
- `CHANGELOG.md`
- `docs/operations/releases/`
- Package metadata
- Release validation output
