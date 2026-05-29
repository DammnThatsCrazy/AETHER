---
title: "ADR-001: Documentation Sync Stamp System"
status: Accepted
date: "2026-05-29"
---

# ADR-001: Documentation Sync Stamp System

**Status:** Accepted  
**Date:** 2026-05-29

## Context

The repository contains 37+ authored Markdown documents that describe system
behaviour derived from source code (API contracts, entity schemas, event
registries, etc.). Without enforcement, these documents drift silently from
their source as code evolves — the classic "the code is the truth" problem.

A timestamp-based approach was evaluated but rejected: wall-clock times are
not reproducible and do not identify *which* source commit the doc was last
reviewed against.

## Decision

Every authored doc that has `source_files:` frontmatter also carries a
`last_synced_commit: <sha>` field. The `scripts/docs_drift.py --strict` CI
check fails if any `source_files` path has been modified in a commit after the
declared SHA.

Generated artifacts (`docs/_generated/*.json`, `docs/REPO-INDEX.md`,
`docs/AUTOMATION.md`) are regenerated deterministically by CI and are excluded
from the stamp system — they are not "authored."

### CI auto-commit behaviour

On pushes to `main`, if `docs/REPO-INDEX.md` or `docs/AUTOMATION.md` drift,
CI auto-commits them with `[skip ci]` in the message to prevent a feedback
loop where the bot commit re-triggers the same workflow run.

## Consequences

**Positive:**
- Drift is caught within one CI cycle of the offending source commit.
- The stamp SHA provides a reproducible review anchor — a reviewer can run
  `git log <sha>..HEAD -- <source_files>` to see exactly what changed.

**Negative:**
- Every source change requires a follow-up doc stamp update, adding a step to
  the PR checklist.
- Docs files appear in git diff on every stamp update, creating noise in PRs
  that are purely code changes.

**Mitigation for noise:** The `[skip ci]` flag on auto-commits prevents
feedback loops. PR diff noise is addressed by excluding stamp-only changes from
the PR size gate (`pr-size` job in `repo-health.yml`).

## Exit Criteria

This system should be reconsidered when:
- OpenAPI spec generation is automated (backend routes → `openapi.json`), at
  which point drift detection becomes schema-diff rather than SHA-stamp.
- A docs-as-code platform (e.g., ReadTheDocs, Mintlify) with native sync hooks
  is adopted.
