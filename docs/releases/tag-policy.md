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

## Rule

No PR may introduce a version bump without updating:

- `VERSION`
- `CHANGELOG.md`
- `docs/releases/`
- Package metadata
- Release validation output
