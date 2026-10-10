---
title: Alpha Release Checklist
slug: alpha-release-checklist
section: changelog
visibility: I
audience: [dev-senior, architect]
status: experimental
since_version: "0.1.0"
---

# Alpha Release Checklist

## Pre-Release Requirements

- [ ] Version bumped in `pyproject.toml` (canonical source)
- [ ] `python scripts/bump_version.py --check` passes
- [ ] `make ci-check` passes
- [ ] CHANGELOG.md updated with release entry
- [ ] Release notes doc created at `docs/releases/vX.Y.Z.md`
- [ ] VERSION file updated
- [ ] All package.json versions aligned

## Documentation Requirements

- [ ] Architecture docs reflect current state
- [ ] SDK docs reflect current capabilities
- [ ] Source-linked docs are not stale (`make docs-check`)
- [ ] Generated docs are regenerated (`make repo-doctor-fix`)

## Contract Requirements

- [ ] `python scripts/validate_contracts.py` passes
- [ ] SDK ingestion contract validated
- [ ] Event type parity confirmed
- [ ] Field trust parity confirmed

## Infrastructure Requirements

- [ ] Staging deployment profile validated
- [ ] Docker images buildable
- [ ] Health checks pass

## Post-Release

- [ ] Git tag created (format: `v0.X.Y-alpha.Z`)
- [ ] CHANGELOG.md `[Unreleased]` section reset
- [ ] Next version planned
