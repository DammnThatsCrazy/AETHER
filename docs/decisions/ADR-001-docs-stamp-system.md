---
title: "ADR-001: Documentation Sync Stamp System"
slug: decisions/adr-001-docs-stamp-system
section: reference
visibility: I
audience: [architect, dev-senior, ops]
status: stable
since_version: "0.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
toc_depth: 2
---

# ADR-001: Documentation Source-Hash Drift System

**Status:** Accepted | **Date:** 2026-05-29

## Context

The repository contains authored Markdown documents that describe system
behaviour derived from source code (API contracts, entity schemas, event
registries, etc.). Without enforcement, these documents drift silently from
their source as code evolves — the classic "the code is the truth" problem.

A timestamp-based approach was evaluated and rejected: wall-clock times are
not reproducible. A Git-commit-only marker was also rejected as the canonical
truth because squash merges can discard the branch commit that was used as a
review anchor even when the resulting source bytes are unchanged.

## Decision

Every authored doc that has `source_files:` frontmatter carries a
`source_hashes:` mapping from each declared repo-relative path to a SHA-256
content marker. The `scripts/docs_drift.py --strict` CI check fails when the
current bytes for any declared source differ from that marker. Directory
sources are hashed as sorted tracked-file manifests. The comparison is
independent of commit ancestry, timestamps, branch names, and filesystem
traversal order.

`last_synced_commit: <sha>` is a legacy field accepted only while older pages
are migrated. `make docs-migrate` performs the one-time conversion; normal
updates use `make docs-generate-changed`, which changes only pages whose source
content actually differs. Hash refreshes remain a review step, not an approval
or a substitute for updating inaccurate prose.

Generated artifacts (`docs/_generated/*.json`, `docs/REPO-INDEX.md`,
`docs/AUTOMATION.md`) are regenerated deterministically by CI and are excluded
from the stamp system — they are not "authored."

### CI auto-commit behaviour

On pushes to `main`, if `docs/REPO-INDEX.md` or `docs/AUTOMATION.md` drift,
CI auto-commits them with `[skip ci]` in the message to prevent a feedback
loop where the bot commit re-triggers the same workflow run.

## Consequences

**Positive:**
- Drift is caught within one CI cycle of the offending source change.
- The source hash is a reproducible content anchor that survives rebase and
  squash merge operations.
- CI identifies the exact source-linked page and source path that needs review.

**Negative:**
- A source change still requires review of each page that declares that source,
  adding a deliberate step to the PR checklist.
- Only affected pages receive a small metadata update; unrelated pages remain
  untouched.

**Mitigation for noise:** Generated docs remain separately managed, and the
source-hash updater is scoped to content mismatches. The trusted-main
`[skip ci]` auto-sync behavior remains limited to generated repository indexes;
it never rewrites authored source-linked pages.

## Exit Criteria

This system should be reconsidered when:
- OpenAPI spec generation is automated (backend routes → `openapi.json`), at
  which point drift detection becomes schema-diff rather than SHA-stamp.
- A docs-as-code platform (e.g., ReadTheDocs, Mintlify) with native sync hooks
  is adopted.
