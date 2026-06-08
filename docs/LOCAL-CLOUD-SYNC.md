---
title: "Local / Cloud Sync Contract"
description: "How local and cloud workspaces stay aligned with origin/main"
category: "internal"
---

# Local / Cloud Sync Contract

`origin/main` is canonical. Local and cloud workspaces are disposable.

## Required before work

```bash
git fetch origin
git status
git rebase origin/main
```

## Required before PR

```bash
make repo-doctor
git status --short
```

## Generated docs rule

Generated docs are **never manually edited**.  
Fix source or generator, then regenerate:

```bash
make repo-doctor-fix
make repo-doctor
```

## Source-linked docs rule

If a source file linked by a doc with `source_files:` frontmatter changes,
the doc must be **reviewed** before `last_synced_commit` is updated.

```bash
# Review stale docs:
python scripts/docs_drift.py --strict

# After review and doc update only:
python scripts/docs_drift.py --update
```

## Operating rule

```
Code changed
  → canonical source updated
  → generated docs regenerated (make repo-doctor-fix)
  → authored docs reviewed / updated
  → source-linked docs stamped (after review)
  → make repo-doctor passes
  → CI passes
  → PR can merge
```

## Enforcement

This repo enforces the rule through:

| Layer | File |
|---|---|
| Orchestrator | `scripts/repo_doctor.py` |
| Makefile gate | `make repo-doctor` / `make ci-check` |
| Pre-commit hooks | `.pre-commit-config.yaml` |
| GitHub Actions | `.github/workflows/repo-consistency.yml` |
| Cloud environment | `.devcontainer/devcontainer.json` |
| Agent instructions | `CLAUDE.md` |
